"""Match site locations to CRM accounts and turn the differences into proposals.

Match order for each site location (first signal that finds something wins):
    1. address  - normalized street + 5-digit zip
    2. phone    - normalized 10-digit phone
    3. admin    - site administrator is a CRM contact on an account in the same city
Name similarity is recorded as evidence but never creates a match on its own.
"""
import normalize as n
from sop import apply_parent_change_sop

OPERATOR_NAME = "Bellhaven Senior Living"


# ---------------------------------------------------------------- helpers

def find_operator_parent(accounts):
    for a in accounts:
        if not a["parent_id"] and n.name(a["name"]).startswith(n.name(OPERATOR_NAME)):
            return a
    raise SystemExit(f"No top-level '{OPERATOR_NAME}' account in the CRM")


def is_parent_account(a, parent_ids):
    return a["account_id"] in parent_ids or "(parent account)" in a["name"].lower()


def is_retired(a):
    """Accounts already linked forward by a CHOW or marked duplicate are history, not candidates."""
    return bool(a.get("chow_current_account") or a.get("duplicate_of_account"))


def site_account_fields(site, parent_id):
    """The body we would POST to create an account for a site location."""
    return {
        "name": site["name"],
        "parent_id": parent_id,
        "billing_street": site["street"],
        "billing_city": site["city"],
        "billing_state": site["state"],
        "billing_zip": site["zip"],
        "care_type": n.care(site["care_offerings"][0]) if site["care_offerings"] else "",
        "phone": site["phone"],
        "status": "Active",
    }


def field_differences(site, account):
    """Name/address/zip fields where the CRM disagrees with the site (after normalizing)."""
    diffs = {}
    if n.name(site["name"]) != n.name(account["name"]):
        diffs["name"] = site["name"]
    if n.is_po_box(account["billing_street"]) or n.street(site["street"]) != n.street(account["billing_street"]):
        diffs["billing_street"] = site["street"]
    if n.zip5(site["zip"]) != n.zip5(account["billing_zip"]):
        diffs["billing_zip"] = site["zip"]
    if site["city"].lower() != (account["billing_city"] or "").lower():
        diffs["billing_city"] = site["city"]
    if site["state"] != account["billing_state"]:
        diffs["billing_state"] = site["state"]
    return diffs


def evidence_for(site, account, contacts_by_account):
    """Every signal we can see between a site location and one account."""
    admins = {n.person(c["name"]) for c in contacts_by_account.get(account["account_id"], [])}
    return {
        "address": n.address_key(site["street"], site["zip"]) == n.address_key(account["billing_street"], account["billing_zip"]),
        "street_only": n.street(site["street"]) == n.street(account["billing_street"]),
        "phone": bool(n.phone(site["phone"])) and n.phone(site["phone"]) == n.phone(account["phone"]),
        "admin_contact": n.person(site["administrator"]) in admins,
        "city": site["city"].lower() == (account["billing_city"] or "").lower(),
        "name_similarity": n.name_similarity(site["name"], account["name"]),
    }


def describe(ev):
    parts = []
    for key, label in [("address", "address+zip match"), ("phone", "phone match"),
                       ("admin_contact", "site administrator is a contact here"), ("city", "same city")]:
        parts.append(f"{label}: {'YES' if ev[key] else 'no'}")
    parts.append(f"name similarity {ev['name_similarity']} (evidence only)")
    return parts


def account_snapshot(a):
    keys = ["account_id", "name", "parent_name", "billing_street", "billing_city", "billing_state",
            "billing_zip", "phone", "care_type", "status", "lifetime_revenue", "outstanding_ar"]
    return {k: a.get(k) for k in keys}


def site_snapshot(s):
    keys = ["name", "street", "city", "state", "zip", "phone", "administrator", "care_offerings", "url"]
    return {k: s.get(k) for k in keys}


# ---------------------------------------------------------------- matching

