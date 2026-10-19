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
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-5-5"
# Σειρά προτίμησης: αν το πρώτο εξαντλήσει το δωρεάν όριο, περνάμε στο επόμενο.
# Το gpt-4o-mini έχει πολύ μεγαλύτερο ημερήσιο όριο στο δωρεάν tier.
GITHUB_MODELS = [m.strip() for m in (os.environ.get("GITHUB_MODEL") or
                 "openai/gpt-4o,openai/gpt-4o-mini").split(",") if m.strip()]
GITHUB_ENDPOINT = "https://models.github.ai/inference/chat/completions"

NEUTRALITY_RULES = """\
Είσαι συντάκτης ενός ουδέτερου ημερήσιου δελτίου ειδήσεων. Κανόνες:
- Μόνο γεγονότα: ποιος, τι, πότε, πού, και τι επιβεβαιωμένο αποτέλεσμα υπάρχει.
- Χωρίς επίθετα αξιολόγησης, χωρίς συναισθηματική γλώσσα, χωρίς εικασίες, χωρίς γνώμη.
- Δηλώσεις προσώπων αποδίδονται ρητά ("σύμφωνα με…", "δήλωσε ότι…"), ποτέ ως γεγονός.
- Αν οι πηγές διαφωνούν, το λες με μία φράση και δεν παίρνεις θέση.
- Γράφεις ΠΑΝΤΑ με δικά σου λόγια. Οι τίτλοι και τα αποσπάσματα των πηγών είναι μόνο
  πρώτη ύλη για τα γεγονότα — ποτέ κείμενο προς μεταφορά:
  · Ο τίτλος σου έχει διαφορετική δομή και λεξιλόγιο από κάθε τίτλο πηγής: άλλο υποκείμενο
    στην αρχή, άλλο ρήμα, χωρίς να κρατάς σειρές 3+ λέξεων από πηγή.
  · Η περίληψη ξεκινά από το πιο ουσιαστικό γεγονός, όχι από ό,τι ξεκινά η πηγή, και
    συνδυάζει στοιχεία από όλες τις πηγές της είδησης.
  · Μην αναδιατυπώνεις πρόταση-πρόταση· ξαναγράφεις από την αρχή σαν να το εξηγείς σε συνάδελφο.
  · Πρόσθεσε ένα στοιχείο πλαισίου όταν βοηθά (π.χ. ποιος επηρεάζεται, τι προηγήθηκε),
    μόνο αν προκύπτει από τις πηγές.
  · Ποικιλία: διαδοχικές ειδήσεις δεν ξεκινούν με την ίδια λέξη ή την ίδια σύνταξη.
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


class QuotaError(RuntimeError):
    """Το μοντέλο εξάντλησε το όριό του — δεν έχει νόημα να ξαναδοκιμάσουμε."""


class GitHubModelsClient:
    """OpenAI-compatible API του GitHub Models — χωρίς εξαρτήσεις, μόνο urllib."""
    max_items = 25  # το δωρεάν tier έχει όριο tokens ανά αίτημα

    def __init__(self, token: str):
        self.token = token
        self.models = list(GITHUB_MODELS)

    @property
    def name(self) -> str:
        return f"GitHub Models ({self.models[0]})" if self.models else "GitHub Models"

    def _post(self, model: str, tool: dict, prompt: str) -> dict:
        body = {
            "model": model,
            "max_tokens": 4000,
            "temperature": 0.5,
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
                status, raw = r.status, r.read().decode(errors="replace")
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")[:300]
            if e.code == 429 or "RateLimit" in text or "quota" in text.lower():
                raise QuotaError(f"{model}: όριο χρήσης (HTTP {e.code}) {text}") from e
            raise RuntimeError(f"{model}: HTTP {e.code} {text}") from e
        if not raw.strip():
            # Κενή απάντηση: στην πράξη σημαίνει εξαντλημένο όριο
            raise QuotaError(f"{model}: κενή απάντηση (HTTP {status}) — πιθανώς εξαντλημένο όριο")
        try:
            data = json.loads(raw)
            msg = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError) as e:
            raise RuntimeError(f"{model}: μη αναμενόμενη απάντηση (HTTP {status}): {raw[:200]}") from e
        for call in msg.get("tool_calls") or []:
            args = call["function"].get("arguments") or ""
            if args.strip():
                return json.loads(args)
        content = (msg.get("content") or "").strip()
        if content.startswith("{"):
            return json.loads(content)
        raise RuntimeError(f"{model}: το μοντέλο δεν επέστρεψε δομημένη απάντηση")

    def tool(self, tool: dict, prompt: str) -> dict:
        while self.models:
            try:
                return self._post(self.models[0], tool, prompt)
            except QuotaError as e:
                dropped = self.models.pop(0)
                print(f"  {e}")
                if self.models:
                    print(f"  → αλλαγή μοντέλου: {dropped} → {self.models[0]}")
        raise QuotaError("όλα τα μοντέλα του GitHub Models εξάντλησαν το όριό τους")


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
        except QuotaError:
            raise  # δεν βοηθά η αναμονή
        except Exception as e:  # δίκτυο / κακό JSON
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
            "_ids": ids,
        })
    try:
        n = enforce_originality(client, stories, items)
        if n:
            print(f"  ξαναγράφτηκαν {n} ειδήσεις λόγω ομοιότητας με τις πηγές")
    except Exception as e:
        print(f"  έλεγχος πρωτοτυπίας απέτυχε ({e}) — κρατάμε το αρχικό κείμενο")
    for st in stories:
        st.pop("_ids", None)
    return stories


# ── Έλεγχος πρωτοτυπίας ────────────────────────────────────────────────
# Συγκρίνει κάθε κείμενο με τα κείμενα των πηγών του. Αν μοιράζεται σειρές λέξεων
# ή μοιάζει πολύ συνολικά, ζητά από το μοντέλο να το ξαναγράψει.
WORD_RE = re.compile(r"\w+", re.UNICODE)
SHINGLE = 4           # σειρά 4 λέξεων = "αντιγραφή φράσης"
MAX_RATIO = 0.55      # συνολική ομοιότητα χαρακτήρων


def _words(t: str) -> list[str]:
    return [w.lower() for w in WORD_RE.findall(t or "")]


def _shingles(words: list[str], n: int = SHINGLE) -> set[tuple]:
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def too_similar(text: str, sources: list[str]) -> bool:
    w = _words(text)
    if len(w) < SHINGLE:
        return False
    mine = _shingles(w)
    for src in sources:
        sw = _words(src)
        if mine & _shingles(sw):
            return True
        if SequenceMatcher(None, " ".join(w), " ".join(sw)).ratio() > MAX_RATIO:
            return True
    return False


REWRITE_TOOL = {
    "name": "rewrite_stories",
    "description": "Επιστρέφει τις ειδήσεις ξαναγραμμένες με εντελώς δικά σου λόγια.",
    "input_schema": {
        "type": "object",
        "properties": {"stories": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "title_el": {"type": "string"}, "title_en": {"type": "string"},
                "summary_el": {"type": "string"}, "summary_en": {"type": "string"},
            },
            "required": ["id", "title_el", "title_en", "summary_el", "summary_en"],
        }}},
        "required": ["stories"],
    },
}


def enforce_originality(client, stories: list[dict], items: list[dict]) -> int:
    """Ξαναγράφει τις ειδήσεις που μοιάζουν με τις πηγές. Επιστρέφει πόσες άλλαξαν."""
    flagged = []
    for idx, s in enumerate(stories):
        srcs = [t for i in s["_ids"] for t in (items[i]["title"], items[i]["summary"])]
        if any(too_similar(s[f][l], srcs) for f in ("title", "summary") for l in ("el", "en")):
            flagged.append((idx, srcs))
    if not flagged:
        return 0
    blocks = []
    for idx, srcs in flagged:
        s = stories[idx]
        blocks.append(
            f"[{idx}]\nΤΡΕΧΟΝ EL: {s['title']['el']} — {s['summary']['el']}\n"
            f"ΤΡΕΧΟΝ EN: {s['title']['en']} — {s['summary']['en']}\n"
            "ΠΗΓΕΣ (ΜΗΝ ΤΙΣ ΑΝΤΙΓΡΑΨΕΙΣ):\n" + "\n".join(f"  - {t}" for t in srcs if t)
        )
    prompt = (
        "Οι παρακάτω ειδήσεις μοιάζουν υπερβολικά με τη διατύπωση των πηγών. Ξαναγράψε "
        "τίτλο και περίληψη (EL και EN) ώστε να μη μοιράζονται καμία σειρά 3+ λέξεων με τις "
        "πηγές: άλλη δομή, άλλο ρήμα, άλλη σειρά πληροφοριών. Ίδια γεγονότα, τίποτα καινούργιο. "
        "Κράτα το id.\n\n" + "\n\n".join(blocks)
    )
    out = call_tool(client, REWRITE_TOOL, prompt)
    changed = 0
    for r in out.get("stories", []):
        i = r.get("id")
        if isinstance(i, int) and 0 <= i < len(stories):
            stories[i]["title"] = {"el": r["title_el"], "en": r["title_en"]}
            stories[i]["summary"] = {"el": r["summary_el"], "en": r["summary_en"]}
            changed += 1
    return changed


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

    sections, ai_sections = [], 0
    for key, cfg in config["categories"].items():
        items = raw["categories"].get(key, {}).get("items", [])
        if not items:
            continue
        stories = None
        if client and getattr(client, "models", [None]):  # υπάρχει ακόμα διαθέσιμο μοντέλο
            try:
                stories = ai_section(client, cfg, items)
                ai_sections += 1
            except Exception as e:
                print(f"[{key}] AI απέτυχε ({e}) — fallback σε τίτλους")
        if stories is None:
            stories = fallback_section(cfg, items)
        if stories:
            sections.append({"key": key, "title": {"el": cfg["title_el"], "en": cfg["title_en"]},
                             "stories": stories})
            print(f"[{key}] {len(stories)} ειδήσεις")

    if not sections:
        print("Καμία είδηση — δεν γράφτηκε digest.")
        return 1

    glance = None
    if client and ai_sections:
        heads = "\n".join(f"- {s['title']['el']} / {s['title']['en']}"
                          for sec in sections for s in sec["stories"][:3])
        try:
            g = call_tool(client, GLANCE_TOOL, f"Οι κορυφαίες ειδήσεις της ημέρας ανά ενότητα:\n{heads}")
            glance = {"el": g["glance_el"], "en": g["glance_en"]}
            meta = {"el": g["meta_el"][:160], "en": g["meta_en"][:160]}
        except Exception as e:
            print(f"Glance απέτυχε ({e}) — fallback")
    if ai_sections == 0:
        glance = None
    if glance is None:
        tops = [sec["stories"][0]["title"]["el"] for sec in sections]
        glance = {"el": tops, "en": tops}
        meta = {"el": "; ".join(tops)[:155], "en": "; ".join(tops)[:155]}

    path = ROOT / "content" / f"{day}.json"
    # Ποτέ μην αντικαθιστάς καλύτερο δελτίο με χειρότερο (π.χ. AI → σκέτοι τίτλοι
    # επειδή εξαντλήθηκε το όριο σε δεύτερη εκτέλεση της ίδιας μέρας).
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            prev_ai = prev.get("ai_sections", len(prev.get("sections", [])) if prev.get("ai") else 0)
        except ValueError:
            prev_ai = 0
        if prev_ai > ai_sections:
            print(f"Υπάρχει ήδη καλύτερο δελτίο για {day} ({prev_ai} ενότητες με AI έναντι {ai_sections}) — το κρατάμε.")
            return 0

    digest = {"date": day, "generated": datetime.now(timezone.utc).isoformat(),
              "ai": client.name if (client and ai_sections) else None, "ai_sections": ai_sections,
              "glance": glance, "meta": meta, "sections": sections}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Digest → {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
