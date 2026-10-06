"""Thin CRM API client. Every request and response is logged to the api_log table."""
import json
from datetime import datetime, timezone

import requests

from config import API_BASE, CRM_TOKEN
from db import connect


class CRM:
    def __init__(self, token=CRM_TOKEN, conn=None):
        if not token:
            raise SystemExit("CRM_TOKEN is not set. Copy .env.example to .env and add your token.")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.conn = conn or connect()

    def _call(self, method, path, body=None, params=None):
        url = f"{API_BASE}{path}"
        resp = self.session.request(method, url, json=body, params=params, timeout=30)
        with self.conn:
            self.conn.execute(
                "INSERT INTO api_log (ts, method, url, request_body, status, response_body) VALUES (?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), method,
                 resp.url, json.dumps(body) if body is not None else None, resp.status_code, resp.text),
            )
        resp.raise_for_status()
        return resp.json()

    def list_all(self, path, **params):
        """Follow {data, page, page_size, total} pagination to the end."""
        rows, page = [], 1
        while True:
            out = self._call("GET", path, params={**params, "page": page, "page_size": 100})
            rows.extend(out["data"])
            if not out["data"] or len(rows) >= out["total"]:
                return rows
            page += 1

    def accounts(self):
        return self.list_all("/accounts")

    def contacts(self):
        return self.list_all("/contacts")

    def me(self):
        return self._call("GET", "/me")

    def get_account(self, account_id):
        return self._call("GET", f"/accounts/{account_id}")

    def create_account(self, fields):
        return self._call("POST", "/accounts", body=fields)

    def update_account(self, account_id, fields):
        return self._call("PATCH", f"/accounts/{account_id}", body=fields)