def match_site(site, candidates, contacts_by_account):
    """Return (signal, [matched accounts]) using address -> phone -> admin. Never name alone."""
    key = n.address_key(site["street"], site["zip"])
    hits = [a for a in candidates if n.address_key(a["billing_street"], a["billing_zip"]) == key]
    if hits:
        return "address", hits

    phone = n.phone(site["phone"])
    hits = [a for a in candidates if phone and n.phone(a["phone"]) == phone]
    if hits:
        return "phone", hits

    admin = n.person(site["administrator"])
    hits = [a for a in candidates
            if a["billing_city"].lower() == site["city"].lower()
            and admin in {n.person(c["name"]) for c in contacts_by_account.get(a["account_id"], [])}]
    if hits:
        return "admin", hits
    return None, []


def pick_survivor(site, group, operator_id, contacts_by_account):
    """Correct parent first, then phone/contact match, then revenue history. None if no account is under the operator."""
    under_operator = [a for a in group if a["parent_id"] == operator_id]
    if not under_operator:
        return None

    def rank(a):
        ev = evidence_for(site, a, contacts_by_account)
        return (ev["phone"] or ev["admin_contact"], ev["phone"] + ev["admin_contact"], a["lifetime_revenue"] or 0)

    return max(under_operator, key=rank)


# ---------------------------------------------------------------- proposals

