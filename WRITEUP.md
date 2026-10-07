# Writeup

**Time spent:** about 3 hours

## Matching approach

**Scraping.** The scraper crawls every internal link starting from `/` and `/communities`, rather than only
following the directory's "Next" links. That matters: the directory says 34 communities, but the homepage
links a 35th (Bellhaven Meadows of Findlay) that isn't in the directory.

**Normalizing.** Both sides are normalized before any comparison:
- street suffixes and directionals (`Road→RD`, `West→W`, `Northwest→NW`, `Pike/Pk`, `Lane→LN`, `Blvd`)
- `&`/`and` and `Centre`/`Center`
- phones to 10 digits, zips to 5
- care labels mapped to CRM values (*Short-Term Rehabilitation & Nursing* → Skilled Nursing,
  *Memory Support* → Memory Care)

**Matching.** Each website location is matched with a strict order of signals:
1. **Address:** normalized street + zip. This decides most locations.
2. **Phone.** This catches records whose address is wrong in the CRM: Ashtabula (a PO Box) and
   Portsmouth (a zip typo).
3. **Administrator:** the site's administrator is a CRM contact on an account in the same city.

**Name similarity never creates a match.** It is only shown to the reviewer as evidence. The CRM has
deliberate same-name decoys: Amberly accounts in other cities, *Union Square Senior Living* at a different
New Albany address, and *Maplewood Senior Care Center* across town from Bellhaven of Maplewood. A
name-based matcher would link all of them wrongly.

**Classification.** Each result becomes one of:

| Outcome | Rule | Found |
|---|---|---|
| Clean match | correct parent, fields agree | 12 (+4 duplicate survivors) |
| Field update | correct parent, name/street/zip differ | 9 (7 outdated names, PO Box, zip typo) |
| Re-parent | wrong parent, SOP allows a direct move | Lima, Zanesville, Findlay |
| CHOW | wrong parent, revenue AND AR > 0 | Marietta, Tiffin |
| Create | no account anywhere | Batavia, Carlisle PA, Union Square, Amberly Manor (Hudson) |
| Duplicate | several accounts at one address | Erie, Port Clinton, Monroe (2 copies), Owosso |
| Orphan | under Bellhaven, not on the website | Sandusky, Alliance, Coldwater |
| Needs decision | several accounts, none under Bellhaven | Kettering |

## Choices I made (and why)

- **SOP.** The SOP lives in one function, `sop.apply_parent_change_sop()`. Marietta and Tiffin have both
  revenue and AR, so their accounts are left exactly as they are. A new account is created under
  Bellhaven, and the old account's `chow_current_account` points to it. Lima and Findlay have revenue
  but no AR, and Zanesville has neither, so they are re-parented directly. Any outdated name is fixed in
  the same change.
- **Duplicates.** The survivor is picked by: correct parent first, then a phone or contact match, then
  revenue history. Losers get `duplicate_of_account` = survivor and `status` = Inactive. Losers under
  another parent (e.g. *Harborview Shores of Erie*) are marked duplicate, not re-parented. They are copies
  of a facility Bellhaven already has.
- **Owosso.** Both copies are under Bellhaven. The survivor is the one whose phone matches the website.
- **Kettering.** Three accounts share the address: one has no parent, one is under Cedar Trail, one under
  Harborview. None has revenue, a matching phone, or a matching contact, so no rule can pick a survivor
  and the tool flags it for a human. I chose _[fill in: e.g. "Kettering Care Centre (Harborview), because
  the website's About page says Harborview's communities joined Bellhaven in 2025"]_. The app then
  re-parented it, renamed it, and marked the other two as duplicates.
- **Orphans.** Sandusky has a Millstone Health Partners account at the same address, so I treated it as
  a sale. It has revenue and AR, so per the SOP it isn't modified. Its `chow_current_account` is linked to
  the existing Millstone account rather than creating another one. Alliance and Coldwater show no sign of
  a new owner, so they are set to `Needs Review` with a note explaining why. Nothing is removed from
  Bellhaven without evidence.
- **Retired accounts are skipped.** Accounts that already have `chow_current_account` or
  `duplicate_of_account` set are left out of matching. Otherwise an approved CHOW (old and new account at
  one address) would show up as a "duplicate" the next day.
- **Not changed on purpose.** Many CRM phone numbers differ from the website. I show phone as evidence but
  don't overwrite it, because the brief scoped fixes to name, address, and parent. It would be a one-line
  addition in `field_differences()`.

## Safety and re-runs

- Nothing writes without approval. The scheduled job only reads the CRM and queues proposals. Every API
  request and response is logged and visible on the app's **API log** page.
- Every proposal has a fingerprint (type + account + proposed values). Approved or rejected fingerprints
  are never proposed again. A second run reports `0 new`. A rejection can be undone with **Reopen**.
- Daily schedule: a GitHub Actions workflow (`.github/workflows/daily-sync.yml`), with a crontab line in
  the README as an alternative.
- 26 tests cover the normalizer, the matcher (including decoys, PO Box/zip-typo recovery and the Kettering
  flag), the SOP, and idempotency.

## How I used AI tools

I used Claude Code as the builder and directed it in stages: scraper, then matcher with a printed
summary, then review app, then writes. I stopped after each stage to check the output.
- **Spec first.** I wrote a detailed spec up front, including the outcomes I expected to find (counts,
  which towns re-parent vs. CHOW, the decoys). I told it not to hardcode those. I then used them as an
  answer key to check that the logic found them on its own.
- **I kept writes behind me.** I told it to describe the POST/PATCH bodies before any write and let me
  approve a single test call first. I approved one name fix and confirmed the change in the CRM before
  approving the rest.
- **What I checked or corrected:**
  - that the Findlay community linked only from the homepage was found;
  - that name similarity alone never matched;
  - that the second run produced zero new proposals.
- **What I caught along the way:**
  - the brief requires the CRM to be corrected, not just reviewed, which meant adding a way to undo a
    rejection;
  - the Kettering case needed a "pick the survivor" action in the app rather than a dead-end flag.

## What I'd build next

- **Contacts:** create/update the site administrator as a CRM contact on new and matched accounts.
- **Phone and care type sync**, behind the same review step.
- **Shared database for the scheduled job** (e.g. Postgres) so the daily run and the review app see the
  same decisions. Today, the Actions run keeps its own SQLite copy.
- **Change alerts:** a daily digest of new proposals sent to the reviewer, plus a "changed since
  yesterday" view on the website side.
- **Ownership signals beyond the operator's own site:** state licensing databases and CMS ownership data
  to confirm sales and catch acquisitions before the website changes.
