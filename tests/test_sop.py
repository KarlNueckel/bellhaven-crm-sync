from sop import apply_parent_change_sop

NEW_PARENT = "P_BELL"


def acct(rev, ar):
    return {"account_id": "A1", "lifetime_revenue": rev, "outstanding_ar": ar}


def test_revenue_and_ar_creates_new_account_and_links_old():
    plan = apply_parent_change_sop(acct(1000, 50), NEW_PARENT, new_account_fields={"name": "X"})
    assert plan["kind"] == "chow"
    create, link = plan["actions"]
    assert create["method"] == "POST" and create["body"]["parent_id"] == NEW_PARENT
    assert link == {"method": "PATCH", "path": "/accounts/A1", "body": {"chow_current_account": "{new_id}"}}
    # The old account's parent is never changed.
    assert all("parent_id" not in a["body"] for a in plan["actions"] if a["method"] == "PATCH")


def test_revenue_and_ar_links_existing_account_instead_of_creating():
    plan = apply_parent_change_sop(acct(1000, 50), NEW_PARENT, existing_account_id="B9")
    assert plan["kind"] == "chow"
    assert plan["actions"] == [{"method": "PATCH", "path": "/accounts/A1", "body": {"chow_current_account": "B9"}}]


def test_revenue_only_reparents_directly():
    plan = apply_parent_change_sop(acct(1000, 0), NEW_PARENT)
    assert plan["kind"] == "reparent"
    assert plan["actions"][0]["body"] == {"parent_id": NEW_PARENT}


def test_ar_only_or_nothing_reparents_directly():
    assert apply_parent_change_sop(acct(0, 50), NEW_PARENT)["kind"] == "reparent"
    assert apply_parent_change_sop(acct(0, 0), NEW_PARENT)["kind"] == "reparent"
    assert apply_parent_change_sop(acct(None, None), NEW_PARENT)["kind"] == "reparent"
