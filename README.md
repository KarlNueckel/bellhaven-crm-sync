# Bellhaven site-to-CRM sync

Keeps the CRM in line with the communities listed on the Bellhaven Senior Living website.
It scrapes the site, compares it with the CRM, and queues **proposals** in a small review app.
Nothing is written to the CRM until a person clicks **Approve**.

Stack: Python, Flask, SQLite, requests, BeautifulSoup.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then paste your token into CRM_TOKEN
```

`.env` is gitignored. The token is never committed.

## Run

| Command | What it does |
|---|---|
| `python run.py scrape` | Crawl the site into SQLite and print every location |
| `python run.py match`  | Pull the CRM (read-only), compare, queue proposals, print a summary |
| `python run.py sync`   | `scrape` + `match` (what the schedule runs) |
| `python run.py serve`  | Review app at http://127.0.0.1:5000 |
| `pytest -q`            | Tests for the normalizer, matcher, SOP, and idempotency |

See [WRITEUP.md](WRITEUP.md) for the decisions behind the results.

The review app lists pending proposals grouped by type. Each one shows the website and CRM data side by side,
the evidence, and the exact API calls that run on approval. **API log** shows every CRM request and response.

## Files

| File | Purpose |
|---|---|
| `scraper.py` | Crawls every internal link from `/` and `/communities`, parses detail pages |
| `normalize.py` | Street suffixes and directionals, `&`/`and`, Centre/Center, phone, zip, care mapping |
| `matcher.py` | Matches site to CRM, builds proposals with evidence |
| `sop.py` | `apply_parent_change_sop()`: the change-of-ownership rule |
| `proposals.py` | Fingerprints, idempotent queue, runs approved API calls |
| `crm.py` | API client. Logs every call to the `api_log` table |
| `webapp.py`, `templates/` | Review app |

## Matching approach

1. **Crawl, don't paginate.** The scraper follows every internal link, not just "Next". One community is
   linked only from the homepage.
2. **Normalize** both sides: `Road→RD`, `West→W`, `Northwest→NW`, `Pk→PIKE`, `Lane→LN`, `Boulevard→BLVD`,
   `&→AND`, `Centre→Center`. Phones go to 10 digits and zips to 5. Care labels are mapped:
   *Short-Term Rehabilitation & Nursing* → Skilled Nursing, *Memory Support* → Memory Care.
3. **Match each site location**, stopping at the first signal that finds an account:
   1. **address**: normalized street + zip
   2. **phone**: catches the PO Box and zip-typo records
   3. **administrator**: the site administrator is a CRM contact on an account in the same city
   
   **Name similarity is never used to match.** It is only shown as evidence, because same-name decoys
   exist in other cities (Amberly, Union Square at 240 Market St, Maplewood Senior Care Center).
4. **Decide what to propose:**
   - **No account found:** *create* under Bellhaven.
   - **Several accounts at one site:** pick a survivor. The order is correct parent, then phone/contact
     match, then revenue. The others are *marked duplicate* (`duplicate_of_account` = survivor,
     `status` = Inactive). If no account is under Bellhaven, it is **flagged for a human decision**
     (Kettering). The reviewer clicks **Keep** on one account, and the matching changes are queued.
   - **Account under the wrong parent:** run the **SOP** (`sop.apply_parent_change_sop`). If
     `lifetime_revenue > 0` AND `outstanding_ar > 0`, the old account is not touched. A new account is
     created under Bellhaven, and the old account's `chow_current_account` is set to the new id (*CHOW*).
     Otherwise it is *re-parented* directly. Any name or address fix rides along.
   - **Right parent but different name/street/zip:** *field update*.
   - **Under Bellhaven but not on the site:** *orphan*. If another parent has an account at the same
     address, it is treated as a sale and the SOP links to that existing account (Sandusky). Otherwise
     it is set to `Needs Review` with a note.
5. Accounts that already have `chow_current_account` or `duplicate_of_account` set are history and are
   not matched again. This stops an approved CHOW from showing up as a duplicate on the next run.

## Idempotency

Each proposal has a fingerprint: a hash of type + account + site + proposed values. Once a fingerprint is
approved or rejected, it is never proposed again. Pending proposals are refreshed, not duplicated.
Pending proposals that no longer apply are dropped. Running `match` twice gives `0 new` the second time.

## Schedule

GitHub Actions: `.github/workflows/daily-sync.yml` runs `python run.py sync` daily at 11:00 UTC.
Add the token under **Settings → Secrets and variables → Actions** as `CRM_TOKEN`. The SQLite DB is
carried between runs with the Actions cache, and the summary is uploaded as an artifact. The scheduled
run only reads the CRM and queues proposals. Approvals happen in the review app.

Cron alternative (on a server that also hosts the review app):

```cron
0 6 * * * cd /path/to/bellhaven-crm-sync && .venv/bin/python run.py sync >> logs/sync.log 2>&1
```

## Write payloads

The POST/PATCH bodies are not documented, so these are the shapes we send. Use the expand
"API calls on approve" in the app to see them for any proposal.

- Field update: `PATCH /accounts/{id}` `{"name": "..."}` (or `billing_street` / `billing_zip`)
- Re-parent: `PATCH /accounts/{id}` `{"parent_id": "<Bellhaven id>"}` (+ any field fixes)
- CHOW: `POST /accounts` `{name, parent_id, billing_*, care_type, phone, status:"Active"}`, then
  `PATCH /accounts/{old}` `{"chow_current_account": "<new id>"}`
- Duplicate: `PATCH /accounts/{id}` `{"duplicate_of_account": "<survivor>", "status": "Inactive"}`
- Orphan: `PATCH /accounts/{id}` `{"status": "Needs Review", "note": "..."}` or `{"chow_current_account": "<id>"}`

## How to test end to end

1. `pytest -q`: 24 tests pass, with no network needed.
2. `python run.py sync`: 35 site locations, 121 CRM accounts, 27 proposals queued.
3. `python run.py match` again: the last line says `0 new`.
4. `python run.py serve`, open http://127.0.0.1:5000:
   - Approve one safe item (e.g. the Sycamore Ridge name fix), then check the result on the card and the
     **API log** page.
   - Reject another item.
   - Click **Re-run sync**: neither item comes back (`skipped (already decided)`).

## Making a change on the spot

| Request | Where |
|---|---|
| New street abbreviation or spelling variant | add a pair to `SUFFIXES` / `DIRECTIONALS` / `NAME_WORDS` in `normalize.py` |
| New care label | `CARE_MAP` in `normalize.py` |
| Change the SOP rule (e.g. revenue OR AR) | `has_billing_history()` in `sop.py` |
| Change survivor priority | `rank()` inside `pick_survivor()` in `matcher.py` |
| Add/remove a match signal | `match_site()` in `matcher.py` |
| Compare another field (e.g. phone) | `field_differences()` in `matcher.py` |

After any change: `pytest -q`, then `python run.py match`.
