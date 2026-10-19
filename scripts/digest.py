#!/usr/bin/env python3
"""Γράφει το ημερήσιο digest (Ελληνικά + Αγγλικά) από τα raw άρθρα.

Πάροχος AI (αυτόματη επιλογή):
  1. ANTHROPIC_API_KEY  → Claude (επί πληρωμή, καλύτερη ποιότητα)
  2. GITHUB_TOKEN       → GitHub Models (δωρεάν μέσα σε GitHub Actions)
  3. τίποτα             → απλή λίστα τίτλων + links (το site δεν σπάει ποτέ)

Έξοδος: content/YYYY-MM-DD.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-5-5"
GITHUB_MODEL = os.environ.get("GITHUB_MODEL") or "openai/gpt-4o"
GITHUB_ENDPOINT = "https://models.github.ai/inference/chat/completions"

NEUTRALITY_RULES = """\
Είσαι συντάκτης ενός ουδέτερου ημερήσιου δελτίου ειδήσεων. Κανόνες:
- Μόνο γεγονότα: ποιος, τι, πότε, πού, και τι επιβεβαιωμένο αποτέλεσμα υπάρχει.
- Χωρίς επίθετα αξιολόγησης, χωρίς συναισθηματική γλώσσα, χωρίς εικασίες, χωρίς γνώμη.
- Δηλώσεις προσώπων αποδίδονται ρητά ("σύμφωνα με…", "δήλωσε ότι…"), ποτέ ως γεγονός.
- Αν οι πηγές διαφωνούν, το λες με μία φράση και δεν παίρνεις θέση.
- Γράφεις με δικά σου λόγια· δεν αντιγράφεις φράσεις από τις πηγές.
- Συγχωνεύεις άρθρα που καλύπτουν το ίδιο γεγονός σε μία είδηση με όλες τις πηγές.
- Επιλέγεις με βάση τη σημασία και τον αντίκτυπο, όχι το πόσο εντυπωσιακός είναι ο τίτλος.
- Αγνοείς διαφημιστικά, lifestyle, αθλητικά κουτσομπολιά και clickbait.
- Η ελληνική και η αγγλική εκδοχή λένε ακριβώς το ίδιο περιεχόμενο."""

STORY_SCHEMA = {
    "type": "object",
    "properties": {
        "title_el": {"type": "string", "description": "Ουδέτερος τίτλος, έως 14 λέξεις"},
        "title_en": {"type": "string", "description": "Neutral headline, max 14 words"},
        "summary_el": {"type": "string", "description": "2-3 προτάσεις, μόνο γεγονότα"},
        "summary_en": {"type": "string", "description": "2-3 sentences, facts only"},
        "source_ids": {"type": "array", "items": {"type": "integer"},
                       "description": "Οι αριθμοί [n] των άρθρων που καλύπτουν την είδηση"},
    },
    "required": ["title_el", "title_en", "summary_el", "summary_en", "source_ids"],
}

CATEGORY_TOOL = {
    "name": "write_section",
    "description": "Καταγράφει τις ειδήσεις της ενότητας, ταξινομημένες κατά σημασία.",
    "input_schema": {
        "type": "object",
        "properties": {"stories": {"type": "array", "items": STORY_SCHEMA}},
        "required": ["stories"],
    },
}

GLANCE_TOOL = {
    "name": "write_glance",
    "description": "Η ημέρα με μια ματιά και SEO περιγραφή.",
    "input_schema": {
        "type": "object",
        "properties": {
            "glance_el": {"type": "array", "items": {"type": "string"}, "description": "4-5 κουκκίδες, μία πρόταση η καθεμία"},
            "glance_en": {"type": "array", "items": {"type": "string"}},
            "meta_el": {"type": "string", "description": "Περιγραφή σελίδας για μηχανές αναζήτησης, έως 155 χαρακτήρες"},
            "meta_en": {"type": "string", "description": "Search meta description, max 155 chars"},
        },
        "required": ["glance_el", "glance_en", "meta_el", "meta_en"],
    },
}


class ClaudeClient:
    name = "Claude"
    max_items = 60  # μεγάλο context

    def __init__(self):
        import anthropic
        self.client = anthropic.Anthropic()

    def tool(self, tool: dict, prompt: str) -> dict:
        resp = self.client.messages.create(
            model=ANTHROPIC_MODEL, max_tokens=8000, system=NEUTRALITY_RULES,
            tools=[tool], tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in resp.content:
            if block.type == "tool_use":
                return block.input
        raise RuntimeError("Το μοντέλο δεν επέστρεψε δομημένη απάντηση")


class GitHubModelsClient:
    """OpenAI-compatible API του GitHub Models — χωρίς εξαρτήσεις, μόνο urllib."""
    name = "GitHub Models"
    max_items = 30  # το δωρεάν tier έχει μικρότερο όριο εισόδου ανά αίτημα

    def __init__(self, token: str):
        self.token = token

    def tool(self, tool: dict, prompt: str) -> dict:
        body = {
            "model": GITHUB_MODEL,
            "max_tokens": 4000,
            "temperature": 0.2,
            "messages": [{"role": "system", "content": NEUTRALITY_RULES},
                         {"role": "user", "content": prompt}],
            "tools": [{"type": "function", "function": {
                "name": tool["name"], "description": tool["description"],
                "parameters": tool["input_schema"]}}],
            "tool_choice": {"type": "function", "function": {"name": tool["name"]}},
        }
        req = urllib.request.Request(
            GITHUB_ENDPOINT, data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                     "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from e
        msg = data["choices"][0]["message"]
        for call in msg.get("tool_calls") or []:
            return json.loads(call["function"]["arguments"])
        return json.loads(msg.get("content") or "{}")  # ορισμένα μοντέλα απαντούν σε content


def make_client():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ClaudeClient()
    if os.environ.get("GITHUB_TOKEN"):
        return GitHubModelsClient(os.environ["GITHUB_TOKEN"])
    return None


def call_tool(client, tool: dict, prompt: str) -> dict:
    last_err = None
    for attempt in range(3):
        try:
            return client.tool(tool, prompt)
        except Exception as e:  # δίκτυο / rate limit / κακό JSON
            last_err = e
            print(f"  προσπάθεια {attempt + 1} απέτυχε: {e}")
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Αποτυχία κλήσης μοντέλου: {last_err}")


def ai_section(client, cat_cfg: dict, items: list[dict]) -> list[dict]:
    items = items[: client.max_items]
    listing = "\n".join(
        f"[{i}] ({it['source']}) {it['title']}\n    {it['summary']}" for i, it in enumerate(items)
    )
    prompt = (
        f"Ενότητα: {cat_cfg['title_el']} / {cat_cfg['title_en']}\n"
        f"Διάλεξε έως {cat_cfg.get('max_items', 10)} σημαντικές ειδήσεις από τα παρακάτω άρθρα "
        f"του τελευταίου 24ώρου και γράψε τες.\n\n{listing}"
    )
    out = call_tool(client, CATEGORY_TOOL, prompt)
    stories = []
    for s in out.get("stories", []):
        ids = [i for i in s.get("source_ids", []) if isinstance(i, int) and 0 <= i < len(items)]
        if not ids:
            continue
        stories.append({
            "title": {"el": s["title_el"], "en": s["title_en"]},
            "summary": {"el": s["summary_el"], "en": s["summary_en"]},
            "sources": [{"name": items[i]["source"], "url": items[i]["url"]} for i in ids],
        })
    return stories


def fallback_section(cat_cfg: dict, items: list[dict]) -> list[dict]:
    return [{
        "title": {"el": it["title"], "en": it["title"]},
        "summary": {"el": "", "en": ""},
        "sources": [{"name": it["source"], "url": it["url"]}],
    } for it in items[: cat_cfg.get("max_items", 10)]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (default σήμερα UTC)")
    args = ap.parse_args()

    day = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw = json.loads((ROOT / "data" / "raw" / f"{day}.json").read_text(encoding="utf-8"))
    config = yaml.safe_load((ROOT / "feeds.yaml").read_text(encoding="utf-8"))

    client = make_client()
    print(f"Πάροχος AI: {client.name if client else 'κανένας — fallback σε λίστα τίτλων'}")

    sections = []
    for key, cfg in config["categories"].items():
        items = raw["categories"].get(key, {}).get("items", [])
        if not items:
            continue
        try:
            stories = ai_section(client, cfg, items) if client else fallback_section(cfg, items)
        except Exception as e:
            print(f"[{key}] AI απέτυχε ({e}) — fallback σε τίτλους")
            stories = fallback_section(cfg, items)
        if stories:
            sections.append({"key": key, "title": {"el": cfg["title_el"], "en": cfg["title_en"]},
                             "stories": stories})
            print(f"[{key}] {len(stories)} ειδήσεις")

    if not sections:
        print("Καμία είδηση — δεν γράφτηκε digest.")
        return 1

    glance = None
    if client:
        heads = "\n".join(f"- {s['title']['el']} / {s['title']['en']}"
                          for sec in sections for s in sec["stories"][:3])
        try:
            g = call_tool(client, GLANCE_TOOL, f"Οι κορυφαίες ειδήσεις της ημέρας ανά ενότητα:\n{heads}")
            glance = {"el": g["glance_el"], "en": g["glance_en"]}
            meta = {"el": g["meta_el"][:160], "en": g["meta_en"][:160]}
        except Exception as e:
            print(f"Glance απέτυχε ({e}) — fallback")
    if glance is None:
        tops = [sec["stories"][0]["title"]["el"] for sec in sections]
        glance = {"el": tops, "en": tops}
        meta = {"el": "; ".join(tops)[:155], "en": "; ".join(tops)[:155]}

    digest = {"date": day, "generated": datetime.now(timezone.utc).isoformat(),
              "ai": client.name if client else None, "glance": glance, "meta": meta, "sections": sections}
    path = ROOT / "content" / f"{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Digest → {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
