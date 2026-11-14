"""MindCircle server (Python standard library only, no installs needed).

Run:  python3 server.py  -> open http://127.0.0.1:8000

Environment variables (all optional):
  PORT          port to listen on (default 8000)
  DATA_FILE     path of the JSON data file (default data/mindcircle.json)
  MOD_USERNAME  moderator login created on first start (default: moderator)
  MOD_PASSWORD  moderator password (default: change-me-now, shown as a warning)
"""
import json
import os
import re
import time
import uuid
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from auth import (
    LOCKOUT_SECONDS, MAX_FAILED_LOGINS, SESSION_TTL_SECONDS, hash_password, new_token,
    token_key, validate_chat_name, validate_password, validate_signup, verify_password,
)
from content import (
    ACTIVITIES, CRISIS_RESOURCES, ENERGY_LEVELS, MOODS, NEEDS, ROOMS, pick_room,
    pseudonym, suggested_first_step,
)
from ics import MAX_EVENTS, parse_events
from recommend import RECENT_LIMIT, build_history, build_message, recommend
from safety import assess
from store import Store

BASE = Path(__file__).parent
STATIC = BASE / "static"
DEFAULT_DATA_FILE = BASE / "data" / "mindcircle.json"
MAX_BODY = 300_000          # large enough for a calendar export
MAX_MESSAGE = 500
ONLINE_WINDOW_SECONDS = 20  # a member counts as online if active in this window
DEFAULT_MOD_PASSWORD = "change-me-now"
CONTENT_TYPES = {".html": "text/html", ".js": "application/javascript", ".css": "text/css"}

STORE = None  # set by make_server()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------- Helpers ----------

def audit(d, actor, action, target=""):
    d["audit"].append({"ts": now_iso(), "actor": actor, "action": action, "target": target})


def public_user(u):
    return {"id": u["id"], "username": u["username"], "display_name": u["display_name"],
            "chat_name": u.get("chat_name", ""), "role": u["role"], "status": u["status"]}


def public_room(room):
    return {"id": room["id"], "name": room["name"], "mood": room["mood"],
            "description": room["description"], "status": room["status"],
            "members": len(room["members"])}


def username_of(d, uid):
    return d["users"].get(uid, {}).get("username", "unknown")


def chat_name_taken(d, name, exclude_id=None):
    lowered = name.lower()
    return any(u.get("chat_name", "").lower() == lowered and uid != exclude_id
               for uid, u in d["users"].items())


def unique_chat_name(d):
    for _ in range(200):
        name = pseudonym()
        if not chat_name_taken(d, name):
            return name
    return f"{pseudonym()} {uuid.uuid4().hex[:4]}"


def create_session(d, user_id):
    token = new_token()
    d["sessions"][token_key(token)] = {"user_id": user_id, "expires": time.time() + SESSION_TTL_SECONDS}
    return token


def ensure_moderator(store):
    """Create the moderator account from env vars if it does not exist yet.

    Returns True when the default password is still in use (so the server can warn).
    """
    username = os.environ.get("MOD_USERNAME", "moderator").strip() or "moderator"
    password = os.environ.get("MOD_PASSWORD", DEFAULT_MOD_PASSWORD)
    d = store.data
    with store.lock:
        if username.lower() not in d["usernames"]:
            uid = uuid.uuid4().hex
            salt, pw_hash = hash_password(password)
            d["users"][uid] = {
                "id": uid, "username": username, "display_name": "Moderator", "chat_name": "Moderator",
                "role": "moderator", "status": "active", "salt": salt, "pw_hash": pw_hash,
                "created": now_iso(), "consent": {}, "last_suggested": [],
            }
            d["usernames"][username.lower()] = uid
            audit(d, "system", "moderator_created", uid)
    return password == DEFAULT_MOD_PASSWORD


def current_user(headers):
    raw = headers.get("Authorization") or ""
    token = raw[7:].strip() if raw.startswith("Bearer ") else ""
    if not token:
        raise ApiError(401, "Please log in.")
    d = STORE.data
    sess = d["sessions"].get(token_key(token))
    if not sess or sess["expires"] < time.time():
        raise ApiError(401, "Your session has expired. Please log in again.")
    user = d["users"].get(sess["user_id"])
    if not user or user["status"] != "active":
        raise ApiError(403, "This account is suspended. Contact a moderator.")
    return user, token