def build_proposals(sites, accounts, contacts):
    """Compare every site location with the CRM. Returns (proposals, summary)."""
    operator = find_operator_parent(accounts)
    op_id = operator["account_id"]
    parent_ids = {a["parent_id"] for a in accounts if a["parent_id"]}
    by_id = {a["account_id"]: a for a in accounts}
    candidates = [a for a in accounts if not is_parent_account(a, parent_ids) and not is_retired(a)]
    contacts_by_account = {}
    for c in contacts:
        if c.get("is_active", True):
            contacts_by_account.setdefault(c["account_id"], []).append(c)

    proposals, summary, matched_ids = [], {"clean": [], "survivors": [], "flagged": []}, set()

    def propose(ptype, site, account, proposed, actions, evidence, title, note=""):
        proposals.append({
            "type": ptype, "title": title, "account_id": account["account_id"] if account else None,
            "site_slug": site["slug"] if site else None, "proposed": proposed, "actions": actions,
            "evidence": evidence, "note": note,
            "site": site_snapshot(site) if site else None,
            "crm": account_snapshot(account) if account else None,
        })

    for site in sites:
        signal, group = match_site(site, candidates, contacts_by_account)
        matched_ids.update(a["account_id"] for a in group)
        label = f"{site['name']} ({site['city']}, {site['state']})"

        # No account anywhere -> create under the operator.
        if not group:
            body = site_account_fields(site, op_id)
            near = sorted(candidates, key=lambda a: -n.name_similarity(site["name"], a["name"]))[:2]
            ev = ["no address, phone, or administrator match in the CRM"]
            ev += [f"closest name '{a['name']}' in {a['billing_city']}, {a['billing_state']} "
                   f"(similarity {n.name_similarity(site['name'], a['name'])}) ignored: name alone never matches"
                   for a in near]
            propose("create", site, None, body, [{"method": "POST", "path": "/accounts", "body": body}],
                    ev, f"Create {label}")
            continue

        # Several accounts at one site -> pick a survivor, mark the rest duplicates.
        account = group[0]
        if len(group) > 1:
            survivor = pick_survivor(site, group, op_id, contacts_by_account)
            if survivor is None:
                ev = [f"{a['name']} [{a['account_id']}] parent={a['parent_name'] or 'none'}: "
                      + "; ".join(describe(evidence_for(site, a, contacts_by_account))) for a in group]
                propose("decision", site, group[0], {"candidates": [a["account_id"] for a in group]}, [],
                        ev, f"Decide: {len(group)} accounts at {label}, none under {OPERATOR_NAME}",
                        note="No survivor can be chosen by rule. Needs a human decision.")
                summary["flagged"].append(label)
                continue
            for loser in group:
                if loser is survivor:
                    continue
                body = {"duplicate_of_account": survivor["account_id"], "status": "Inactive"}
                sv = evidence_for(site, survivor, contacts_by_account)
                ev = [f"same {signal} as survivor {survivor['name']} [{survivor['account_id']}]",
                      f"survivor chosen by: parent={survivor['parent_name']}, phone match={sv['phone']}, "
                      f"admin contact={sv['admin_contact']}, revenue={survivor['lifetime_revenue']}",
                      "this account:"]
                ev += describe(evidence_for(site, loser, contacts_by_account))
                propose("duplicate", site, loser, body,
                        [{"method": "PATCH", "path": f"/accounts/{loser['account_id']}", "body": body}],
                        ev, f"Mark duplicate: {loser['name']} -> {survivor['name']} ({site['city']})")
            account = survivor

        ev = [f"matched on {signal}"] + describe(evidence_for(site, account, contacts_by_account))
        diffs = field_differences(site, account)

        # Wrong parent -> SOP decides re-parent vs CHOW.
        if account["parent_id"] != op_id:
            plan = apply_parent_change_sop(account, op_id, new_account_fields=site_account_fields(site, op_id))
            ev.append(f"SOP: {plan['reason']}")
            if plan["kind"] == "reparent":
                body = {"parent_id": op_id, **{k: v for k, v in diffs.items()}}
                plan["actions"][0]["body"] = body
                propose("reparent", site, account, body, plan["actions"], ev,
                        f"Re-parent {account['name']} from {account['parent_name'] or 'no parent'} to {OPERATOR_NAME}")
            else:
                propose("chow", site, account, plan["actions"][0]["body"], plan["actions"], ev,
                        f"CHOW: {account['name']} ({account['parent_name']}) -> new account under {OPERATOR_NAME}")
            continue

        if len(group) > 1 and not diffs:
            summary["survivors"].append(label)
        if diffs:
            propose("field_update", site, account, diffs,
                    [{"method": "PATCH", "path": f"/accounts/{account['account_id']}", "body": diffs}],
                    ev, f"Update {', '.join(diffs)} on {account['name']} ({site['city']})")
        else:
            if len(group) == 1:
                summary["clean"].append(label)

    # Orphans: under the operator in the CRM, but on no site page.
    for a in candidates:
        if a["parent_id"] != op_id or a["account_id"] in matched_ids:
            continue
        key = n.address_key(a["billing_street"], a["billing_zip"])
        new_owner = next((o for o in candidates if o["account_id"] != a["account_id"]
                          and o["parent_id"] and o["parent_id"] != op_id
                          and n.address_key(o["billing_street"], o["billing_zip"]) == key), None)
        ev = ["under the operator in the CRM but not listed on the website"]
        if new_owner:
            plan = apply_parent_change_sop(a, new_owner["parent_id"], existing_account_id=new_owner["account_id"])
            ev += [f"{new_owner['name']} [{new_owner['account_id']}] under {new_owner['parent_name']} "
                   "is at the same address: treated as a sale", f"SOP: {plan['reason']}"]
            propose("orphan", None, a, plan["actions"][0]["body"], plan["actions"], ev,
                    f"Orphan sold: {a['name']} -> {new_owner['parent_name']}", note=plan["reason"])
        else:
            body = {"status": "Needs Review",
                    "note": f"Not listed on {OPERATOR_NAME} website; no other owner found at this address."}
            ev.append("no other account at this address: no evidence of a new owner")
            propose("orphan", None, a, body,
                    [{"method": "PATCH", "path": f"/accounts/{a['account_id']}", "body": body}],
                    ev, f"Orphan: {a['name']} ({a['billing_city']}) -> Needs Review")

    return proposals, summary
