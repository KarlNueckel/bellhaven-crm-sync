"""Idempotency and write-path tests with an in-memory DB and a fake CRM."""
import proposals
from db import connect


def proposal(name="New Name", account="A1"):
    return {"type": "field_update", "title": "t", "account_id": account, "site_slug": "s",
            "proposed": {"name": name}, "evidence": [], "note": "", "site": None, "crm": None,
            "actions": [{"method": "PATCH", "path": f"/accounts/{account}", "body": {"name": name}}]}


class FakeCRM:
    def __init__(self):
        self.calls = []

    def create_account(self, body):
        self.calls.append(("POST", body))
        return {"account_id": "NEW1", **body}

    def update_account(self, account_id, body):
        self.calls.append(("PATCH", account_id, body))
        return {"account_id": account_id, **body}


def test_second_run_adds_nothing_for_decided_items():
    conn = connect(":memory:")
    assert proposals.save(conn, [proposal()]) == (1, 0, 0)
    pid = conn.execute("SELECT id FROM proposals").fetchone()[0]
    proposals.decide(conn, FakeCRM(), pid, approve=False)
    assert proposals.save(conn, [proposal()]) == (0, 1, 0)


def test_pending_items_are_not_duplicated_and_changed_values_are_new():
    conn = connect(":memory:")
    proposals.save(conn, [proposal()])
    assert proposals.save(conn, [proposal()]) == (0, 0, 1)
    assert proposals.save(conn, [proposal(name="Other")]) == (1, 0, 0)
    # the stale pending one was dropped
    assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 1


def test_only_approval_writes():
    conn, crm = connect(":memory:"), FakeCRM()
    proposals.save(conn, [proposal(account="A1"), proposal(account="A2")])
    (a,), (b,) = conn.execute("SELECT id FROM proposals ORDER BY id").fetchall()
    proposals.decide(conn, crm, b, approve=False)
    assert crm.calls == []
    proposals.decide(conn, crm, a, approve=True)
    assert crm.calls == [("PATCH", "A1", {"name": "New Name"})]


def test_chow_links_old_account_to_created_id():
    conn, crm = connect(":memory:"), FakeCRM()
    p = proposal()
    p.update(type="chow", actions=[
        {"method": "POST", "path": "/accounts", "body": {"name": "X"}, "save_as": "new_id"},
        {"method": "PATCH", "path": "/accounts/OLD", "body": {"chow_current_account": "{new_id}"}},
    ])
    proposals.save(conn, [p])
    proposals.decide(conn, crm, 1, approve=True)
    assert crm.calls[1] == ("PATCH", "OLD", {"chow_current_account": "NEW1"})