def require_mod(headers):
    user, _ = current_user(headers)
    if user["role"] != "moderator":
        raise ApiError(403, "Moderators only.")
    return user


def get_room(d, room_id):
    room = d["rooms"].get(room_id)
    if not room:
        raise ApiError(404, "Room not found.")
    room.setdefault("presence", {})
    return room


def history_for(d, uid, user):
    entries = [f for f in d["feedback"] if f["user_id"] == uid]
    return build_history(entries, user.get("last_suggested", []))


def open_tasks(d, uid):
    tasks = [dict(t) for t in d["tasks"].get(uid, []) if not t["done"]]
    tasks.sort(key=lambda t: (t["deadline"] or "9999-12-31", t["created"]))
    return tasks


def priority_for(d, uid, energy, mood=None):
    tasks = open_tasks(d, uid)
    if not tasks:
        return None
    top = tasks[0]
    due = f" due {top['deadline']}" if top.get("deadline") else ""
    return {
        "task": top,
        "first_step": suggested_first_step(top["title"], energy, mood),
        "question": f"Your next priority is '{top['title']}'{due}. Do you want to start with it today?",
    }


# ---------- Accounts ----------

def handle_signup(body):
    username = (body.get("username") or "").strip()
    display = (body.get("display_name") or "").strip()
    password = body.get("password") or ""
    confirm = body.get("confirm") or ""
    errors = validate_signup(username, password, confirm, display,
                             body.get("adult"), body.get("consent"))
    if errors:
        raise ApiError(400, " ".join(errors))
    d = STORE.data
    with STORE.lock:
        if username.lower() in d["usernames"]:
            raise ApiError(409, "That username is taken.")
        uid = uuid.uuid4().hex
        salt, pw_hash = hash_password(password)
        d["users"][uid] = {
            "id": uid, "username": username, "display_name": display,
            "chat_name": unique_chat_name(d), "role": "member", "status": "active",
            "salt": salt, "pw_hash": pw_hash, "created": now_iso(),
            "consent": {"adult": True, "message_screening": True, "ts": now_iso()},
            "last_suggested": [],
        }
        d["usernames"][username.lower()] = uid
        audit(d, username, "signup", uid)
        token = create_session(d, uid)
    return {"token": token, "user": public_user(d["users"][uid])}


def handle_login(body):
    username = (body.get("username") or "").strip().lower()
    password = body.get("password") or ""
    d = STORE.data
    with STORE.lock:
        now = time.time()
        fails = [t for t in d["login_fails"].get(username, []) if now - t < LOCKOUT_SECONDS]
        d["login_fails"][username] = fails
        if len(fails) >= MAX_FAILED_LOGINS:
            raise ApiError(429, "Too many failed attempts. Try again in 15 minutes.")
        uid = d["usernames"].get(username)
        user = d["users"].get(uid) if uid else None
        if not user or not verify_password(password, user["salt"], user["pw_hash"]):
            fails.append(now)
            raise ApiError(401, "Invalid username or password.")
        if user["status"] != "active":
            raise ApiError(403, "This account is suspended. Contact a moderator.")
        d["login_fails"].pop(username, None)
        token = create_session(d, user["id"])
        if user["role"] == "moderator":
            audit(d, user["username"], "moderator_login", user["id"])
    return {"token": token, "user": public_user(user)}


def handle_logout(headers):
    _, token = current_user(headers)
    STORE.data["sessions"].pop(token_key(token), None)
    return {"status": "logged_out"}


def handle_me(headers):
    user, _ = current_user(headers)
    return {"user": public_user(user)}


def handle_profile(body, headers):
    """Change the display name or the chat name shown in groups."""
    user, _ = current_user(headers)
    d = STORE.data
    with STORE.lock:
        if "display_name" in body:
            display = (body.get("display_name") or "").strip()
            if not display or len(display) > 40:
                raise ApiError(400, "Display name is required (40 characters or fewer).")
            user["display_name"] = display
        if "chat_name" in body:
            chat = (body.get("chat_name") or "").strip()
            err = validate_chat_name(chat)
            if err:
                raise ApiError(400, err)
            if chat_name_taken(d, chat, exclude_id=user["id"]):
                raise ApiError(409, "That chat name is already in use. Try another.")
            user["chat_name"] = chat
        return {"user": public_user(user)}


