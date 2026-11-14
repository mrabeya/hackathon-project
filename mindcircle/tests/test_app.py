"""Run with:  python3 -m unittest discover -s tests -v   (from the project folder)"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["MOD_USERNAME"] = "moderator"
os.environ["MOD_PASSWORD"] = "test-mod-pass-123"

import server  # noqa: E402
from auth import hash_password, validate_signup, verify_password  # noqa: E402
from content import ACTIVITIES, MOOD_PROFILES, MOODS, ROOMS, suggested_first_step  # noqa: E402
from ics import parse_events  # noqa: E402
from recommend import build_history, build_message, recommend  # noqa: E402
from safety import assess  # noqa: E402
from store import Store  # noqa: E402

MOD_PASS = "test-mod-pass-123"
PW = "correct-horse-1"


# ---------- Safety ----------

class SafetyRulesTests(unittest.TestCase):
    def test_normal_message_is_allowed(self):
        r = assess("Had a nice walk with my dog today")
        self.assertEqual(r["level"], 0)
        self.assertFalse(r["hold"])

    def test_distress_is_supported_not_held(self):
        r = assess("I feel really anxious about my exam")
        self.assertEqual(r["level"], 1)
        self.assertFalse(r["hold"])
        self.assertTrue(r["show_support_tip"])

    def test_concerning_is_posted_but_reviewed(self):
        r = assess("I feel hopeless lately")
        self.assertEqual(r["level"], 2)
        self.assertFalse(r["hold"])
        self.assertTrue(r["needs_review"])

    def test_serious_self_harm_is_held_with_crisis_panel(self):
        r = assess("I want to die")
        self.assertEqual(r["level"], 3)
        self.assertTrue(r["hold"])
        self.assertTrue(r["show_crisis"])

    def test_imminent_self_harm_red_flags_room(self):
        r = assess("I'm going to end my life tonight")
        self.assertEqual(r["level"], 4)
        self.assertTrue(r["red_flag"])

    def test_threat_is_red_flagged(self):
        self.assertTrue(assess("I will hurt him tomorrow")["red_flag"])

    def test_crime_planning_is_red_flagged(self):
        r = assess("I'm planning to rob the store on Friday")
        self.assertIn("crime_planning", r["categories"])
        self.assertTrue(r["red_flag"])

    def test_educational_third_person_is_not_escalated(self):
        r = assess("Suicide prevention article was useful for the news story")
        self.assertLess(r["level"], 3)
        self.assertFalse(r["red_flag"])

    def test_first_person_context_is_not_de_escalated(self):
        r = assess("I read an article and now I want to die")
        self.assertEqual(r["level"], 3)
        self.assertTrue(r["hold"])


# ---------- Content and personalisation ----------

class ContentTests(unittest.TestCase):
    def test_every_mood_has_enough_activities(self):
        for mood in MOODS:
            matches = [a for a in ACTIVITIES if mood in a["moods"]]
            self.assertGreaterEqual(len(matches), 3, mood)

    def test_every_mood_has_its_own_message(self):
        messages = {build_message(m, "medium", "relax") for m in MOODS}
        self.assertEqual(len(messages), len(MOODS))
        self.assertEqual(set(MOOD_PROFILES), set(MOODS))

    def test_different_moods_get_different_top_suggestions(self):
        empty = build_history([], [])
        tops = {m: tuple(a["id"] for a in recommend(m, "medium", "relax", empty)) for m in MOODS}
        self.assertGreater(len(set(tops.values())), 4)

    def test_need_changes_the_suggestions(self):
        empty = build_history([], [])
        relax = [a["id"] for a in recommend("stressed", "medium", "relax", empty)]
        focus = [a["id"] for a in recommend("stressed", "medium", "focus", empty)]
        self.assertNotEqual(relax, focus)

    def test_low_energy_prefers_short_activities(self):
        empty = build_history([], [])
        picks = recommend("exhausted", "low", "relax", empty, limit=3)
        self.assertTrue(all(a["minutes"] <= 15 for a in picks))

    def test_helpful_feedback_boosts_an_activity(self):
        empty = build_history([], [])
        before = [a["id"] for a in recommend("sad", "medium", "relax", empty, limit=6)]
        target = before[-1]
        hist = build_history([{"activity_id": target, "helpful": True}], [])
        after = [a["id"] for a in recommend("sad", "medium", "relax", hist, limit=6)]
        self.assertLess(after.index(target), before.index(target))

    def test_not_for_me_removes_an_activity_from_top(self):
        empty = build_history([], [])
        top = recommend("anxious", "medium", "relax", empty, limit=1)[0]["id"]
        hist = build_history([{"activity_id": top, "helpful": False}], [])
        self.assertNotEqual(recommend("anxious", "medium", "relax", hist, limit=1)[0]["id"], top)

    def test_recently_shown_activities_are_avoided(self):
        empty = build_history([], [])
        top = recommend("calm", "medium", "relax", empty, limit=1)[0]["id"]
        hist = build_history([], [top])
        self.assertNotEqual(recommend("calm", "medium", "relax", hist, limit=1)[0]["id"], top)

    def test_reasons_are_given(self):
        picks = recommend("anxious", "low", "relax", build_history([], []), limit=2)
        self.assertTrue(all(p["why"].startswith("Picked because") for p in picks))


# ---------- Accounts ----------

class AuthUnitTests(unittest.TestCase):
    def test_password_hash_roundtrip(self):
        salt, h = hash_password("secret-pass-1")
        self.assertTrue(verify_password("secret-pass-1", salt, h))
        self.assertFalse(verify_password("wrong-pass-1", salt, h))

    def test_signup_validation(self):
        errs = validate_signup("a", "short", "other", "", False, False)
        self.assertGreaterEqual(len(errs), 5)
        self.assertEqual(validate_signup("good_user", PW, PW, "Sam", True, True), [])


class ApiTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server("127.0.0.1", 0, data_file="")
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        # Fresh in-memory store for every test, with the moderator account seeded.
        server.STORE = Store(None)
        server.ensure_moderator(server.STORE)

    def call(self, method, path, body=None, token=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, json.loads(res.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def signup(self, username, display="Test User"):
        status, data = self.call("POST", "/api/auth/signup", {
            "username": username, "display_name": display, "password": PW, "confirm": PW,
            "adult": True, "consent": True,
        })
        self.assertEqual(status, 200, data)
        return data["token"], data["user"]

    def mod_token(self):
        _, data = self.call("POST", "/api/auth/login", {"username": "moderator", "password": MOD_PASS})
        return data["token"]


class AccountApiTests(ApiTestBase):
    def test_signup_then_me(self):
        token, user = self.signup("alice_01")
        status, data = self.call("GET", "/api/auth/me", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(data["user"]["username"], "alice_01")
        self.assertEqual(data["user"]["role"], "member")
        self.assertNotIn("pw_hash", json.dumps(data))

    def test_duplicate_username_rejected_case_insensitive(self):
        self.signup("Bob_42")
        status, _ = self.call("POST", "/api/auth/signup", {
            "username": "bob_42", "display_name": "x", "password": PW, "confirm": PW,
            "adult": True, "consent": True,
        })
        self.assertEqual(status, 409)

    def test_signup_requires_adult_and_consent(self):
        status, data = self.call("POST", "/api/auth/signup", {
            "username": "young_1", "display_name": "x", "password": PW, "confirm": PW,
            "adult": False, "consent": True,
        })
        self.assertEqual(status, 400)
        self.assertIn("18", data["error"])

    def test_login_wrong_password_is_generic(self):
        self.signup("carol_1")
        status, data = self.call("POST", "/api/auth/login", {"username": "carol_1", "password": "nope-nope"})
        self.assertEqual(status, 401)
        self.assertEqual(data["error"], "Invalid username or password.")

    def test_lockout_after_repeated_failures(self):
        self.signup("dave_11")
        for _ in range(server.MAX_FAILED_LOGINS):
            self.call("POST", "/api/auth/login", {"username": "dave_11", "password": "bad-guess-1"})
        status, _ = self.call("POST", "/api/auth/login", {"username": "dave_11", "password": PW})
        self.assertEqual(status, 429)

    def test_logout_invalidates_token(self):
        token, _ = self.signup("erin_1")
        self.call("POST", "/api/auth/logout", token=token)
        status, _ = self.call("GET", "/api/auth/me", token=token)
        self.assertEqual(status, 401)

    def test_password_change(self):
        token, _ = self.signup("frank_1")
        status, _ = self.call("POST", "/api/auth/password",
                              {"current": PW, "new": "brand-new-pass-2"}, token=token)
        self.assertEqual(status, 200)
        self.assertEqual(self.call("POST", "/api/auth/login",
                                   {"username": "frank_1", "password": PW})[0], 401)
        self.assertEqual(self.call("POST", "/api/auth/login",
                                   {"username": "frank_1", "password": "brand-new-pass-2"})[0], 200)

    def test_protected_routes_need_login(self):
        self.assertEqual(self.call("GET", "/api/rooms")[0], 401)
        self.assertEqual(self.call("POST", "/api/checkin", {"mood": "calm"})[0], 401)

    def test_members_cannot_open_moderator_routes(self):
        token, _ = self.signup("gina_1")
        self.assertEqual(self.call("GET", "/api/mod/queue", token=token)[0], 403)
        self.assertEqual(self.call("GET", "/api/mod/users", token=token)[0], 403)

    def test_moderator_seeded_and_can_log_in(self):
        status, data = self.call("POST", "/api/auth/login", {"username": "moderator", "password": MOD_PASS})
        self.assertEqual(status, 200)
        self.assertEqual(data["user"]["role"], "moderator")
        self.assertEqual(self.call("GET", "/api/mod/queue", token=data["token"])[0], 200)


class SuspensionTests(ApiTestBase):
    def test_suspended_user_is_blocked_everywhere(self):
        token, user = self.signup("hank_1")
        mod = self.mod_token()
        status, _ = self.call("POST", f"/api/mod/users/{user['id']}/status", {"status": "suspended"}, token=mod)
        self.assertEqual(status, 200)
        self.assertEqual(self.call("GET", "/api/auth/me", token=token)[0], 401)  # session revoked
        status, data = self.call("POST", "/api/auth/login", {"username": "hank_1", "password": PW})
        self.assertEqual(status, 403)
        self.assertIn("suspended", data["error"])

    def test_reactivate_allows_login_again(self):
        _, user = self.signup("ivy_1")
        mod = self.mod_token()
        self.call("POST", f"/api/mod/users/{user['id']}/status", {"status": "suspended"}, token=mod)
        self.call("POST", f"/api/mod/users/{user['id']}/status", {"status": "active"}, token=mod)
        self.assertEqual(self.call("POST", "/api/auth/login", {"username": "ivy_1", "password": PW})[0], 200)

    def test_moderator_accounts_cannot_be_suspended(self):
        mod = self.mod_token()
        mod_id = server.STORE.data["usernames"]["moderator"]
        status, _ = self.call("POST", f"/api/mod/users/{mod_id}/status", {"status": "suspended"}, token=mod)
        self.assertEqual(status, 400)


class GroupChatTests(ApiTestBase):
    def test_multiple_users_chat_in_the_same_group(self):
        t1, _ = self.signup("chat_one")
        t2, _ = self.signup("chat_two")
        t3, _ = self.signup("chat_three")
        room = "anxiety-support"
        for t in (t1, t2, t3):
            self.assertEqual(self.call("POST", f"/api/rooms/{room}/join", token=t)[0], 200)

        self.call("POST", f"/api/rooms/{room}/messages", {"text": "Breathing helped me"}, token=t1)
        self.call("POST", f"/api/rooms/{room}/messages", {"text": "Same here, thank you"}, token=t2)
        self.call("POST", f"/api/rooms/{room}/messages", {"text": "Glad to hear it"}, token=t3)

        _, feed = self.call("GET", f"/api/rooms/{room}/messages?since=0", token=t1)
        self.assertEqual(len(feed["messages"]), 3)
        authors = {m["author"] for m in feed["messages"]}
        self.assertEqual(len(authors), 3)  # three distinct pseudonyms
        self.assertNotIn("user_id", json.dumps(feed))  # no account identity leaks to members

    def test_non_member_cannot_read_or_post(self):
        t1, _ = self.signup("outsider_1")
        t2, _ = self.signup("insider_1")
        self.call("POST", "/api/rooms/stress-relief/join", token=t2)
        self.assertEqual(self.call("GET", "/api/rooms/stress-relief/messages?since=0", token=t1)[0], 403)
        self.assertEqual(self.call("POST", "/api/rooms/stress-relief/messages", {"text": "hi"}, token=t1)[0], 403)

    def test_serious_message_is_held_and_not_visible_to_others(self):
        t1, _ = self.signup("held_one")
        t2, _ = self.signup("viewer_1")
        for t in (t1, t2):
            self.call("POST", "/api/rooms/gentle-peer-support/join", token=t)
        status, data = self.call("POST", "/api/rooms/gentle-peer-support/messages", {"text": "I want to die"}, token=t1)
        self.assertEqual(data["status"], "held")
        self.assertIsNotNone(data["crisis"])
        _, feed = self.call("GET", "/api/rooms/gentle-peer-support/messages?since=0", token=t2)
        self.assertEqual(feed["messages"], [])

    def test_red_flag_pauses_room_for_everyone_until_cleared(self):
        t1, _ = self.signup("flagger_1")
        t2, _ = self.signup("bystander_1")
        for t in (t1, t2):
            self.call("POST", "/api/rooms/stress-relief/join", token=t)
        self.call("POST", "/api/rooms/stress-relief/messages", {"text": "I'm going to end my life tonight"}, token=t1)
        self.assertEqual(self.call("POST", "/api/rooms/stress-relief/messages", {"text": "anyone?"}, token=t2)[0], 423)

        mod = self.mod_token()
        self.assertEqual(self.call("POST", "/api/mod/rooms/stress-relief/clear", token=mod)[0], 200)
        self.assertEqual(self.call("POST", "/api/rooms/stress-relief/messages", {"text": "back"}, token=t2)[0], 200)

    def test_member_report_reaches_moderator_with_account_name(self):
        t1, _ = self.signup("reported_1")
        t2, _ = self.signup("reporter_1")
        for t in (t1, t2):
            self.call("POST", "/api/rooms/youre-not-alone/join", token=t)
        self.call("POST", "/api/rooms/youre-not-alone/messages", {"text": "Hello everyone"}, token=t1)
        _, feed = self.call("GET", "/api/rooms/youre-not-alone/messages?since=0", token=t2)
        self.assertEqual(self.call("POST", "/api/rooms/youre-not-alone/report",
                                   {"message_id": feed["messages"][0]["id"]}, token=t2)[0], 200)
        mod = self.mod_token()
        _, queue = self.call("GET", "/api/mod/queue", token=mod)
        item = queue["queue"][0]
        self.assertEqual(item["kind"], "report")
        self.assertEqual(item["username"], "reported_1")

    def test_moderator_release_posts_held_message(self):
        t1, _ = self.signup("release_me")
        self.call("POST", "/api/rooms/mindfulness-circle/join", token=t1)
        self.call("POST", "/api/rooms/mindfulness-circle/messages", {"text": "I want to die"}, token=t1)
        mod = self.mod_token()
        _, queue = self.call("GET", "/api/mod/queue", token=mod)
        item_id = queue["queue"][0]["id"]
        self.assertEqual(self.call("POST", f"/api/mod/queue/{item_id}/resolve", {"action": "release"}, token=mod)[0], 200)
        _, feed = self.call("GET", "/api/rooms/mindfulness-circle/messages?since=0", token=t1)
        self.assertEqual(len(feed["messages"]), 1)


class MemberFeatureTests(ApiTestBase):
    def test_checkin_gives_mood_specific_message(self):
        t, _ = self.signup("mood_one")
        _, a = self.call("POST", "/api/checkin", {"mood": "anxious", "energy": "low", "need": "relax"}, token=t)
        _, b = self.call("POST", "/api/checkin", {"mood": "happy", "energy": "high", "need": "focus"}, token=t)
        self.assertNotEqual(a["message"], b["message"])
        self.assertEqual(a["suggested_room"], "anxiety-support")
        self.assertTrue(all("why" in x for x in a["activities"]))

    def test_feedback_changes_future_suggestions(self):
        t, _ = self.signup("feedback_one")
        _, first = self.call("GET", "/api/activities?mood=sad&energy=medium&need=relax", token=t)
        target = first["activities"][-1]["id"]
        self.call("POST", f"/api/activities/{target}/feedback", {"helpful": True}, token=t)
        _, second = self.call("GET", "/api/activities?mood=sad&energy=medium&need=relax", token=t)
        ids = [a["id"] for a in second["activities"]]
        self.assertLess(ids.index(target), len(ids) - 1)

    def test_feedback_is_private_to_user(self):
        t1, _ = self.signup("private_a")
        t2, _ = self.signup("private_b")
        self.call("POST", "/api/activities/box-breathing/feedback", {"helpful": False}, token=t1)
        _, data = self.call("GET", "/api/activities?mood=anxious&energy=medium&need=relax", token=t2)
        self.assertIn("box-breathing", [a["id"] for a in data["activities"]])

    def test_checkin_rejects_bad_mood(self):
        t, _ = self.signup("bad_mood")
        self.assertEqual(self.call("POST", "/api/checkin", {"mood": "bogus"}, token=t)[0], 400)

    def test_tasks_priority_is_earliest_deadline(self):
        t, _ = self.signup("planner_1")
        self.call("POST", "/api/tasks", {"title": "Later task", "deadline": "2099-12-01"}, token=t)
        self.call("POST", "/api/tasks", {"title": "Soon task", "deadline": "2099-01-01"}, token=t)
        _, data = self.call("GET", "/api/tasks?energy=low", token=t)
        self.assertEqual(data["priority"]["title"], "Soon task")

    def test_tasks_are_private(self):
        t1, _ = self.signup("task_a")
        t2, _ = self.signup("task_b")
        self.call("POST", "/api/tasks", {"title": "Secret"}, token=t1)
        _, data = self.call("GET", "/api/tasks", token=t2)
        self.assertEqual(data["tasks"], [])

    def test_crisis_defaults_to_us_numbers(self):
        _, data = self.call("GET", "/api/crisis?country=US")
        self.assertIn("988", data["crisis"][0]["action"])
        self.assertIn("911", data["emergency"]["action"])


class ModeratorMonitoringTests(ApiTestBase):
    def test_user_list_has_account_info_but_no_mood_or_task_data(self):
        t, _ = self.signup("watched_1")
        self.call("POST", "/api/checkin", {"mood": "sad", "energy": "low", "need": "talk"}, token=t)
        self.call("POST", "/api/tasks", {"title": "Private task"}, token=t)
        mod = self.mod_token()
        status, data = self.call("GET", "/api/mod/users", token=mod)
        self.assertEqual(status, 200)
        names = [u["username"] for u in data["users"]]
        self.assertIn("watched_1", names)
        raw = json.dumps(data)
        self.assertNotIn("pw_hash", raw)
        self.assertNotIn("salt", raw)
        self.assertNotIn('"mood"', raw)
        self.assertNotIn("Private task", raw)

    def test_actions_are_written_to_audit_log(self):
        t, user = self.signup("audited_1")
        mod = self.mod_token()
        self.call("POST", f"/api/mod/users/{user['id']}/status", {"status": "suspended"}, token=mod)
        _, data = self.call("GET", "/api/mod/audit", token=mod)
        actions = [e["action"] for e in data["audit"]]
        self.assertIn("account_suspended", actions)
        self.assertIn("signup", actions)

    def test_wrong_moderator_password_fails(self):
        self.assertEqual(self.call("POST", "/api/auth/login",
                                   {"username": "moderator", "password": "nope-nope-1"})[0], 401)


class StaticTests(ApiTestBase):
    def test_index_served(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as res:
            self.assertEqual(res.status, 200)
            self.assertIn(b"MindCircle", res.read())

    def test_path_traversal_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/..%2fserver.py")
        self.assertEqual(ctx.exception.code, 404)


ICS_SAMPLE = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:1
SUMMARY:Research proposal\\, draft due
DTSTART;VALUE=DATE:20991201
END:VEVENT
BEGIN:VEVENT
UID:2
SUMMARY:Old meeting
DTSTART:20000105T090000Z
END:VEVENT
BEGIN:VEVENT
UID:3
SUMMARY:Long folded
  title
DTSTART:20991015T140000
END:VEVENT
BEGIN:VEVENT
UID:4
SUMMARY:No date
END:VEVENT
END:VCALENDAR
"""


