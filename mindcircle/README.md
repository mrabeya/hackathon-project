# MindCircle: Hackathon Prototype (v3)

MindCircle is a mental wellness and peer-support prototype. Members sign up, check in each day, get suggestions chosen for their mood, see their top priority, chat with others in mood-based groups, and track tasks. Moderators watch the chats, handle flagged content, and monitor accounts.

> **Not a replacement for therapy, medical care, or emergency services.** This is a demo. It has not been clinically validated or reviewed by a safety team. Read [Before any real launch](#before-any-real-launch) first.

---

## What's included

| Feature | How it works |
|---|---|
| **Sign up and log in** | Username, your name, password (8+ characters), 18+ confirmation, and consent to message screening. Passwords are hashed. Logins lock for 15 minutes after 5 failed attempts. |
| **Stable names** | Your **name** (for your account) and your **chat name** (shown in groups) are separate. Your chat name is created once, stays the same in every room, and can be changed under **Account**. The header always shows both. |
| **Daily check-in** | Mood, energy, and "what would help?" Private. Reminder banner at 09:00 by default. |
| **Priority after check-in** | Your top open task appears right after check-in, with a question, a first step sized to your mood and energy, and a "Mark done" button. |
| **Calendar import** | Upload an `.ics` file exported from Google Calendar, Outlook, or Apple Calendar. Upcoming events become tasks with their dates. Duplicates are skipped. Manual tasks are supported too. |
| **Personalised suggestions** | Each mood has its own message and activities. Energy, your "I want to" choice, and your feedback change the ranking. Each suggestion explains why it was picked. |
| **Real group chat** | Message bubbles (yours on the right), chat names, times, a live member list with online dots, and messages every 1.5 seconds. Several people can talk at once. |
| **Safety screening** | Every message is checked. Serious messages are held and the author sees crisis resources. Imminent or threat messages pause the room for everyone. |
| **Moderator monitor** | Choose any room and see the full conversation with **usernames**, the member list, open flags, and a box to post announcements. Moderators can watch a room without joining it. |
| **Moderator safety queue** | Release, confirm, or dismiss held messages and reports. Reopen paused rooms. |
| **Account monitoring** | Account list with message counts, held messages, and flags. Suspend or reactivate member accounts. Full audit log. |
| **Crisis resources** | US: 988 (call or text) and 911 for immediate danger. Other countries show a placeholder until verified numbers are added. |

### What moderators can and cannot see

Moderators can see: usernames, names, account status, message counts, chat messages (with usernames), member lists, flagged items, and the audit log.

Moderators **cannot** see: check-ins, moods, energy levels, activity feedback, or tasks. These are never returned to moderators. A test checks this.

Members see each other by chat name only. Usernames are visible to moderators only.

---

## Quick start

Requires **Python 3.9+**. There are no third-party packages.

```bash
cd mindcircle
python3 server.py
```

Open **http://127.0.0.1:8000**.

### Set the moderator login before real use

The server creates a moderator account on first start:

| Setting | Default |
|---|---|
| Username | `moderator` (override with `MOD_USERNAME`) |
| Password | `change-me-now` (override with `MOD_PASSWORD`) |

The server prints a warning while the default password is in use:

```bash
MOD_USERNAME=safety_lead MOD_PASSWORD="a-long-unique-passphrase" python3 server.py
```

To change the password later, log in as the moderator and use **Account → Change password**.

### Run the tests

```bash
python3 -m unittest discover -s tests -v
```

There are 67 tests. They cover safety rules, suggestion personalisation, sign-up and login rules, lockout, suspensions, group chat between several users, chat names, the moderator monitor and announcements, moderator privacy, calendar parsing and import, check-in priority, and data persistence.

---

## Demo walkthrough (about 4 minutes)

Use two browser windows (one normal, one private) for two members, and a third for the moderator.

1. **Sign up** `ann_demo` and `ben_demo`. Note the chat names shown in the header.
2. **Priorities (Ann):** add a task with a deadline, or import an `.ics` file.
3. **Check-in (Ann):** choose "Anxious", energy "Low", and "Focus". Your priority appears with a first step. Mark one suggestion "Helpful".
4. **Community (Ann and Ben):** both open *Anxiety Support*. They see each other in the member list and chat in bubbles.
5. **Safety (Ben):** Ben posts "I want to die". The message is held, and only Ben sees the crisis resources.
6. **Red flag (Ann):** Ann posts "I'm going to end my life tonight". The room pauses for everyone.
7. **Moderator:** log in as `moderator`. Open **Moderator**. In the chat monitor, pick the room and see usernames beside chat names. Post an announcement. Release, confirm, or dismiss the queued messages. Reopen the room. Check the audit log.

---

## Project structure

```
mindcircle/
├── server.py        # HTTP server, routes, sessions, chat, moderator tools
├── auth.py          # Password hashing, sign-up and chat-name validation, tokens
├── store.py         # JSON file storage (atomic writes)
├── recommend.py     # Personalised suggestion scoring and mood messages
├── ics.py           # Calendar (.ics) reader for priority tasks
├── content.py       # Moods, mood profiles, activities, rooms, crisis resources
├── safety.py        # Rule-based message screening (levels 0 to 4)
├── static/
│   ├── index.html   # Login, sign-up, member app, moderator dashboard
│   ├── app.js       # Front end (no build step; server text is inserted with textContent)
│   └── style.css
├── tests/
│   └── test_app.py  # 67 unit and API tests
└── README.md
```

---

## API reference

All routes except sign-up, log-in, and crisis resources need `Authorization: Bearer <token>`. Bodies and responses are JSON.

**Accounts**

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/signup` | Create a member account. Returns a token. |
| POST | `/api/auth/login` | Log in. Returns a token. |
| POST | `/api/auth/logout` | End the current session. |
| GET | `/api/auth/me` | Current user. |
| POST | `/api/auth/profile` | `{"display_name": "...", "chat_name": "..."}` (either or both). |
| POST | `/api/auth/password` | Change password. Other sessions are signed out. |

**Member**

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/checkin` | Save a check-in. Returns mood message, activities, suggested room, and top priority. |
| GET | `/api/activities?mood=&energy=&need=` | Personalised activities. |
| POST | `/api/activities/{id}/feedback` | `{"helpful": true\|false}` |
| GET | `/api/rooms?mood=` | List rooms. |
| POST | `/api/rooms/{id}/join` | Join a room. Returns your chat name. |
| GET | `/api/rooms/{id}/messages?since=` | Read messages, members, and room status (members only). |
| POST | `/api/rooms/{id}/messages` | Post a message (screened first). |
| POST | `/api/rooms/{id}/report` | Report a message. |
| GET / POST | `/api/tasks` | List or add tasks. |
| POST | `/api/tasks/import-ics` | `{"ics": "<file text>"}`: import upcoming calendar events. |
| POST | `/api/tasks/{id}/done` | Complete a task. |
| GET | `/api/crisis?country=US` | Crisis and emergency resources (public). |

**Moderator** (moderator role only)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/mod/queue` | Open safety queue and paused rooms. |
| POST | `/api/mod/queue/{id}/resolve` | `{"action": "release" \| "confirm" \| "dismiss"}` |
| POST | `/api/mod/rooms/{id}/clear` | Reopen a paused room. |
| GET | `/api/mod/rooms/{id}` | Chat monitor: messages with usernames, members, and open flags. |
| POST | `/api/mod/rooms/{id}/announce` | `{"text": "..."}`: post an announcement to the room. |
| GET | `/api/mod/users` | Account list with activity counts (no mood data). |
| POST | `/api/mod/users/{id}/status` | `{"status": "active" \| "suspended"}`. Member accounts only. |
| GET | `/api/mod/audit` | Recent moderator and account actions. |

---

## How the features work

**Suggestions.** For each check-in the server keeps only activities written for your mood, then scores them. Points go to: fits your energy (short activities favoured on low energy), matches what you want (relax, talk, or focus), you found it helpful, or it is a type you have liked. Activities you marked "Not for me" and those in your last few suggestions are lowered. Everything is rule-based and explainable, with no machine-learning model.

**Priority and calendar.** The top open task is the one with the earliest deadline. Its first step is shortened when your mood is heavy (anxious, stressed, exhausted, sad, lonely) or your energy is low. Calendar import reads `SUMMARY` and `DTSTART` from each event. It skips past events and events already imported. It does not handle repeating events, so import each occurrence you need or use manual tasks for recurring ones.

**Chat.** Each member has one chat name. Messages store the author's account, and the chat name is looked up when the message is shown, so a renamed member appears with the new name everywhere. The room is refreshed every 1.5 seconds, and online status is based on activity in the last 20 seconds. The message route rejects posts from moderators. Moderators announce through their own route, which labels the message "Moderator".

**Monitoring and safety.** Every message is screened. Held messages go to the safety queue with the username attached, and are not shown to other members until a moderator releases them. A red-flagged room blocks posting for everyone until a moderator reopens it. Member reports also go to the queue.

---

## Safety design

| Level | Name | Example | Action |
|---|---|---|---|
| 0 | Normal | "Had a nice walk" | Post |
| 1 | Distress | "I feel anxious about my exam" | Post, show a support tip |
| 2 | Concerning | "I feel hopeless lately" | Post, add to moderator review |
| 3 | Serious | "I want to die", threats, crime planning | **Hold.** Show crisis panel to author. Queue for moderator. |
| 4 | Imminent | Self-harm with a time or means | **Hold.** Show crisis panel. Pause the room. Queue for moderator. |

- **Context guard:** third-person educational wording (for example, "suicide prevention article") is lowered by one level. First-person intent is never lowered. Crime and threat categories are never lowered.
- **No automatic police reporting.** The app does not call 911, contact police, or reveal identities to other members. Moderators decide what happens next, under your approved process and local law.

### Limitations

- Phrase rules miss paraphrases, misspellings, slang, other languages, and coded language. They also flag innocent messages, such as song lyrics or quotes.
- The levels are proposed operational categories, not clinical standards.
- Tests check that the rules behave as described. They do not measure real-world accuracy. Measure precision, recall, and false-negative rates on clinician-reviewed data before launch.

---

## Deploying online

The data lives in one JSON file, so the host needs persistent disk storage.

1. Put the project in a GitHub repository.
2. Create a web service on a host with persistent disks (for example Render or Railway). Set the start command to `python3 server.py`.
3. Set `PORT` if the host requires it, `DATA_FILE` to a path on the persistent disk, and `MOD_USERNAME` and `MOD_PASSWORD` to your own values.
4. The server listens on `127.0.0.1` by default. For hosted use, change `make_server("127.0.0.1", ...)` to `"0.0.0.0"` in `server.py`.

Use HTTPS in production. Hosts usually provide it.

---

## Before any real launch

This is still a prototype. A real product would also need:

1. **A real database** (PostgreSQL or a managed service). The JSON file does not suit many users or backups.
2. **Secure cookies and HTTPS**, with tokens moved from localStorage to HttpOnly cookies, and CSRF protection.
3. **Verified crisis numbers** for each country you support. Check official sources. The "Other" entry is a placeholder.
4. **Trained moderators with 24/7 cover**, or a clear fallback when none are available.
5. **Clinical and legal review** of the safety levels, moderation process, and reporting duties in each jurisdiction.
6. **Better screening** (for example, a fine-tuned model) measured on protected data, with humans kept in the loop.
7. **Encryption and access controls** for held messages and check-ins. Limit who reads the audit log, and set retention periods.
8. **Email verification and password reset**, with stronger rate limiting than the per-username lockout here.
9. **Privacy and consent:** data export, account deletion, and clear notice of screening.
10. **Adults only**, unless the design is reviewed for minors.
11. **Accessibility testing** and localisation.
12. **Real-time transport** (WebSockets or a managed chat service) instead of polling.

---

## Notes

- The spec gives 988 as the US crisis line and 911 for emergencies. The app shows those for the US. Confirm the correct numbers for every country you support.
- Video suggestions link to YouTube search results. Replace them with reviewed video IDs before launch.
- Calendar import is one-off file upload. Live sync needs OAuth with Google or Microsoft, which is the next step.

## License

Hackathon prototype. Add a license before sharing publicly.