def handle_change_password(body, headers):
    user, token = current_user(headers)
    d = STORE.data
    with STORE.lock:
        if not verify_password(body.get("current") or "", user["salt"], user["pw_hash"]):
            raise ApiError(400, "Current password is incorrect.")
        err = validate_password(body.get("new") or "")
        if err:
            raise ApiError(400, err)
        salt, pw_hash = hash_password(body["new"])
        user["salt"], user["pw_hash"] = salt, pw_hash
        keep = token_key(token)
        for key in [k for k, s in d["sessions"].items() if s["user_id"] == user["id"] and k != keep]:
            del d["sessions"][key]
        audit(d, user["username"], "password_changed", user["id"])
    return {"status": "changed"}


# ---------- Check-ins and suggestions (private to the member) ----------

def _validate_mood_energy_need(mood, energy, need):
    if mood not in MOODS:
        raise ApiError(400, f"mood must be one of {MOODS}.")
    if energy not in ENERGY_LEVELS:
        raise ApiError(400, f"energy must be one of {ENERGY_LEVELS}.")
    if need not in NEEDS:
        raise ApiError(400, f"need must be one of {NEEDS}.")


def handle_checkin(body, headers):
    user, _ = current_user(headers)
    mood = body.get("mood")
    energy = body.get("energy", "medium")
    need = body.get("need", "relax")
    _validate_mood_energy_need(mood, energy, need)
    d = STORE.data
    uid = user["id"]
    with STORE.lock:
        d["checkins"].append({"user_id": uid, "mood": mood, "energy": energy, "need": need, "ts": now_iso()})
        acts = recommend(mood, energy, need, history_for(d, uid, user), limit=3)
        user["last_suggested"] = (user.get("last_suggested", []) + [a["id"] for a in acts])[-RECENT_LIMIT * 2:]
        priority = priority_for(d, uid, energy, mood)
    return {
        "suggested_room": pick_room(mood),
        "message": build_message(mood, energy, need),
        "priority": priority,
        "activities": acts,
    }


def handle_activities(query, headers):
    user, _ = current_user(headers)
    mood = (query.get("mood", [""])[0] or "").strip()
    energy = query.get("energy", ["medium"])[0]
    need = query.get("need", ["relax"])[0]
    if not mood:
        return {"message": "Choose how you feel to get suggestions for you.",
                "activities": [{**a, "why": ""} for a in ACTIVITIES]}
    _validate_mood_energy_need(mood, energy, need)
    with STORE.lock:
        acts = recommend(mood, energy, need, history_for(STORE.data, user["id"], user), limit=6)
    return {"message": build_message(mood, energy, need), "activities": acts}


def handle_activity_feedback(activity_id, body, headers):
    user, _ = current_user(headers)
    if not any(a["id"] == activity_id for a in ACTIVITIES):
        raise ApiError(404, "Activity not found.")
    if not isinstance(body.get("helpful"), bool):
        raise ApiError(400, "helpful must be true or false.")
    with STORE.lock:
        STORE.data["feedback"].append({"user_id": user["id"], "activity_id": activity_id,
                                       "helpful": body["helpful"], "ts": now_iso()})
    return {"status": "saved"}


# ---------- Community chat ----------

def handle_rooms(query, headers):
    current_user(headers)
    mood = query.get("mood", [""])[0]
    with STORE.lock:
        rooms = [public_room(r) for r in STORE.data["rooms"].values()]
    if mood:
        rooms = [r for r in rooms if r["mood"] == mood]
    return {"rooms": rooms}


def handle_join(room_id, headers):
    user, _ = current_user(headers)
    with STORE.lock:
        room = get_room(STORE.data, room_id)
        if user["role"] != "moderator":
            room["members"].setdefault(user["id"], {"joined": now_iso()})
            room["presence"][user["id"]] = time.time()
        return {"chat_name": user.get("chat_name", ""), "room": public_room(room)}


def _member_list(d, room, viewer):
    now = time.time()
    members = []
    for uid in room["members"]:
        u = d["users"].get(uid, {})
        item = {
            "name": u.get("chat_name", "Member"),
            "online": now - room["presence"].get(uid, 0) < ONLINE_WINDOW_SECONDS,
            "mine": uid == viewer["id"],
        }
        if viewer["role"] == "moderator":
            item["username"] = u.get("username", "unknown")
        members.append(item)
    members.sort(key=lambda m: (not m["online"], m["name"].lower()))
    return members


