"""Command-line entry point.

    python run.py scrape     # crawl the site into SQLite and print what was found
    python run.py match      # pull the CRM, compare with the site, queue proposals, print a summary
    python run.py sync       # scrape + match (what the daily schedule runs)
    python run.py serve      # start the review app on http://127.0.0.1:5000
"""
import json
import sys
from collections import defaultdict

import matcher
import proposals
import scraper
from crm import CRM
from db import connect

TYPE_ORDER = ["field_update", "reparent", "chow", "create", "duplicate", "orphan", "decision"]


def load_sites(conn):
    rows = [dict(r) for r in conn.execute("SELECT * FROM site_locations ORDER BY slug")]
    for r in rows:
        r["care_offerings"] = json.loads(r["care_offerings"])
    return rows


def cmd_scrape():
    rows = scraper.scrape()
    print(f"Scraped {len(rows)} site locations\n")
    for r in sorted(rows, key=lambda r: (r["state"] or "", r["city"] or "")):
        only_home = all("/communities" not in p for p in r["found_on"])
        flag = "  [linked only from homepage]" if only_home else ""
        print(f"{r['name']:<48} {r['street']}, {r['city']}, {r['state']} {r['zip']}")
        print(f"{'':<48} {r['phone']} | admin: {r['administrator']} | {', '.join(r['care_offerings'])}{flag}")


def match(conn):
    """Read the CRM, compare with the stored site data, queue proposals. Used by the CLI and the app."""
    sites = load_sites(conn)
    if not sites:
        raise SystemExit("No site data yet. Run: python run.py scrape")
    crm = CRM(conn=conn)
    accounts, contacts = crm.accounts(), crm.contacts()
    found, summary = matcher.build_proposals(sites, accounts, contacts)
    counts = proposals.save(conn, found)
    return found, summary, counts, (len(sites), len(accounts), len(contacts))


def cmd_match():
    found, summary, (new, skipped, pending), sizes = match(connect())
    print("{} site locations, {} CRM accounts, {} contacts\n".format(*sizes))
    by_type = defaultdict(list)
    for p in found:
        by_type[p["type"]].append(p)

    print(f"Clean matches (no change needed): {len(summary['clean'])}")
    for label in summary["clean"]:
        print(f"   {label}")
    print(f"Duplicate survivors that already match the site: {len(summary['survivors'])}")
    for label in summary["survivors"]:
        print(f"   {label}")
    for t in TYPE_ORDER:
        print(f"\n{t.upper()} ({len(by_type[t])})")
        for p in by_type[t]:
            print(f"   {p['title']}")
            if t == "field_update":
                for k, v in p["proposed"].items():
                    print(f"      {k}: {p['crm'].get(k)!r} -> {v!r}")

    print(f"\nQueue: {new} new, {pending} already pending, {skipped} skipped (already decided)")


def cmd_sync():
    cmd_scrape()
    print()
    cmd_match()


def cmd_serve():
    from webapp import app
    app.run(debug=False, port=5000)


COMMANDS = {"scrape": cmd_scrape, "match": cmd_match, "sync": cmd_sync, "serve": cmd_serve}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        print(f"usage: python run.py [{'|'.join(COMMANDS)}]")
        sys.exit(1)
    COMMANDS[sys.argv[1]]()
