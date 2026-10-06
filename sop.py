"""The change-of-ownership SOP, kept in one function so it is easy to find and test."""


def has_billing_history(account):
    return (account.get("lifetime_revenue") or 0) > 0 and (account.get("outstanding_ar") or 0) > 0


def apply_parent_change_sop(account, new_parent_id, new_account_fields=None, existing_account_id=None):
    """Decide how an account moves to a different parent.

    SOP: if lifetime_revenue > 0 AND outstanding_ar > 0, the account is NOT touched
    (other than the link). Instead the account under the correct parent is created
    (or, if one already exists, reused) and the OLD account's chow_current_account
    is set to that id. Otherwise, re-parent the account directly.

    Returns {"kind": "chow" | "reparent", "reason": str, "actions": [api calls]}.
    An action is {"method", "path", "body"}; a POST may carry "save_as" and later
    bodies refer to the saved id as "{new_id}".
    """
    old_id = account["account_id"]
    if has_billing_history(account):
        reason = (f"revenue {account['lifetime_revenue']} and AR {account['outstanding_ar']} > 0: "
                  "old account left untouched, linked via chow_current_account")
        if existing_account_id:
            return {"kind": "chow", "reason": reason, "actions": [
                {"method": "PATCH", "path": f"/accounts/{old_id}",
                 "body": {"chow_current_account": existing_account_id}},
            ]}
        return {"kind": "chow", "reason": reason, "actions": [
            {"method": "POST", "path": "/accounts",
             "body": {**(new_account_fields or {}), "parent_id": new_parent_id}, "save_as": "new_id"},
            {"method": "PATCH", "path": f"/accounts/{old_id}", "body": {"chow_current_account": "{new_id}"}},
        ]}

    reason = "no revenue+AR history: re-parent directly"
    return {"kind": "reparent", "reason": reason, "actions": [
        {"method": "PATCH", "path": f"/accounts/{old_id}", "body": {"parent_id": new_parent_id}},
    ]}