def _public_message(d, m, viewer):
    if m.get("role") == "announcement":
        author = "Moderator"
    else:
        author = d["users"].get(m["user_id"], {}).get("chat_name", "Member")
    out = {
        "id": m["id"], "author": author, "role": m.get("role", "member"), "text": m["text"],
        "ts": m["ts"], "ts_epoch": m["ts_epoch"], "mine": m["user_id"] == viewer["id"],
    }
    if viewer["role"] == "moderator":
        out["username"] = username_of(d, m["user_id"])
    return out


def handle_list_messages(room_id, query, headers):
    user, _ = current_user(headers)
    since = float(query.get("since", ["0"])[0] or 0)
    d = STORE.data
    with STORE.lock:
        room = get_room(d, room_id)
        is_mod = user["role"] == "moderator"
        if not is_mod and user["id"] not in room["members"]:
            raise ApiError(403, "Join the room to read messages.")
        if user["id"] in room["members"]:
            room["presence"][user["id"]] = time.time()
        msgs = [_public_message(d, m, user) for m in room["messages"] if m["ts_epoch"] > since]
        return {
            "status": room["status"],
            "room": public_room(room),
            "members": _member_list(d, room, user),
            "messages": msgs,
        }


def handle_post_message(room_id, body, headers):
    user, _ = current_user(headers)
    if user["role"] == "moderator":
        raise ApiError(403, "Moderators monitor rooms. Use an announcement from the Moderator tab.")
    text = (body.get("text") or "").strip()
    if not text:
        raise ApiError(400, "Message cannot be empty.")
    if len(text) > MAX_MESSAGE:
        raise ApiError(400, f"Message must be {MAX_MESSAGE} characters or fewer.")
    d = STORE.data
    with STORE.lock:
        room = get_room(d, room_id)
        if user["id"] not in room["members"]:
            raise ApiError(403, "Join the room before posting.")
        if room["status"] == "red_flag":
            raise ApiError(423, "This room is paused for safety review. Please try again later.")
        room["presence"][user["id"]] = time.time()
        result = assess(text)
        if result["hold"]:
            d["queue"].append({
                "id": uuid.uuid4().hex[:10], "kind": "held", "room_id": room_id,
                "author": user.get("chat_name", "Member"), "subject_user_id": user["id"],
                "username": user["username"], "text": text, "categories": result["categories"],
                "level": result["level"], "status": "open", "ts": now_iso(),
            })
            if result["red_flag"]:
                room["status"] = "red_flag"
                audit(d, "system", "room_red_flagged", room_id)
            return {
                "status": "held",
                "message": "Your message was not posted. A trained moderator will review it.",
                "show_crisis": result["show_crisis"],
                "crisis": CRISIS_RESOURCES["US"] if result["show_crisis"] else None,
            }
        msg = {"id": uuid.uuid4().hex[:10], "user_id": user["id"], "role": "member", "text": text,
               "ts": now_iso(), "ts_epoch": time.time()}
        room["messages"].append(msg)
        if result["needs_review"]:
            d["queue"].append({
                "id": uuid.uuid4().hex[:10], "kind": "review", "room_id": room_id,
                "author": user.get("chat_name", "Member"), "subject_user_id": user["id"],
                "username": user["username"], "text": text, "categories": result["categories"],
                "level": result["level"], "message_id": msg["id"], "status": "open", "ts": now_iso(),
            })
    response = {"status": "posted", "message": _public_message(d, msg, user)}
    if result["show_support_tip"]:
        response["support_tip"] = "Thanks for sharing. If you are struggling, reaching out to someone you trust can help."
    return response


def handle_report(room_id, body, headers):
    user, _ = current_user(headers)
    message_id = body.get("message_id", "")
    reason = (body.get("reason") or "Reported by member")[:200]
    d = STORE.data
    with STORE.lock:
        room = get_room(d, room_id)
        if user["id"] not in room["members"]:
            raise ApiError(403, "Join the room to report messages.")
        msg = next((m for m in room["messages"] if m["id"] == message_id), None)
        if not msg:
            raise ApiError(404, "Message not found.")
        d["queue"].append({
            "id": uuid.uuid4().hex[:10], "kind": "report", "room_id": room_id,
            "author": d["users"].get(msg["user_id"], {}).get("chat_name", "Member"),
            "subject_user_id": msg["user_id"], "username": username_of(d, msg["user_id"]),
            "reporter_id": user["id"], "text": msg["text"], "categories": ["member_report"],
            "level": None, "message_id": message_id, "reason": reason, "status": "open", "ts": now_iso(),
        })
    return {"status": "reported"}


