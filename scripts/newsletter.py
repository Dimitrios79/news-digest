#!/usr/bin/env python3
"""Στέλνει το σημερινό digest στους συνδρομητές του Buttondown (προαιρετικό).

Ενεργοποιείται μόνο αν υπάρχει το secret BUTTONDOWN_API_KEY.
NEWSLETTER_LANG=el|en (default el). NEWSLETTER_STATUS=draft για δοκιμή
χωρίς αποστολή (το email μένει ως πρόχειρο στο Buttondown).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from build import UI, human_date  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def render_markdown(d: dict, site: dict, lang: str) -> str:
    ui, base = UI[lang], site["base_url"].rstrip("/")
    out = [f"## {ui['glance']}", ""]
    out += [f"- {g}" for g in d["glance"][lang]]
    sp = site.get("sponsor") or {}
    if sp.get("url") and sp.get(f"text_{lang}"):
        out += ["", f"> **{sp.get(f'label_{lang}') or ui['ad']}:** [{sp[f'text_{lang}']}]({sp['url']})"]
    for sec in d["sections"]:
        out += ["", f"## {sec['title'][lang]}", ""]
        for s in sec["stories"]:
            srcs = ", ".join(f"[{x['name']}]({x['url']})" for x in s["sources"])
            out.append(f"**{s['title'][lang]}**  ")
            if s["summary"][lang]:
                out.append(f"{s['summary'][lang]}  ")
            out += [f"_{ui['sources']}: {srcs}_", ""]
    out += ["---", f"[{base}/{lang}/{d['date']}/]({base}/{lang}/{d['date']}/)", "", f"_{ui['ai_note']}_"]
    return "\n".join(out)


def main() -> int:
    key = os.environ.get("BUTTONDOWN_API_KEY")
    if not key:
        print("Χωρίς BUTTONDOWN_API_KEY — παράλειψη newsletter.")
        return 0
    lang = os.environ.get("NEWSLETTER_LANG", "el")
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = ROOT / "content" / f"{day}.json"
    if not path.exists():
        print("Δεν υπάρχει σημερινό digest — παράλειψη.")
        return 0
    d = json.loads(path.read_text(encoding="utf-8"))
    site = yaml.safe_load((ROOT / "site.yaml").read_text(encoding="utf-8"))

    payload = {
        "subject": f"{site['name']} — {human_date(day, lang)}",
        "body": render_markdown(d, site, lang),
        "status": os.environ.get("NEWSLETTER_STATUS", "about_to_send"),
    }
    req = urllib.request.Request(
        "https://api.buttondown.com/v1/emails",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Token {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"Buttondown: HTTP {r.status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
