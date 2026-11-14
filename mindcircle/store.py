"""Data store: one JSON file on the server (no database install needed).

The whole state lives in memory and is written to disk after each change,
using a temp file and an atomic rename. For a real launch, replace this with
a hosted database (PostgreSQL, Supabase, Firebase) and keep the same API.
"""
import json
import os
import threading

from content import ROOMS


def new_data():
    return {
        "users": {},        # user_id -> account (includes password hash)
        "usernames": {},    # lowercase username -> user_id
        "sessions": {},     # sha256(token) -> {user_id, expires}
        "login_fails": {},  # lowercase username -> [epoch seconds]
        "checkins": [],     # private: never returned to moderators or other members
        "feedback": [],     # activity helpful / not-for-me votes
        "tasks": {},        # user_id -> [tasks]
        "rooms": {
            r["id"]: {**r, "status": "open", "members": {}, "messages": []} for r in ROOMS
        },
        "queue": [],        # moderator queue: held messages, reviews, reports
        "audit": [],        # moderator and account actions (no message bodies)
    }


class Store:
    def __init__(self, path=None):
        self.path = path
        self.lock = threading.RLock()
        self.data = new_data()
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                loaded = json.load(f)
            merged = new_data()
            merged.update(loaded)
            self.data = merged

    def save(self):
        """Write the state to disk atomically. No-op when no path is set."""
        if not self.path:
            return
        with self.lock:
            folder = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(folder, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)