# ---------- Priorities and calendar ----------

def handle_list_tasks(query, headers):
    user, _ = current_user(headers)
    energy = query.get("energy", ["medium"])[0]
    with STORE.lock:
        tasks = open_tasks(STORE.data, user["id"])
    top = tasks[0] if tasks else None
    return {
        "tasks": tasks,
        "priority": top,
        "suggested_first_step": suggested_first_step(top["title"], energy) if top else None,
    }


def handle_add_task(body, headers):
    user, _ = current_user(headers)
    title = (body.get("title") or "").strip()
    deadline = (body.get("deadline") or "").strip() or None
    if not title or len(title) > 120:
        raise ApiError(400, "title is required (max 120 characters).")
    if deadline:
        try:
            datetime.strptime(deadline, "%Y-%m-%d")
        except ValueError:
            raise ApiError(400, "deadline must be YYYY-MM-DD.")
    task = {"id": uuid.uuid4().hex[:10], "title": title, "deadline": deadline,
            "done": False, "created": now_iso(), "source": "manual"}
    with STORE.lock:
        STORE.data["tasks"].setdefault(user["id"], []).append(task)
    return {"task": task}


def handle_import_ics(body, headers):
    user, _ = current_user(headers)
    text = body.get("ics")
    if not isinstance(text, str) or not text.strip():
        raise ApiError(400, "Paste or choose an .ics calendar file first.")
    events = parse_events(text)
    if not events:
        raise ApiError(400, "No events found. Export your calendar as an .ics file and try again.")
    today = date.today().isoformat()
    d = STORE.data
    imported = skipped = 0
    with STORE.lock:
        tasks = d["tasks"].setdefault(user["id"], [])
        existing = {(t["title"], t.get("deadline")) for t in tasks}
        for ev in events:
            if ev["date"] < today or (ev["title"], ev["date"]) in existing:
                skipped += 1
                continue
            if imported >= MAX_EVENTS:
                break
            tasks.append({"id": uuid.uuid4().hex[:10], "title": ev["title"], "deadline": ev["date"],
                          "done": False, "created": now_iso(), "source": "calendar"})
            existing.add((ev["title"], ev["date"]))
            imported += 1
    return {"imported": imported, "skipped": skipped}


def handle_complete_task(task_id, headers):
    user, _ = current_user(headers)
    with STORE.lock:
        for t in STORE.data["tasks"].get(user["id"], []):
            if t["id"] == task_id:
                t["done"] = True
                return {"status": "done"}
    raise ApiError(404, "Task not found.")


# ---------- Crisis resources (public) ----------

def handle_crisis(query):
    country = (query.get("country", ["US"])[0] or "US").upper()
    return CRISIS_RESOURCES.get(country, CRISIS_RESOURCES["OTHER"])


# ---------- Moderator: safety queue and chat monitoring ----------

def handle_mod_queue(headers):
    mod = require_mod(headers)
    d = STORE.data
    with STORE.lock:
        items = [dict(i) for i in d["queue"] if i["status"] == "open"]
        rooms = [public_room(r) for r in d["rooms"].values() if r["status"] == "red_flag"]
        audit(d, mod["username"], "queue_viewed", "")
    items.sort(key=lambda i: (-(i["level"] or 0), i["ts"]))
    return {"queue": items, "red_flag_rooms": rooms}


def handle_mod_resolve(item_id, body, headers):
    mod = require_mod(headers)
    action = body.get("action")
    if action not in ("release", "dismiss", "confirm"):
        raise ApiError(400, "action must be release, dismiss, or confirm.")
    d = STORE.data
    with STORE.lock:
        item = next((i for i in d["queue"] if i["id"] == item_id), None)
        if not item:
            raise ApiError(404, "Queue item not found.")
        if item["status"] != "open":
            raise ApiError(409, "Item already resolved.")
        room = get_room(d, item["room_id"])
        if action == "release" and item["kind"] == "held":
            room["messages"].append({
                "id": uuid.uuid4().hex[:10], "user_id": item["subject_user_id"], "role": "member",
                "text": item["text"], "ts": now_iso(), "ts_epoch": time.time(),
            })
        item["status"] = action + "d"
        item["resolved_at"] = now_iso()
        item["resolved_by"] = mod["username"]
        audit(d, mod["username"], f"queue_{action}", item_id)
    return {"status": item["status"]}


