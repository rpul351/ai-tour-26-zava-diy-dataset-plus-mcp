"""Who may use the agent, and which Row Level Security identity each person gets.

An access list maps a person's name to a role. A super manager sees every store. A store manager sees
one store. Anyone not on the list gets nothing: there is no default identity.
"""

import json
from pathlib import Path

GLOBAL_RLS_ID = "00000000-0000-0000-0000-000000000000"

# Same identifiers as .env.example. The database, not this table, enforces what each one can see.
STORE_RLS_IDS = {
    "Zava Retail Seattle": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "Zava Retail Bellevue": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
    "Zava Retail Tacoma": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "Zava Retail Spokane": "d8e9f0a1-b2c3-4567-8901-234567890abc",
    "Zava Retail Everett": "3b9ac9fa-cd5e-4b92-a7f2-b8c1d0e9f2a3",
    "Zava Retail Redmond": "e7f8a9b0-c1d2-3e4f-5678-90abcdef1234",
    "Zava Retail Kirkland": "9c8b7a65-4321-fed0-9876-543210fedcba",
    "Zava Retail Online": "2f4e6d8c-1a3b-5c7e-9f0a-b2d4f6e8c0a2",
}


def normalise(name: str | None) -> str:
    return (name or "").strip().lower()


def describe_viewer(rls_id: str | None, user: str | None = None) -> str:
    """One sentence for the model saying who is asking, taken from the identity the service chose."""
    if rls_id == GLOBAL_RLS_ID:
        access = f"a super manager who can see all {len(STORE_RLS_IDS)} stores"
    else:
        store = next((s for s, i in STORE_RLS_IDS.items() if i == rls_id), None)
        access = f"a store manager who can see only {store}" if store else "a user whose access is not known, so assume the narrowest"
    name = normalise(user).replace("-", " ").title()
    return f"The person asking is {name}, {access}." if name else f"The person asking is {access}."


class AccessList:
    def __init__(self, users: dict[str, str]) -> None:
        self.users = users

    def rls_id_for(self, user: str | None) -> str | None:
        """The identity for this person, or None if they are not on the list."""
        return self.users.get(normalise(user)) or None


def load_access_list(path: Path) -> AccessList:
    """Read the access list. Any problem raises, so the caller fails closed instead of guessing."""
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data["users"]
    if not isinstance(entries, dict) or not entries:
        raise ValueError("the access list has no users")
    users: dict[str, str] = {}
    for name, entry in entries.items():
        role = entry.get("role")
        if role == "super_manager":
            users[normalise(name)] = GLOBAL_RLS_ID
        elif role == "store_manager":
            store = entry.get("store")
            if store not in STORE_RLS_IDS:
                raise ValueError(f"{name}: unknown store {store!r}. Use one of: {', '.join(STORE_RLS_IDS)}")
            users[normalise(name)] = STORE_RLS_IDS[store]
        else:
            raise ValueError(f"{name}: role must be super_manager or store_manager")
    return AccessList(users)
