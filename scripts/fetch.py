#!/usr/bin/env python3
"""Συλλέγει τα άρθρα των τελευταίων N ωρών από τα feeds του feeds.yaml.

Έξοδος: data/raw/YYYY-MM-DD.json
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import feedparser
import yaml

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "news-digest/1.0 (+https://github.com)"
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean_text(raw: str, limit: int = 400) -> str:
    text = html.unescape(TAG_RE.sub(" ", raw or ""))
    text = WS_RE.sub(" ", text).strip()
    return text[:limit].rsplit(" ", 1)[0] + "…" if len(text) > limit else text


def normalize_url(url: str) -> str:
    """Αφαιρεί tracking params/fragments για καλύτερο dedupe."""
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc.lower().removeprefix("www."), p.path.rstrip("/"), "", "", ""))


def title_key(title: str) -> str:
    return re.sub(r"[^\w]+", "", title.lower())[:80]


def entry_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def source_name(feed, url: str) -> str:
    name = (feed.feed.get("title") or "").strip()
    return name or urlparse(url).netloc.removeprefix("www.")


def fetch_category(cfg: dict, since: datetime) -> tuple[list[dict], list[str]]:
    items, failed = [], []
    seen_urls, seen_titles = set(), set()
    for url in cfg["feeds"]:
        feed = feedparser.parse(url, agent=USER_AGENT)
        if feed.bozo and not feed.entries:
            failed.append(f"{url} ({type(feed.bozo_exception).__name__})")
            continue
        src = source_name(feed, url)
        for e in feed.entries:
            link, title = e.get("link"), clean_text(e.get("title", ""), 200)
            if not link or not title:
                continue
            ts = entry_time(e)
            if ts and ts < since:
                continue
            # Google News: ο πραγματικός εκδότης είναι στο <source>
            pub = e.get("source", {}).get("title") if isinstance(e.get("source"), dict) else None
            nu, tk = normalize_url(link), title_key(title)
            if nu in seen_urls or tk in seen_titles:
                continue
            seen_urls.add(nu)
            seen_titles.add(tk)
            items.append({
                "title": title,
                "url": link,
                "source": pub or src,
                "published": ts.isoformat() if ts else None,
                "summary": clean_text(e.get("summary", "")),
            })
    items.sort(key=lambda i: i["published"] or "", reverse=True)
    return items, failed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=26, help="παράθυρο σε ώρες (default 26)")
    ap.add_argument("--date", help="ημερομηνία αρχείου YYYY-MM-DD (default σήμερα UTC)")
    args = ap.parse_args()

    config = yaml.safe_load((ROOT / "feeds.yaml").read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=args.hours)
    day = args.date or now.strftime("%Y-%m-%d")

    out = {"date": day, "generated": now.isoformat(), "categories": {}}
    total = 0
    for key, cfg in config["categories"].items():
        items, failed = fetch_category(cfg, since)
        out["categories"][key] = {"items": items[:60], "failed_feeds": failed}
        total += len(items)
        print(f"[{key}] {len(items)} άρθρα" + (f", αποτυχημένα feeds: {failed}" if failed else ""))

    path = ROOT / "data" / "raw" / f"{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Σύνολο {total} άρθρα → {path.relative_to(ROOT)}")
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
