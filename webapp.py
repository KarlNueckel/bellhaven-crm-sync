"""Review app: approve or reject proposals. Only an approval writes to the CRM."""
import json

from flask import Flask, flash, g, redirect, render_template, request, url_for

import proposals
import run
import scraper
from crm import CRM
from db import connect

app = Flask(__name__)
app.secret_key = "local-review-app"  # only used for flash messages

TYPES = [
    ("field_update", "Field updates"), ("reparent", "Re-parents"), ("chow", "Change of ownership (CHOW)"),
    ("create", "Create account"), ("duplicate", "Mark duplicate"), ("orphan", "Orphans"),
    ("decision", "Needs your decision"),
]


def db():
    if "conn" not in g:
        g.conn = connect()
    return g.conn


@app.teardown_appcontext
def close(_):
    if "conn" in g:
        g.conn.close()


@app.route("/")
def queue():
    show = request.args.get("show", "pending")
    statuses = ("pending", "failed") if show == "pending" else ("approved", "rejected")
    rows = db().execute(
        f"SELECT * FROM proposals WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY id", statuses
    ).fetchall()
    groups = []
    for key, label in TYPES:
        items = [{**dict(r), "p": json.loads(r["payload"])} for r in rows if r["type"] == key]
        if items:
            groups.append((label, items))
    counts = dict(db().execute("SELECT status, COUNT(*) FROM proposals GROUP BY status").fetchall())
    return render_template("queue.html", groups=groups, show=show, counts=counts)


@app.post("/proposals/<int:pid>/<action>")
def decide(pid, action):
    proposals.decide(db(), CRM(conn=db()), pid, approve=(action == "approve"))
    return redirect(url_for("queue", show=request.args.get("show", "pending")) + f"#p{pid}")


@app.post("/proposals/<int:pid>/reopen")
def reopen(pid):
    proposals.reopen(db(), pid)
    return redirect(url_for("queue") + f"#p{pid}")


@app.post("/proposals/<int:pid>/choose/<account_id>")
def choose(pid, account_id):
    """Kettering-style flag: the reviewer picks the survivor, then the matcher queues the follow-up changes."""
    proposals.choose_survivor(db(), pid, account_id)
    _, _, (new, _, _), _ = run.match(db())
    flash(f"Survivor recorded. {new} follow-up proposals queued for approval.")
    return redirect(url_for("queue"))


@app.route("/log")
def log():
    rows = db().execute("SELECT * FROM api_log ORDER BY id DESC LIMIT 300").fetchall()
    return render_template("log.html", rows=rows)


@app.post("/sync")
def sync():
    """Same as `python run.py sync`: re-scrape, re-read the CRM, queue anything new."""
    scraper.scrape()
    _, _, (new, skipped, pending), _ = run.match(db())
    flash(f"Sync done: {new} new, {pending} still pending, {skipped} skipped (already decided).")
    return redirect(url_for("queue"))