class IcsTests(unittest.TestCase):
    def test_parses_summary_and_date_and_unfolds_lines(self):
        events = parse_events(ICS_SAMPLE)
        titles = [e["title"] for e in events]
        self.assertIn("Research proposal, draft due", titles)
        self.assertIn("Long folded title", titles)
        self.assertNotIn("No date", titles)
        self.assertIn({"title": "Research proposal, draft due", "date": "2099-12-01"}, events)

    def test_empty_input_gives_no_events(self):
        self.assertEqual(parse_events(""), [])

    def test_first_step_is_smaller_when_mood_is_heavy(self):
        self.assertIn("5 minutes", suggested_first_step("Essay", "high", "anxious"))
        self.assertIn("25 minutes", suggested_first_step("Essay", "high", "happy"))


class ChatAndPriorityTests(ApiTestBase):
    def test_chat_name_is_stable_across_rooms_and_can_be_changed(self):
        t, user = self.signup("nameful_1")
        _, a = self.call("POST", "/api/rooms/stress-relief/join", token=t)
        _, b = self.call("POST", "/api/rooms/gratitude-circle/join", token=t)
        self.assertEqual(a["chat_name"], b["chat_name"])
        self.assertEqual(a["chat_name"], user["chat_name"])
        status, data = self.call("POST", "/api/auth/profile", {"chat_name": "Sunny Otter"}, token=t)
        self.assertEqual(status, 200)
        self.assertEqual(data["user"]["chat_name"], "Sunny Otter")
        self.assertEqual(data["user"]["display_name"], "Test User")

    def test_chat_name_must_be_unique(self):
        t1, _ = self.signup("unique_a")
        t2, _ = self.signup("unique_b")
        self.call("POST", "/api/auth/profile", {"chat_name": "Shared Name"}, token=t1)
        status, _ = self.call("POST", "/api/auth/profile", {"chat_name": "shared name"}, token=t2)
        self.assertEqual(status, 409)

    def test_chat_shows_new_name_on_old_messages(self):
        t, _ = self.signup("renamed_1")
        self.call("POST", "/api/rooms/youre-not-alone/join", token=t)
        self.call("POST", "/api/rooms/youre-not-alone/messages", {"text": "hello"}, token=t)
        self.call("POST", "/api/auth/profile", {"chat_name": "New Chat Name"}, token=t)
        _, feed = self.call("GET", "/api/rooms/youre-not-alone/messages?since=0", token=t)
        self.assertEqual(feed["messages"][0]["author"], "New Chat Name")

    def test_members_list_shows_online_status(self):
        t1, _ = self.signup("online_a")
        t2, _ = self.signup("online_b")
        self.call("POST", "/api/rooms/anxiety-support/join", token=t1)
        self.call("POST", "/api/rooms/anxiety-support/join", token=t2)
        _, feed = self.call("GET", "/api/rooms/anxiety-support/messages?since=0", token=t1)
        self.assertEqual(len(feed["members"]), 2)
        self.assertTrue(all(m["online"] for m in feed["members"]))
        self.assertTrue(any(m["mine"] for m in feed["members"]))
        self.assertTrue(all("username" not in m for m in feed["members"]))  # hidden from members

    def test_moderator_can_monitor_room_without_joining_and_sees_usernames(self):
        t1, _ = self.signup("monitored_1")
        self.call("POST", "/api/rooms/mindfulness-circle/join", token=t1)
        self.call("POST", "/api/rooms/mindfulness-circle/messages", {"text": "Hello room"}, token=t1)
        mod = self.mod_token()
        status, feed = self.call("GET", "/api/rooms/mindfulness-circle/messages?since=0", token=mod)
        self.assertEqual(status, 200)
        self.assertEqual(feed["messages"][0]["username"], "monitored_1")
        status, detail = self.call("GET", "/api/mod/rooms/mindfulness-circle", token=mod)
        self.assertEqual(status, 200)
        self.assertEqual(detail["members"][0]["username"], "monitored_1")

    def test_moderator_cannot_post_as_a_member(self):
        mod = self.mod_token()
        self.call("POST", "/api/rooms/mindfulness-circle/join", token=mod)
        status, _ = self.call("POST", "/api/rooms/mindfulness-circle/messages", {"text": "hi"}, token=mod)
        self.assertEqual(status, 403)

    def test_moderator_announcement_is_visible_to_members(self):
        t, _ = self.signup("listener_1")
        self.call("POST", "/api/rooms/rest-recovery/join", token=t)
        mod = self.mod_token()
        status, _ = self.call("POST", "/api/mod/rooms/rest-recovery/announce",
                              {"text": "Reminder: be kind to each other."}, token=mod)
        self.assertEqual(status, 200)
        _, feed = self.call("GET", "/api/rooms/rest-recovery/messages?since=0", token=t)
        ann = feed["messages"][-1]
        self.assertEqual(ann["role"], "announcement")
        self.assertEqual(ann["author"], "Moderator")

    def test_members_cannot_announce(self):
        t, _ = self.signup("nosy_1")
        self.assertEqual(self.call("POST", "/api/mod/rooms/rest-recovery/announce", {"text": "x"}, token=t)[0], 403)

    def test_checkin_includes_top_priority_and_question(self):
        t, _ = self.signup("priority_1")
        self.call("POST", "/api/tasks", {"title": "Prepare proposal draft", "deadline": "2099-06-01"}, token=t)
        _, data = self.call("POST", "/api/checkin", {"mood": "anxious", "energy": "low", "need": "focus"}, token=t)
        self.assertIsNotNone(data["priority"])
        self.assertEqual(data["priority"]["task"]["title"], "Prepare proposal draft")
        self.assertIn("Prepare proposal draft", data["priority"]["question"])
        self.assertIn("5 minutes", data["priority"]["first_step"])

    def test_checkin_without_tasks_has_no_priority(self):
        t, _ = self.signup("priority_2")
        _, data = self.call("POST", "/api/checkin", {"mood": "calm", "energy": "medium", "need": "relax"}, token=t)
        self.assertIsNone(data["priority"])

    def test_calendar_import_creates_future_tasks_and_skips_duplicates(self):
        t, _ = self.signup("calendar_1")
        status, first = self.call("POST", "/api/tasks/import-ics", {"ics": ICS_SAMPLE}, token=t)
        self.assertEqual(status, 200)
        self.assertEqual(first["imported"], 2)  # the two future events; the 2000 event is skipped
        _, again = self.call("POST", "/api/tasks/import-ics", {"ics": ICS_SAMPLE}, token=t)
        self.assertEqual(again["imported"], 0)
        _, tasks = self.call("GET", "/api/tasks", token=t)
        self.assertTrue(all(task["source"] == "calendar" for task in tasks["tasks"]))
        self.assertEqual(tasks["priority"]["deadline"], "2099-10-15")

    def test_calendar_import_rejects_empty_file(self):
        t, _ = self.signup("calendar_2")
        self.assertEqual(self.call("POST", "/api/tasks/import-ics", {"ics": "hello"}, token=t)[0], 400)


class PersistenceTests(unittest.TestCase):
    def test_accounts_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "data.json")
            store = Store(path)
            server.STORE = store
            server.ensure_moderator(store)
            store.save()
            with store.lock:
                uid = "persist-test-id"
                salt, h = hash_password(PW)
                store.data["users"][uid] = {"id": uid, "username": "persisted", "display_name": "P",
                                            "role": "member", "status": "active", "salt": salt,
                                            "pw_hash": h, "created": "x", "consent": {}, "last_suggested": []}
                store.data["usernames"]["persisted"] = uid
            store.save()
            reloaded = Store(path)
            self.assertIn("persisted", reloaded.data["usernames"])
            self.assertIn("moderator", reloaded.data["usernames"])
            self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
