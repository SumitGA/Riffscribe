"""Sign-ups in Clerk (run inside the API container, which has CLERK_SECRET_KEY): how many
accounts exist, and when each joined and was last active. Prints no names or emails."""

import datetime
import json
import os
import urllib.request

from api.account import CLERK_API, USER_AGENT

HEADERS = {"Authorization": f"Bearer {os.environ['CLERK_SECRET_KEY']}", "User-Agent": USER_AGENT}


def get(path: str) -> object:
    request = urllib.request.Request(CLERK_API + path, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def day(ms: int | None) -> str:
    if not ms:
        return "-"
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%Y-%m-%d")


count = get("/users/count")
users = get("/users?limit=100&order_by=-created_at")
assert isinstance(count, dict) and isinstance(users, list)
print(f"Clerk accounts (signed in at least once): {count['total_count']}")
for user in users:
    google = any("google" in a.get("provider", "") for a in user.get("external_accounts", []))
    print(
        f"  joined {day(user.get('created_at'))}"
        f"  last active {day(user.get('last_active_at') or user.get('last_sign_in_at'))}"
        f"  via {'Google' if google else 'email'}"
    )
