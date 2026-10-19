#!/usr/bin/env python3
"""Συλλέγει τα πρόσφατα άρθρα από τα feeds του feeds.yaml.

- Κατεβάζει όλα τα feeds παράλληλα, με χρονικό όριο ανά feed.
- Κάθε κατηγορία μπορεί να έχει δικό της παράθυρο (`hours`).
- Παραλείπει άρθρα που εμφανίστηκαν ήδη στις 2 προηγούμενες μέρες,
  ώστε τα δελτία να μην επαναλαμβάνονται.
- Round-robin ανά εκδότη, ώστε κανένας να μην κυριαρχεί.

Έξοδος: data/raw/YYYY-MM-DD.json
"""
from __future__ import annotations

import argparse
import html
import json
import re
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic
from urllib.parse import urlparse, urlunparse

import feedparser
import yaml

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "Mozilla/5.0 (compatible; DailyBriefBot/1.0; RSS reader)"
FEED_TIMEOUT = 20  # δευτερόλεπτα ανά feed
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


def download(url: str):
    """Επιστρέφει (url, feed, error, δευτερόλεπτα)."""
    t0 = monotonic()
    try:
        feed = feedparser.parse(url, agent=USER_AGENT)
    except Exception as e:  # π.χ. timeout
        return url, None, type(e).__name__, monotonic() - t0
    status = feed.get("status")
    if status and status >= 400:
        return url, None, f"HTTP {status}", monotonic() - t0
    if feed.bozo and not feed.entries:
        return url, None, type(feed.bozo_exception).__name__, monotonic() - t0
    return url, feed, None, monotonic() - t0


def previous_urls(day: str, days_back: int = 2) -> set[str]:
    """URLs που χρησιμοποιήθηκαν ήδη στα raw των προηγούμενων ημερών."""
    seen = set()
    d0 = datetime.strptime(day, "%Y-%m-%d")
    for i in range(1, days_back + 1):
        p = ROOT / "data" / "raw" / f"{(d0 - timedelta(days=i)):%Y-%m-%d}.json"
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                for cat in raw.get("categories", {}).values():
                    seen.update(normalize_url(it["url"]) for it in cat.get("items", []))
            except (ValueError, KeyError):
                pass
    return seen


def build_category(cfg: dict, results: dict, since: datetime, already: set[str]):
    per_feed, failed, report = [], [], {}
    seen_urls, seen_titles = set(already), set()
    for url in cfg["feeds"]:
        _, feed, err, secs = results[url]
        if err:
            failed.append(f"{url} ({err})")
            report[url] = {"items": 0, "status": err, "secs": round(secs, 1)}
            continue
        src = (feed.feed.get("title") or "").strip() or urlparse(url).netloc.removeprefix("www.")
        bucket, old, dup = [], 0, 0
        for e in feed.entries:
            link, title = e.get("link"), clean_text(e.get("title", ""), 200)
            if not link or not title:
                continue
            ts = entry_time(e)
            if ts and ts < since:
                old += 1
                continue
            nu, tk = normalize_url(link), title_key(title)
            if nu in seen_urls or tk in seen_titles:
                dup += 1
                continue
            seen_urls.add(nu)
            seen_titles.add(tk)
            bucket.append({
                "title": title,
                "url": link,
                "source": src,
                "published": ts.isoformat() if ts else None,
                "summary": clean_text(e.get("summary", "")),
            })
        bucket.sort(key=lambda i: i["published"] or "", reverse=True)
        status = "ok" if bucket else (f"κανένα νέο ({old} παλιά, {dup} ήδη)" if feed.entries else "άδειο feed")
        report[url] = {"items": len(bucket), "status": status, "secs": round(secs, 1)}
        per_feed.append(bucket)

    items = []
    for i in range(max((len(b) for b in per_feed), default=0)):
        items += [b[i] for b in per_feed if i < len(b)]
    return items, failed, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=26, help="προεπιλεγμένο παράθυρο σε ώρες")
    ap.add_argument("--date", help="ημερομηνία αρχείου YYYY-MM-DD (default σήμερα UTC)")
    args = ap.parse_args()

    socket.setdefaulttimeout(FEED_TIMEOUT)
    config = yaml.safe_load((ROOT / "feeds.yaml").read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    day = args.date or now.strftime("%Y-%m-%d")
    already = previous_urls(day)

    all_urls = list(dict.fromkeys(u for c in config["categories"].values() for u in c["feeds"]))
    t0 = monotonic()
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = {r[0]: r for r in pool.map(download, all_urls)}
    print(f"Κατέβηκαν {len(all_urls)} feeds σε {monotonic() - t0:.0f}s "
          f"(παράλειψη {len(already)} άρθρων προηγούμενων ημερών)")

    out = {"date": day, "generated": now.isoformat(), "categories": {}}
    total = 0
    for key, cfg in config["categories"].items():
        since = now - timedelta(hours=cfg.get("hours", args.hours))
        items, failed, report = build_category(cfg, results, since, already)
        already |= {normalize_url(i["url"]) for i in items}  # ίδιο άρθρο όχι σε 2 ενότητες
        out["categories"][key] = {"items": items[:60], "failed_feeds": failed, "feeds": report}
        total += len(items)
        print(f"[{key}] {len(items)} άρθρα")
        for url, r in report.items():
            mark = "✓" if r["items"] else "✗"
            extra = "" if r["status"] == "ok" else f"  — {r['status']}"
            print(f"    {mark} {r['items']:3d}  {url}{extra}")

    path = ROOT / "data" / "raw" / f"{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Σύνολο {total} άρθρα → {path.relative_to(ROOT)}")
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
