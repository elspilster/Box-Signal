#!/usr/bin/env python3
"""Export a safe, read-only Bubbles search snapshot while the crawler runs.
Run from the Bubbles directory: py export_search.py
Creates bubbles_search.json. Never changes the live database.
"""
import json, sqlite3, pathlib, sys, re
from datetime import datetime, timezone
ROOT = pathlib.Path(__file__).resolve().parent
DB = ROOT / "bubbles.db"
OUT = ROOT / "bubbles_search.json"
MAX_PAGES = 2000
def pick(names, candidates):
    lookup = {x.lower(): x for x in names}
    return next((lookup[x] for x in candidates if x in lookup), None)
def main():
    if not DB.exists():
        sys.exit(f"Cannot find {DB}. Put this script beside app.py and bubbles.db.")
    # SQLite online backup provides a transactionally consistent snapshot.
    src = sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True, timeout=30)
    dst = sqlite3.connect(":memory:")
    try:
        src.backup(dst, pages=100, sleep=0.1)
    finally:
        src.close()
    tables = [r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    chosen = None
    for table in sorted(tables, key=lambda x: ("page" not in x.lower(), x)):
        cols = [r[1] for r in dst.execute('PRAGMA table_info("' + table.replace('"','""') + '")')]
        url = pick(cols, ("url","page_url","canonical_url"))
        title = pick(cols, ("title","page_title"))
        body = pick(cols, ("text","body_text","content","page_text","body","clean_text","main_text","description","snippet"))
        if url and (title or body):
            chosen = (table, cols, url, title, body)
            break
    if not chosen:
        sys.exit("Could not identify a page table. Tables: " + ", ".join(tables) + ". Send Kollin the schema and we'll adapt the exporter.")
    table, cols, url, title, body = chosen
    description = pick(cols, ("description","meta_description","summary","snippet"))
    fields = [url] + [x for x in (title, description, body) if x and x != url]
    fields = list(dict.fromkeys(fields))
    quoted = lambda x: '"' + x.replace('"','""') + '"'
    sql = "SELECT " + ", ".join(map(quoted, fields)) + " FROM " + quoted(table) + " WHERE " + quoted(url) + " IS NOT NULL LIMIT ?"
    pages = []
    seen = set()
    for values in dst.execute(sql, (MAX_PAGES * 2,)):
        record = dict(zip(fields, values))
        link = str(record.get(url) or "").strip()
        if not link.startswith(("https://","http://")) or link in seen:
            continue
        seen.add(link)
        clean = lambda x, n: re.sub(r"\\s+", " ", re.sub(r"<[^>]*>", " ", str(x or ""))).strip()[:n]
        pages.append({"url":link, "title":clean(record.get(title) if title else "", 180) or link,
                      "description":clean(record.get(description) if description else "", 350),
                      "text":clean(record.get(body) if body else "", 1400)})
        if len(pages) >= MAX_PAGES: break
    payload = {"generated_at":datetime.now(timezone.utc).isoformat(),"source":"Bubbles local crawler snapshot","pages":pages}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",",":")), encoding="utf-8")
    print(f"Exported {len(pages)} pages from {table} to {OUT}")
    print("Crawler remains running. This file contains public page text and URLs; review before publishing.")
if __name__ == "__main__":
    main()
