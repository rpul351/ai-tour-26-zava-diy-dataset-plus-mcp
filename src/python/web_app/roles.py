"""Which role and store a signed-in person has, read from the agent's access list.

The role is never taken from the browser. The login page lets a person pick Store Manager or Super Manager, and the code
must belong to someone with that role on the access list. The agent service makes the same decision from the same file.
"""

import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / "workshop"))

import json  # noqa: E402

from access import GLOBAL_RLS_ID, STORE_RLS_IDS, normalise  # noqa: E402

ACCESS_LIST_FILE = Path(os.getenv("ACCESS_LIST_FILE") or Path(__file__).parent.parent / "workshop" / "access_list.json")

ROLE_LABELS = {"super_manager": "Super Manager", "store_manager": "Store Manager"}
_cache_key: tuple[str, float] | None = None
_cache_users: dict = {}


def _users() -> dict:
    """The access list entries, reread when the file changes. Missing or broken means nobody has a role."""
    global _cache_key, _cache_users
    try:
        key = (str(ACCESS_LIST_FILE), ACCESS_LIST_FILE.stat().st_mtime)
        if key != _cache_key:
            _cache_users = json.loads(ACCESS_LIST_FILE.read_text(encoding="utf-8")).get("users", {})
            _cache_key = key
        return _cache_users
    except (OSError, ValueError):
        return {}


def describe(user: str | None) -> dict | None:
    """{"user", "name", "role", "role_label", "store"} for a person on the access list, else None."""
    key = normalise(user)
    entries = {normalise(name): entry for name, entry in _users().items()}
    entry = entries.get(key)
    if not entry:
        return None
    role = entry.get("role")
    if role not in ROLE_LABELS:
        return None
    store = entry.get("store") if role == "store_manager" else None
    if role == "store_manager" and store not in STORE_RLS_IDS:
        return None
    return {
        "user": key,
        "name": key.replace("-", " ").title(),
        "role": role,
        "role_label": ROLE_LABELS[role],
        "store": store.replace("Zava Retail ", "") if store else None,
        "sees": "all 8 stores" if role == "super_manager" else store.replace("Zava Retail ", "") if store else "",
    }


__all__ = ["describe", "ROLE_LABELS", "GLOBAL_RLS_ID"]