def handle_mod_clear_room(room_id, headers):
    mod = require_mod(headers)
    d = STORE.data
    with STORE.lock:
        room = get_room(d, room_id)
        room["status"] = "open"
        audit(d, mod["username"], "room_cleared", room_id)
    return {"status": "open"}


def handle_mod_announce(room_id, body, headers):
    mod = require_mod(headers)
    text = (body.get("text") or "").strip()
    if not text or len(text) > MAX_MESSAGE:
        raise ApiError(400, f"Announcement must be 1 to {MAX_MESSAGE} characters.")
    d = STORE.data
    with STORE.lock:
        room = get_room(d, room_id)
        msg = {"id": uuid.uuid4().hex[:10], "user_id": mod["id"], "role": "announcement",
               "text": text, "ts": now_iso(), "ts_epoch": time.time()}
        room["messages"].append(msg)
        audit(d, mod["username"], "announcement", room_id)
    return {"status": "posted"}


def handle_mod_room_detail(room_id, query, headers):
    """Full monitor view of one room: messages with usernames, members, and open flags."""
    mod = require_mod(headers)
    d = STORE.data
    with STORE.lock:
        room = get_room(d, room_id)
        msgs = [_public_message(d, m, mod) for m in room["messages"]]
        flags = [dict(i) for i in d["queue"] if i["room_id"] == room_id and i["status"] == "open"]
        audit(d, mod["username"], "room_monitored", room_id)
        return {
            "room": public_room(room),
            "members": _member_list(d, room, mod),
            "messages": msgs,
            "flags": flags,
        }


# ---------- Moderator: account monitoring ----------

def handle_mod_users(headers):
    """Account-level view only. Moods, check-ins, and tasks are never shown to moderators."""
    mod = require_mod(headers)
    d = STORE.data
    with STORE.lock:
        out = []
        for u in d["users"].values():
            uid = u["id"]
            posted = sum(1 for r in d["rooms"].values() for m in r["messages"] if m.get("user_id") == uid)
            held = sum(1 for i in d["queue"] if i.get("subject_user_id") == uid and i["kind"] == "held")
            flags = sum(1 for i in d["queue"] if i.get("subject_user_id") == uid)
            out.append({
                **public_user(u), "created": u.get("created"),
                "messages_posted": posted, "held_messages": held, "flags": flags,
            })
        audit(d, mod["username"], "users_viewed", "")
    out.sort(key=lambda x: (-x["flags"], x["username"].lower()))
    return {"users": out}


def handle_mod_user_status(user_id, body, headers):
    mod = require_mod(headers)
    status = body.get("status")
    if status not in ("active", "suspended"):
        raise ApiError(400, "status must be active or suspended.")
    d = STORE.data
    with STORE.lock:
        target = d["users"].get(user_id)
        if not target:
            raise ApiError(404, "User not found.")
        if target["role"] == "moderator":
            raise ApiError(400, "Moderator accounts cannot be suspended from this screen.")
        target["status"] = status
        if status == "suspended":
            for key in [k for k, s in d["sessions"].items() if s["user_id"] == user_id]:
                del d["sessions"][key]
        audit(d, mod["username"], f"account_{status}", user_id)
    return {"status": status}


def handle_mod_audit(headers):
    require_mod(headers)
    with STORE.lock:
        entries = list(reversed(STORE.data["audit"][-200:]))
    return {"audit": entries}


# ---------- Routing ----------

