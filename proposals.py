"""Store proposals idempotently and execute approved ones against the CRM.

A proposal's fingerprint is a hash of (type, account, site, proposed values).
Once a fingerprint is approved or rejected it is never proposed again.
"""
import hashlib
import json
from datetime import datetime, timezone

DECIDED = ("approved", "rejected")


def fingerprint(p):
    raw = json.dumps([p["type"], p["account_id"], p["site_slug"], p["proposed"]], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save(conn, proposals):
    """Insert new proposals; skip decided fingerprints; drop pending ones that no longer apply.

    Returns (new, skipped_decided, already_pending)."""
    current = {fingerprint(p): p for p in proposals}
    existing = {r["fingerprint"]: r["status"] for r in conn.execute("SELECT fingerprint, status FROM proposals")}
    new = skipped = pending = 0
    with conn:
        for fp, p in current.items():
            if fp in existing:
                if existing[fp] in DECIDED:
                    skipped += 1
                else:  # still pending: refresh evidence/snapshots, keep the same row
                    pending += 1
                    conn.execute("UPDATE proposals SET title = ?, payload = ? WHERE fingerprint = ?",
                                 (p["title"], json.dumps(p), fp))
                continue
            conn.execute(
                """INSERT INTO proposals (fingerprint, type, title, account_id, site_slug, payload, status, created_at)
                   VALUES (?,?,?,?,?,?, 'pending', ?)""",
                (fp, p["type"], p["title"], p["account_id"], p["site_slug"], json.dumps(p), now()),
            )
            new += 1
        stale = [fp for fp, s in existing.items() if s in ("pending", "failed") and fp not in current]
        conn.executemany("DELETE FROM proposals WHERE fingerprint = ?", [(fp,) for fp in stale])
    return new, skipped, pending


def execute(crm, payload):
    """Run a proposal's API actions in order. Returns a list of response bodies."""
    saved, results = {}, []
    for action in payload["actions"]:
        body = json.loads(json.dumps(action["body"]))  # copy
        for k, v in body.items():
            if isinstance(v, str) and v.startswith("{") and v.endswith("}") and v[1:-1] in saved:
                body[k] = saved[v[1:-1]]
        if action["method"] == "POST":
            out = crm.create_account(body)
        else:
            out = crm.update_account(action["path"].rsplit("/", 1)[1], body)
        if action.get("save_as"):
            record = out.get("data", out) if isinstance(out, dict) else {}
            saved[action["save_as"]] = record["account_id"]
        results.append(out)
    return results


def decide(conn, crm, proposal_id, approve):
    """Approve (write to the CRM) or reject one proposal."""
    row = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    if row is None or row["status"] in DECIDED:
        return row
    status, result = "rejected", None
    if approve:
        try:
            result = json.dumps(execute(crm, json.loads(row["payload"])))
            status = "approved"
        except Exception as e:  # keep the proposal retryable and show the error
            status, result = "failed", str(e)
    with conn:
        conn.execute("UPDATE proposals SET status = ?, result = ?, decided_at = ? WHERE id = ?",
                     (status, result, now(), proposal_id))
    return conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
