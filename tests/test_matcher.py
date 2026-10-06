"""Matcher tests on a small synthetic CRM (no network)."""
import matcher

BELL, OTHER, OTHER2 = "P_BELL", "P_OTHER", "P_OTHER2"


def account(aid, name, street, city, zip_, parent="", phone="", rev=0, ar=0, **extra):
    parent_names = {BELL: "Bellhaven Senior Living (Parent Account)", OTHER: "Other Group (Parent Account)",
                    OTHER2: "Second Group (Parent Account)"}
    return {"account_id": aid, "name": name, "parent_id": parent, "parent_name": parent_names.get(parent, ""),
            "billing_street": street, "billing_city": city, "billing_state": "OH", "billing_zip": zip_,
            "care_type": "Assisted Living", "status": "Active", "phone": phone, "lifetime_revenue": rev,
            "outstanding_ar": ar, "chow_current_account": "", "duplicate_of_account": "", "note": "", **extra}


PARENTS = [
    account(BELL, "Bellhaven Senior Living (Parent Account)", "", "", ""),
    account(OTHER, "Other Group (Parent Account)", "", "", ""),
    account(OTHER2, "Second Group (Parent Account)", "", "", ""),
]


def site(slug, name, street, city, zip_, phone="(000) 000-0000", admin="Nobody Here", care=("Assisted Living",)):
    return {"slug": slug, "url": f"https://x/communities/{slug}", "name": name, "street": street, "city": city,
            "state": "OH", "zip": zip_, "phone": phone, "administrator": admin, "care_offerings": list(care)}


def run(sites, accounts, contacts=()):
    props, summary = matcher.build_proposals(sites, PARENTS + accounts, list(contacts))
    return props, summary


def by_type(props, t):
    return [p for p in props if p["type"] == t]


def test_normalized_address_match_is_clean():
    props, summary = run([site("a", "Bellhaven of A", "12 North Main Street", "Aville", "11111")],
                         [account("1", "Bellhaven of A", "12 N Main St", "Aville", "11111", BELL)])
    assert props == [] and summary["clean"] == ["Bellhaven of A (Aville, OH)"]


def test_same_name_decoy_in_other_city_never_matches():
    props, _ = run([site("a", "Amberly Manor", "4390 Darrow Rd", "Hudson", "44236")],
                   [account("1", "Amberly Manor", "918 S Nevada Ave", "Colorado Springs", "80903", OTHER)])
    assert [p["type"] for p in props] == ["create"]
    assert props[0]["proposed"]["parent_id"] == BELL


def test_phone_rescues_po_box_and_zip_typo():
    props, _ = run(
        [site("a", "Bellhaven of A", "3156 W Prospect Rd", "Aville", "44004", phone="(260) 440-4975"),
         site("b", "Bellhaven of B", "2222 Gallia St", "Bville", "45662", phone="(330) 431-2495")],
        [account("1", "Bellhaven of A", "PO Box 517", "Aville", "44004", BELL, phone="260-440-4975"),
         account("2", "Bellhaven of B", "2222 Gallia St", "Bville", "45626", BELL, phone="(330) 431-2495")])
    updates = {p["account_id"]: p["proposed"] for p in by_type(props, "field_update")}
    assert updates == {"1": {"billing_street": "3156 W Prospect Rd"}, "2": {"billing_zip": "45662"}}


def test_admin_contact_match_requires_same_city():
    s = site("a", "Bellhaven of A", "1 New St", "Aville", "11111", admin="Pat Lee")
    contacts = [{"account_id": "1", "name": "Pat Lee", "is_active": True}]
    props, _ = run([s], [account("1", "Old Name", "9 Old St", "Aville", "11111", BELL)], contacts)
    assert by_type(props, "field_update")[0]["account_id"] == "1"
    props, _ = run([s], [account("1", "Old Name", "9 Old St", "Elsewhere", "22222", BELL)], contacts)
    assert [p["type"] for p in props] == ["create", "orphan"]


def test_outdated_name_is_a_field_update():
    props, _ = run([site("a", "Bellhaven of Chesterton", "1250 NW Franklin Street", "Chesterton", "46304")],
                   [account("1", "Chesterton Senior Commons", "1250 Northwest Franklin St", "Chesterton", "46304", BELL)])
    assert by_type(props, "field_update")[0]["proposed"] == {"name": "Bellhaven of Chesterton"}


def test_wrong_parent_uses_sop():
    props, _ = run(
        [site("a", "Bellhaven of A", "1 A St", "Aville", "11111"),
         site("b", "Bellhaven of B", "2 B St", "Bville", "22222")],
        [account("1", "Bellhaven of A", "1 A St", "Aville", "11111", OTHER, rev=500, ar=0),
         account("2", "Bellhaven of B", "2 B St", "Bville", "22222", OTHER, rev=500, ar=20)])
    assert by_type(props, "reparent")[0]["account_id"] == "1"
    chow = by_type(props, "chow")[0]
    assert chow["account_id"] == "2" and chow["actions"][0]["method"] == "POST"


def test_duplicates_pick_survivor_under_correct_parent_then_phone():
    s = site("a", "Bellhaven of A", "1 A St", "Aville", "11111", phone="(111) 111-1111")
    props, _ = run([s], [
        account("1", "Bellhaven of A", "1 A Street", "Aville", "11111", BELL),
        account("2", "Bellhaven of A", "1 A St", "Aville", "11111", BELL, phone="111-111-1111"),
        account("3", "Other A", "1 A St", "Aville", "11111", OTHER, rev=900),
    ])
    dups = by_type(props, "duplicate")
    assert sorted(p["account_id"] for p in dups) == ["1", "3"]
    assert all(p["proposed"] == {"duplicate_of_account": "2", "status": "Inactive"} for p in dups)


def test_shared_address_with_no_operator_account_is_flagged():
    props, summary = run([site("a", "Bellhaven of K", "3313 Wilmington Pike", "Kettering", "45429")], [
        account("1", "K One", "3313 Wilmington Pike", "Kettering", "45429", ""),
        account("2", "K Two", "3313 Wilmington Pk", "Kettering", "45429", OTHER),
        account("3", "K Three", "3313 Wilmington Pike", "Kettering", "45429", OTHER2),
    ])
    assert [p["type"] for p in props] == ["decision"] and props[0]["actions"] == []


def test_orphan_sold_links_existing_account_and_orphan_without_owner_needs_review():
    props, _ = run([], [
        account("1", "Bellhaven of S", "2715 Columbus Ave", "Sandusky", "44870", BELL, rev=130000, ar=5200),
        account("2", "Millstone of S", "2715 Columbus Ave", "Sandusky", "44870", OTHER),
        account("3", "Bellhaven of C", "90 N Michigan Ave", "Coldwater", "49036", BELL),
    ])
    orphans = {p["account_id"]: p["proposed"] for p in by_type(props, "orphan")}
    assert orphans["1"] == {"chow_current_account": "2"}
    assert orphans["3"]["status"] == "Needs Review"


def test_retired_accounts_are_ignored():
    """After a CHOW is approved, old + new share an address; that must not look like a duplicate."""
    props, summary = run([site("a", "Bellhaven of A", "1 A St", "Aville", "11111")], [
        account("old", "Bellhaven of A", "1 A St", "Aville", "11111", OTHER, rev=9, ar=9, chow_current_account="new"),
        account("new", "Bellhaven of A", "1 A St", "Aville", "11111", BELL),
    ])
    assert props == [] and len(summary["clean"]) == 1