ROUTES_GET = [
    (r"^/api/auth/me$", lambda m, q, b, h: handle_me(h)),
    (r"^/api/activities$", lambda m, q, b, h: handle_activities(q, h)),
    (r"^/api/rooms$", lambda m, q, b, h: handle_rooms(q, h)),
    (r"^/api/rooms/([\w-]+)/messages$", lambda m, q, b, h: handle_list_messages(m.group(1), q, h)),
    (r"^/api/tasks$", lambda m, q, b, h: handle_list_tasks(q, h)),
    (r"^/api/crisis$", lambda m, q, b, h: handle_crisis(q)),
    (r"^/api/mod/queue$", lambda m, q, b, h: handle_mod_queue(h)),
    (r"^/api/mod/rooms/([\w-]+)$", lambda m, q, b, h: handle_mod_room_detail(m.group(1), q, h)),
    (r"^/api/mod/users$", lambda m, q, b, h: handle_mod_users(h)),
    (r"^/api/mod/audit$", lambda m, q, b, h: handle_mod_audit(h)),
]
ROUTES_POST = [
    (r"^/api/auth/signup$", lambda m, q, b, h: handle_signup(b)),
    (r"^/api/auth/login$", lambda m, q, b, h: handle_login(b)),
    (r"^/api/auth/logout$", lambda m, q, b, h: handle_logout(h)),
    (r"^/api/auth/password$", lambda m, q, b, h: handle_change_password(b, h)),
    (r"^/api/auth/profile$", lambda m, q, b, h: handle_profile(b, h)),
    (r"^/api/checkin$", lambda m, q, b, h: handle_checkin(b, h)),
    (r"^/api/activities/([\w-]+)/feedback$", lambda m, q, b, h: handle_activity_feedback(m.group(1), b, h)),
    (r"^/api/rooms/([\w-]+)/join$", lambda m, q, b, h: handle_join(m.group(1), h)),
    (r"^/api/rooms/([\w-]+)/messages$", lambda m, q, b, h: handle_post_message(m.group(1), b, h)),
    (r"^/api/rooms/([\w-]+)/report$", lambda m, q, b, h: handle_report(m.group(1), b, h)),
    (r"^/api/tasks$", lambda m, q, b, h: handle_add_task(b, h)),
    (r"^/api/tasks/import-ics$", lambda m, q, b, h: handle_import_ics(b, h)),
    (r"^/api/tasks/([\w-]+)/done$", lambda m, q, b, h: handle_complete_task(m.group(1), h)),
    (r"^/api/mod/queue/([\w-]+)/resolve$", lambda m, q, b, h: handle_mod_resolve(m.group(1), b, h)),
    (r"^/api/mod/rooms/([\w-]+)/clear$", lambda m, q, b, h: handle_mod_clear_room(m.group(1), h)),
    (r"^/api/mod/rooms/([\w-]+)/announce$", lambda m, q, b, h: handle_mod_announce(m.group(1), b, h)),
    (r"^/api/mod/users/([\w-]+)/status$", lambda m, q, b, h: handle_mod_user_status(m.group(1), b, h)),
]


class Handler(BaseHTTPRequestHandler):
    server_version = "MindCircle/0.3"

    def log_message(self, fmt, *args):  # keep output quiet
        pass

    def _send_json(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError(413, "Request too large.")
        if length == 0:
            return {}
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "Body must be valid JSON.")
        if not isinstance(body, dict):
            raise ApiError(400, "Body must be a JSON object.")
        return body

    def _dispatch(self, routes, body):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        for pattern, fn in routes:
            m = re.match(pattern, parsed.path)
            if m:
                return fn(m, query, body, self.headers)
        return None

    def _serve_static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        target = (STATIC / path.lstrip("/")).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, method):
        try:
            path = urlparse(self.path).path
            if method == "GET" and not path.startswith("/api/"):
                return self._serve_static(path)
            body = self._read_body() if method == "POST" else {}
            routes = ROUTES_GET if method == "GET" else ROUTES_POST
            try:
                result = self._dispatch(routes, body)
            finally:
                if method == "POST":
                    STORE.save()
            if result is None:
                return self._send_json(404, {"error": "Not found."})
            self._send_json(200, result)
        except ApiError as e:
            self._send_json(e.status, {"error": e.message})
        except Exception:  # never leak stack traces to clients
            self._send_json(500, {"error": "Something went wrong. Please try again."})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


def make_server(host="127.0.0.1", port=8000, data_file=None):
    """Create the server. data_file=None uses the default file; pass '' for memory-only."""
    global STORE
    if data_file is None:
        data_file = os.environ.get("DATA_FILE", str(DEFAULT_DATA_FILE))
    STORE = Store(data_file or None)
    ensure_moderator(STORE)
    STORE.save()
    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    httpd = make_server("127.0.0.1", port)
    print(f"MindCircle running at http://127.0.0.1:{port}")
    if os.environ.get("MOD_PASSWORD") is None:
        print("WARNING: moderator is using the default password. Set MOD_PASSWORD before real use.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
