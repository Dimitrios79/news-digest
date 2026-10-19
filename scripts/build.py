#!/usr/bin/env python3
"""Χτίζει το στατικό site (site/) από τα content/*.json.

Δομή εξόδου:
  /                     τελευταίο digest (EL)
  /el/YYYY-MM-DD/       ημερήσιες σελίδες   /en/YYYY-MM-DD/
  /el/archive/          αρχείο              /en/archive/
  /el/about/            σχετικά & απόρρητο  /en/about/
  /el/feed.xml          RSS                 /en/feed.xml
  /sitemap.xml /robots.txt /ads.txt (αν υπάρχει AdSense)
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site"
LANGS = ("el", "en")

MONTHS_EL = ["Ιανουαρίου", "Φεβρουαρίου", "Μαρτίου", "Απριλίου", "Μαΐου", "Ιουνίου",
             "Ιουλίου", "Αυγούστου", "Σεπτεμβρίου", "Οκτωβρίου", "Νοεμβρίου", "Δεκεμβρίου"]
DAYS_EL = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]

UI = {
    "el": {
        "glance": "Με μια ματιά", "archive": "Αρχείο", "about": "Σχετικά", "today": "Σήμερα",
        "sources": "Πηγές", "prev": "Προηγούμενη", "next": "Επόμενη", "other": "English",
        "subscribe_title": "Το δελτίο κάθε πρωί στο email σου",
        "subscribe_text": "Ένα email την ημέρα. Χωρίς spam, διαγραφή με ένα κλικ.",
        "email_ph": "το email σου", "subscribe_btn": "Εγγραφή",
        "donate": "Στήριξε το δελτίο", "ad": "Διαφήμιση",
        "ai_note": "Οι περιλήψεις συντάσσονται αυτόματα από AI με βάση τις συνδεδεμένες πηγές. "
                   "Για λεπτομέρειες και διορθώσεις ισχύει πάντα το πρωτότυπο άρθρο.",
        "archive_title": "Αρχείο δελτίων", "stories": "ειδήσεις",
    },
    "en": {
        "glance": "At a glance", "archive": "Archive", "about": "About", "today": "Today",
        "sources": "Sources", "prev": "Previous", "next": "Next", "other": "Ελληνικά",
        "subscribe_title": "Get the brief in your inbox every morning",
        "subscribe_text": "One email a day. No spam, one-click unsubscribe.",
        "email_ph": "your email", "subscribe_btn": "Subscribe",
        "donate": "Support the brief", "ad": "Advertisement",
        "ai_note": "Summaries are written automatically by AI from the linked sources. "
                   "The original article is always the authoritative version.",
        "archive_title": "Brief archive", "stories": "stories",
    },
}


def human_date(day: str, lang: str) -> str:
    d = datetime.strptime(day, "%Y-%m-%d")
    if lang == "el":
        return f"{DAYS_EL[d.weekday()]} {d.day} {MONTHS_EL[d.month - 1]} {d.year}"
    return d.strftime("%A, %B %-d, %Y")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    site = yaml.safe_load((ROOT / "site.yaml").read_text(encoding="utf-8"))
    # BASE_URL=http://localhost:8000 για τοπική προεπισκόπηση
    site["base_url"] = os.environ.get("BASE_URL", site["base_url"]).rstrip("/")
    digests = sorted(
        (json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "content").glob("*.json")),
        key=lambda d: d["date"], reverse=True,
    )
    if not digests:  # πρώτο push, πριν το πρώτο digest
        write(OUT / "index.html", f"<!doctype html><meta charset=utf-8><title>{site['name']}</title>"
              "<p style='font-family:sans-serif;padding:2rem'>Το πρώτο δελτίο έρχεται σύντομα. / First brief coming soon.</p>")
        print("Δεν υπάρχουν digests ακόμα — γράφτηκε placeholder.")
        return

    env = Environment(loader=FileSystemLoader(ROOT / "templates"),
                      autoescape=select_autoescape(["html", "xml"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.globals.update(site=site, B=site["base_url"], human_date=human_date)

    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(ROOT / "static", OUT / "static")

    urls = []
    for lang in LANGS:
        ui, other = UI[lang], "en" if lang == "el" else "el"
        common = dict(lang=lang, other=other, ui=ui)
        for i, d in enumerate(digests):
            ctx = dict(common, d=d,
                       newer=digests[i - 1]["date"] if i > 0 else None,
                       older=digests[i + 1]["date"] if i + 1 < len(digests) else None,
                       path=f"/{lang}/{d['date']}/", alt_path=f"/{other}/{d['date']}/")
            html = env.get_template("day.html").render(**ctx)
            write(OUT / lang / d["date"] / "index.html", html)
            urls.append((f"/{lang}/{d['date']}/", d["date"]))
            if i == 0:  # η αρχική κάθε γλώσσας = τελευταίο digest, canonical στη μέρα
                write(OUT / lang / "index.html", html)
                if lang == "el":
                    write(OUT / "index.html", html)

        write(OUT / lang / "archive" / "index.html", env.get_template("archive.html").render(
            **common, digests=digests, path=f"/{lang}/archive/", alt_path=f"/{other}/archive/"))
        write(OUT / lang / "about" / "index.html", env.get_template("about.html").render(
            **common, path=f"/{lang}/about/", alt_path=f"/{other}/about/"))
        write(OUT / lang / "feed.xml", env.get_template("feed.xml").render(
            **common, digests=digests[:30],
            rfc822=lambda s: format_datetime(datetime.fromisoformat(s))))
        urls += [(f"/{lang}/archive/", digests[0]["date"]), (f"/{lang}/about/", None)]

    write(OUT / "sitemap.xml", env.get_template("sitemap.xml").render(urls=urls))
    write(OUT / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {site['base_url']}/sitemap.xml\n")
    if site.get("adsense_client"):
        pub = site["adsense_client"].removeprefix("ca-")
        write(OUT / "ads.txt", f"google.com, {pub}, DIRECT, f08c47fec0942fa0\n")
    write(OUT / "404.html", env.get_template("404.html").render(lang="el", other="en", ui=UI["el"],
                                                               path="/", alt_path="/en/"))
    (OUT / ".nojekyll").touch()
    print(f"Site → {OUT.relative_to(ROOT)}/ ({len(digests)} ημέρες, {len(urls)} σελίδες)")


if __name__ == "__main__":
    main()
