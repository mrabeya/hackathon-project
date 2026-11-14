// MindCircle front end. Plain JavaScript, no build step.
// All server-provided text is inserted with textContent, never innerHTML.

const $ = (sel) => document.querySelector(sel);

const MOODS = [
  { key: "happy", label: "Happy", emoji: "😊" },
  { key: "calm", label: "Calm", emoji: "😌" },
  { key: "anxious", label: "Anxious", emoji: "😟" },
  { key: "sad", label: "Sad", emoji: "😔" },
  { key: "stressed", label: "Stressed", emoji: "😤" },
  { key: "lonely", label: "Lonely", emoji: "🫂" },
  { key: "exhausted", label: "Exhausted", emoji: "😴" },
];

const CHAT_POLL_MS = 1500;
const MONITOR_POLL_MS = 2500;

const state = {
  token: localStorage.getItem("mc_token") || "",
  user: null,
  mood: null,
  room: null,          // room the member is chatting in
  chatTimer: null,
  monitorTimer: null,
  monitorRoom: null,
  lastSeen: 0,
  seenIds: new Set(),
};

// ---------- Networking and helpers ----------

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  const init = { method: opts.method || "GET", headers };
  if (opts.body !== undefined) init.body = JSON.stringify(opts.body);
  const res = await fetch(path, init);
  let data = {};
  try { data = await res.json(); } catch (_) { /* empty body */ }
  if (!res.ok) {
    const err = new Error(data.error || "Request failed.");
    err.status = res.status;
    if (res.status === 401 && path !== "/api/auth/login") logout(true);
    throw err;
  }
  return data;
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c);
  return node;
}

function setError(id, msg) {
  const box = $(id);
  box.textContent = msg || "";
  box.classList.toggle("hidden", !msg);
}

function formatTime(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// ---------- Auth ----------

function showAuthTab(which) {
  const login = which === "login";
  $("#login-form").classList.toggle("hidden", !login);
  $("#signup-form").classList.toggle("hidden", login);
  $("#show-login").classList.toggle("active", login);
  $("#show-signup").classList.toggle("active", !login);
}

function startSession(token, user) {
  state.token = token;
  state.user = user;
  localStorage.setItem("mc_token", token);
  $("#auth-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  renderIdentity();
  document.querySelectorAll(".mod-only").forEach((b) => b.classList.toggle("hidden", user.role !== "moderator"));
  showTab("checkin");
}

function renderIdentity() {
  const u = state.user;
  $("#whoami").textContent = `${u.display_name} · chat name: ${u.chat_name || "not set"}`;
  $("#account-info").textContent = `Account: @${u.username} · Role: ${u.role}`;
  $("#profile-display").value = u.display_name;
  $("#profile-chat").value = u.chat_name || "";
}

async function login(e) {
  e.preventDefault();
  setError("#login-error", "");
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: { username: $("#login-username").value.trim(), password: $("#login-password").value },
    });
    $("#login-password").value = "";
    startSession(data.token, data.user);
  } catch (err) {
    setError("#login-error", err.message);
  }
}

async function signup(e) {
  e.preventDefault();
  setError("#signup-error", "");
  const body = {
    username: $("#signup-username").value.trim(),
    display_name: $("#signup-display").value.trim(),
    password: $("#signup-password").value,
    confirm: $("#signup-confirm").value,
    adult: $("#signup-adult").checked,
    consent: $("#signup-consent").checked,
  };
  try {
    const data = await api("/api/auth/signup", { method: "POST", body });
    startSession(data.token, data.user);
  } catch (err) {
    setError("#signup-error", err.message);
  }
}

async function logout(silent = false) {
  stopChat();
  stopMonitor();
  if (state.token && !silent) {
    try { await api("/api/auth/logout", { method: "POST" }); } catch (_) { /* ignore */ }
  }
  state.token = "";
  state.user = null;
  localStorage.removeItem("mc_token");
  $("#app-view").classList.add("hidden");
  $("#auth-view").classList.remove("hidden");
  if (silent) setError("#login-error", "Your session has ended. Please log in again.");
}

async function restoreSession() {
  if (!state.token) return;
  try {
    const data = await api("/api/auth/me");
    startSession(state.token, data.user);
  } catch (_) {
    logout(true);
  }
}

// ---------- Tabs ----------

function showTab(name) {
  document.querySelectorAll(".panel").forEach((p) => p.classList.add("hidden"));
  $("#tab-" + name).classList.remove("hidden");
  document.querySelectorAll(".tab[data-tab]").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  if (name !== "communities") stopChat();
  if (name !== "mod") stopMonitor();
  if (name === "activities") loadActivities();
  if (name === "communities") loadRooms();
  if (name === "tasks") loadTasks();
  if (name === "crisis") loadCrisis();
  if (name === "mod") {
    loadModDashboard();
    startMonitor();
  }
}

// ---------- Check-in and suggestions ----------

function renderMoods() {
  const wrap = $("#mood-buttons");
  MOODS.forEach((m) => {
    const btn = el("button", { class: "mood-btn", type: "button", "aria-pressed": "false" }, [
      el("span", { class: "emoji", "aria-hidden": "true", text: m.emoji }),
      document.createTextNode(m.label),
    ]);
    btn.addEventListener("click", () => {
      state.mood = m.key;
      wrap.querySelectorAll(".mood-btn").forEach((b) => {
        b.classList.toggle("selected", b === btn);
        b.setAttribute("aria-pressed", String(b === btn));
      });
    });
    wrap.append(btn);
  });
  MOODS.forEach((m) => $("#act-mood").append(el("option", { value: m.key, text: m.label })));
}

function activityCard(act) {
  const children = [
    el("h3", { text: act.title }),
    el("p", { class: "meta", text: `${act.minutes} min · ${act.type}` }),
    el("p", { text: act.description }),
  ];
  if (act.why) children.push(el("p", { class: "why", text: act.why }));
  if (act.url) {
    children.push(el("p", {}, [el("a", { href: act.url, target: "_blank", rel: "noopener noreferrer", text: "Find a video (YouTube search)" })]));
  }
  children.push(el("div", { class: "row vote" }, [
    feedbackButton(act.id, true, "Helpful"),
    feedbackButton(act.id, false, "Not for me"),
  ]));
  return el("div", { class: "card" }, children);
}

function feedbackButton(activityId, helpful, label) {
  const btn = el("button", { class: "secondary", type: "button", text: label });
  btn.addEventListener("click", async () => {
    try {
      await api(`/api/activities/${activityId}/feedback`, { method: "POST", body: { helpful } });
      btn.textContent = helpful ? "Thanks, noted" : "Got it";
      btn.parentElement.querySelectorAll("button").forEach((b) => (b.disabled = true));
    } catch (e) {
      alert(e.message);
    }
  });
  return btn;
}

function priorityCard(priority, energyForStep) {
  const card = el("div", { class: "card priority" }, [
    el("h3", { text: "Your priority today" }),
    el("p", { text: priority.question }),
    el("p", { class: "meta", text: priority.task.deadline ? `Deadline: ${priority.task.deadline}` : "No deadline set" }),
    el("p", { text: "Suggested first step: " + priority.first_step }),
  ]);
  const done = el("button", { class: "secondary", type: "button", text: "Mark done" });
  done.addEventListener("click", async () => {
    await api(`/api/tasks/${priority.task.id}/done`, { method: "POST" });
    card.replaceChildren(el("p", { text: "Nice work. Marked as done." }));
  });
  const addMore = el("button", { class: "secondary", type: "button", text: "See all priorities" });
  addMore.addEventListener("click", () => showTab("tasks"));
  card.append(el("div", { class: "row" }, [done, addMore]));
  return card;
}

async function submitCheckin() {
  if (!state.mood) {
    alert("Pick a mood first, or browse activities instead.");
    return;
  }
  const btn = $("#checkin-submit");
  btn.disabled = true;
  try {
    const data = await api("/api/checkin", {
      method: "POST",
      body: { mood: state.mood, energy: $("#energy").value, need: $("#need").value },
    });
    const box = $("#checkin-result");
    box.replaceChildren();
    box.classList.remove("hidden");
    box.append(el("p", { class: "message-lead", text: data.message }));

    if (data.priority) {
      box.append(priorityCard(data.priority, $("#energy").value));
    } else {
      const add = el("button", { class: "secondary", type: "button", text: "Add a priority or import calendar" });
      add.addEventListener("click", () => showTab("tasks"));
      box.append(el("div", { class: "card" }, [
        el("h3", { text: "No priority set yet" }),
        el("p", { text: "Add a task or import your calendar, and your next priority will appear here after each check-in." }),
        add,
      ]));
    }

    const roomBtn = el("button", { class: "primary", type: "button", text: "Open community for this mood" });
    roomBtn.addEventListener("click", () => openRoom(data.suggested_room));
    box.append(el("div", { class: "card" }, [
      el("h3", { text: "Community room" }),
      el("p", { text: "Read and join when you are ready. Joining is optional." }),
      roomBtn,
    ]));

    box.append(el("h3", { text: "Suggested for you" }));
    const cards = el("div", { class: "cards" });
    data.activities.forEach((a) => cards.append(activityCard(a)));
    box.append(cards);
  } catch (e) {
    alert(e.message);
  } finally {
    btn.disabled = false;
  }
}

async function loadActivities() {
  const mood = $("#act-mood").value;
  const qs = new URLSearchParams({ energy: $("#act-energy").value, need: $("#act-need").value });
  if (mood) qs.set("mood", mood);
  const data = await api("/api/activities?" + qs.toString());
  $("#act-message").textContent = data.message;
  $("#activity-list").replaceChildren(...data.activities.map(activityCard));
}

// ---------- Community chat (members) ----------

async function loadRooms() {
  $("#room-list-view").classList.remove("hidden");
  $("#room-view").classList.add("hidden");
  const data = await api("/api/rooms");
  const list = $("#room-list");
  list.replaceChildren();
  data.rooms.forEach((r) => {
    const btn = el("button", { class: "primary", type: "button", text: "Open chat" });
    btn.addEventListener("click", () => openRoom(r.id));
    list.append(el("div", { class: "card" }, [
      el("h3", { text: r.name }),
      el("p", { text: r.description }),
      el("p", { class: "meta", text: `${r.members} joined${r.status === "red_flag" ? " · paused for review" : ""}` }),
      btn,
    ]));
  });
}

async function openRoom(roomId) {
  stopChat();
  showTab("communities");
  $("#room-list-view").classList.add("hidden");
  $("#room-view").classList.remove("hidden");
  $("#messages").replaceChildren();
  $("#message-feedback").classList.add("hidden");
  state.seenIds.clear();
  state.lastSeen = 0;
  try {
    const joined = await api(`/api/rooms/${roomId}/join`, { method: "POST" });
    state.room = joined.room;
    $("#room-title").textContent = joined.room.name;
    $("#room-desc").textContent = joined.room.description;
    const isMod = state.user.role === "moderator";
    $("#chat-note").textContent = isMod
      ? "You are viewing this room as a moderator. Use the Moderator tab to post announcements."
      : `You are chatting as ${joined.chat_name}. Change it under Account.`;
    $("#message-form").classList.toggle("hidden", isMod);
    startChat();
  } catch (e) {
    alert(e.message);
    loadRooms();
  }
}

function startChat() {
  pollChat();
  state.chatTimer = setInterval(pollChat, CHAT_POLL_MS);
}

function stopChat() {
  if (state.chatTimer) clearInterval(state.chatTimer);
  state.chatTimer = null;
  state.room = null;
}

function renderMembers(list, members, showUsernames) {
  list.replaceChildren();
  members.forEach((m) => {
    const dot = el("span", { class: "dot " + (m.online ? "on" : "off"), "aria-label": m.online ? "online" : "offline" });
    const label = el("span", { text: m.name + (m.mine ? " (you)" : "") });
    const li = el("li", {}, [dot, label]);
    if (showUsernames && m.username) li.append(el("span", { class: "small muted", text: ` @${m.username}` }));
    list.append(li);
  });
  if (!members.length) list.append(el("li", { class: "muted small", text: "No one has joined yet." }));
}

function buildBubble(m, showUsername, canReport) {
  const cls = m.role === "announcement" ? "bubble announce" : (m.mine ? "bubble mine" : "bubble theirs");
  const head = el("div", { class: "bubble-head" }, [
    el("span", { class: "who", text: m.author }),
    el("span", { class: "time", text: " " + formatTime(m.ts) }),
  ]);
  if (showUsername && m.username) head.append(el("span", { class: "small muted", text: ` · @${m.username}` }));
  const children = [head, el("div", { class: "text", text: m.text })];
  if (canReport && !m.mine && m.role === "member") {
    const report = el("button", { class: "link", type: "button", text: "Report" });
    report.addEventListener("click", () => reportMessage(m.id));
    children.push(report);
  }
  return el("div", { class: cls }, children);
}

function appendMessages(box, messages, showUsername, canReport) {
  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
  messages.forEach((m) => {
    if (state.seenIds.has(m.id)) return;
    state.seenIds.add(m.id);
    box.append(buildBubble(m, showUsername, canReport));
    if (m.ts_epoch) state.lastSeen = Math.max(state.lastSeen, m.ts_epoch);
  });
  if (messages.length && (nearBottom || messages.some((m) => m.mine))) box.scrollTop = box.scrollHeight;
}

async function pollChat() {
  if (!state.room) return;
  try {
    const data = await api(`/api/rooms/${state.room.id}/messages?since=${state.lastSeen}`);
    const paused = data.status === "red_flag";
    $("#room-banner").classList.toggle("hidden", !paused);
    $("#message-form").querySelector("button").disabled = paused;
    renderMembers($("#member-list"), data.members, false);
    appendMessages($("#messages"), data.messages, false, true);
  } catch (_) { /* retry on next tick */ }
}

function setFeedback(text, alertStyle = false) {
  const box = $("#message-feedback");
  box.textContent = text;
  box.classList.toggle("alert", alertStyle);
  box.classList.remove("hidden");
}

async function sendMessage(e) {
  e.preventDefault();
  const input = $("#message-input");
  const text = input.value.trim();
  if (!text || !state.room) return;
  try {
    const res = await api(`/api/rooms/${state.room.id}/messages`, { method: "POST", body: { text } });
    input.value = "";
    if (res.status === "held") {
      setFeedback(res.message, true);
      if (res.show_crisis && res.crisis) renderCrisisInline(res.crisis);
    } else {
      if (res.message) appendMessages($("#messages"), [res.message], false, true);
      if (res.support_tip) setFeedback(res.support_tip);
      else $("#message-feedback").classList.add("hidden");
    }
    pollChat();
  } catch (err) {
    setFeedback(err.message, err.status === 423);
  }
}

function renderCrisisInline(crisis) {
  const box = $("#message-feedback");
  box.append(el("p", { text: "If you are in danger or thinking about ending your life, please reach out now:" }));
  crisis.crisis.forEach((c) => box.append(el("p", { text: `${c.label}: ${c.action}` })));
  box.append(el("p", { text: `${crisis.emergency.label}: ${crisis.emergency.action}` }));
}

async function reportMessage(messageId) {
  try {
    await api(`/api/rooms/${state.room.id}/report`, {
      method: "POST", body: { message_id: messageId, reason: "Reported by member" },
    });
    setFeedback("Thanks. A moderator will review this message.");
  } catch (e) {
    setFeedback(e.message, true);
  }
}

// ---------- Priorities and calendar ----------

async function loadTasks() {
  const data = await api("/api/tasks?energy=" + $("#energy").value);
  const card = $("#priority-card");
  if (data.priority) {
    card.className = "card priority";
    card.replaceChildren(
      el("h3", { text: "Focus for now" }),
      el("p", { text: data.priority.title }),
      el("p", { class: "meta", text: data.priority.deadline ? `Deadline: ${data.priority.deadline}` : "No deadline set" }),
      el("p", { text: "Suggested first step: " + data.suggested_first_step }),
    );
  } else {
    card.className = "card hidden";
    card.replaceChildren();
  }
  const list = $("#task-list");
  list.replaceChildren();
  data.tasks.forEach((t) => {
    const done = el("button", { class: "secondary", type: "button", text: "Mark done" });
    done.addEventListener("click", async () => {
      await api(`/api/tasks/${t.id}/done`, { method: "POST" });
      loadTasks();
    });
    const label = `${t.title}${t.deadline ? ` (due ${t.deadline})` : ""}`;
    list.append(el("li", {}, [
      el("span", { class: "t" }, [
        document.createTextNode(label),
        el("span", { class: "tag", text: t.source === "calendar" ? " calendar" : " manual" }),
      ]),
      done,
    ]));
  });
  if (!data.tasks.length) list.append(el("li", { class: "muted", text: "No open tasks yet. Add one or import your calendar." }));
}

async function addTask(e) {
  e.preventDefault();
  const title = $("#task-title").value.trim();
  const deadline = $("#task-deadline").value || null;
  if (!title) return;
  try {
    await api("/api/tasks", { method: "POST", body: { title, deadline } });
    $("#task-title").value = "";
    $("#task-deadline").value = "";
    loadTasks();
  } catch (err) {
    alert(err.message);
  }
}

async function importCalendar() {
  const file = $("#ics-file").files[0];
  const msg = $("#ics-msg");
  if (!file) {
    msg.className = "small error";
    msg.textContent = "Choose an .ics file first.";
    return;
  }
  try {
    const ics = await file.text();
    const data = await api("/api/tasks/import-ics", { method: "POST", body: { ics } });
    msg.className = "small success";
    msg.textContent = `Imported ${data.imported} upcoming event(s). ${data.skipped} were past or already added.`;
    loadTasks();
  } catch (err) {
    msg.className = "small error";
    msg.textContent = err.message;
  }
}

// ---------- Crisis ----------

async function loadCrisis() {
  const data = await api("/api/crisis?country=" + $("#crisis-country").value);
  const panel = $("#crisis-panel");
  panel.replaceChildren();
  data.crisis.forEach((c) => panel.append(el("div", { class: "card" }, [
    el("h3", { text: c.label }), el("p", { text: c.action }),
  ])));
  panel.append(el("div", { class: "card" }, [
    el("h3", { text: data.emergency.label }), el("p", { text: data.emergency.action }),
  ]));
  if (data.note) panel.append(el("p", { class: "muted small", text: data.note }));
}

// ---------- Account ----------

async function saveProfile(e) {
  e.preventDefault();
  const msg = $("#profile-msg");
  try {
    const data = await api("/api/auth/profile", {
      method: "POST",
      body: { display_name: $("#profile-display").value.trim(), chat_name: $("#profile-chat").value.trim() },
    });
    state.user = { ...state.user, ...data.user };
    renderIdentity();
    msg.className = "small success";
    msg.textContent = "Saved. Your new chat name appears on your past messages too.";
  } catch (err) {
    msg.className = "small error";
    msg.textContent = err.message;
  }
}

async function changePassword(e) {
  e.preventDefault();
  const msg = $("#pw-msg");
  try {
    await api("/api/auth/password", {
      method: "POST",
      body: { current: $("#pw-current").value, new: $("#pw-new").value },
    });
    msg.className = "small success";
    msg.textContent = "Password updated. Other sessions were signed out.";
    $("#pw-current").value = "";
    $("#pw-new").value = "";
  } catch (err) {
    msg.className = "small error";
    msg.textContent = err.message;
  }
}

// ---------- Moderator dashboard ----------

async function loadModDashboard() {
  try {
    const [queue, users, audit] = await Promise.all([
      api("/api/mod/queue"), api("/api/mod/users"), api("/api/mod/audit"),
    ]);
    renderModRooms(queue.red_flag_rooms);
    renderModQueue(queue.queue);
    renderModUsers(users.users);
    renderModAudit(audit.audit);
    await refreshMonitorRoomList();
  } catch (e) {
    alert(e.message);
  }
}

function renderModRooms(rooms) {
  const box = $("#mod-rooms");
  box.replaceChildren();
  if (!rooms.length) return;
  box.append(el("p", { class: "banner warn", text: "Red-flagged rooms: " + rooms.map((r) => r.name).join(", ") }));
  rooms.forEach((r) => {
    const btn = el("button", { class: "primary", type: "button", text: `Reopen ${r.name}` });
    btn.addEventListener("click", async () => {
      await api(`/api/mod/rooms/${r.id}/clear`, { method: "POST" });
      loadModDashboard();
    });
    box.append(btn);
  });
}

function renderModQueue(items) {
  const box = $("#mod-queue");
  box.replaceChildren();
  if (!items.length) box.append(el("p", { class: "muted", text: "Queue is empty." }));
  items.forEach((item) => {
    const actions = el("div", { class: "row" });
    const mk = (label, action, cls) => {
      const b = el("button", { class: cls, type: "button", text: label });
      b.addEventListener("click", async () => {
        await api(`/api/mod/queue/${item.id}/resolve`, { method: "POST", body: { action } });
        loadModDashboard();
      });
      return b;
    };
    actions.append(mk("Release to room", "release", "primary"), mk("Confirm", "confirm", "secondary"), mk("Dismiss", "dismiss", "secondary"));
    box.append(el("div", { class: "card" }, [
      el("p", { class: "meta", text: `${item.kind} · level ${item.level ?? "n/a"} · ${item.categories.join(", ")}` }),
      el("p", { class: "meta", text: `Room: ${item.room_id} · Account: @${item.username} · Chat name: ${item.author}` }),
      el("p", { class: "text", text: item.text }),
      el("p", { class: "small muted", text: item.reason ? `Reason: ${item.reason}` : "" }),
      actions,
    ]));
  });
}

function renderModUsers(users) {
  const table = $("#mod-users");
  table.replaceChildren();
  const head = el("tr", {}, ["Username", "Chat name", "Role", "Status", "Posts", "Held", "Flags", "Action"].map((h) => el("th", { text: h })));
  table.append(el("thead", {}, [head]));
  const body = el("tbody");
  users.forEach((u) => {
    const cells = [
      el("td", { text: u.username }),
      el("td", { text: u.chat_name || "" }),
      el("td", { text: u.role }),
      el("td", { text: u.status }),
      el("td", { text: String(u.messages_posted) }),
      el("td", { text: String(u.held_messages) }),
      el("td", { text: String(u.flags) }),
    ];
    const actionCell = el("td");
    if (u.role !== "moderator") {
      const next = u.status === "active" ? "suspended" : "active";
      const b = el("button", { class: u.status === "active" ? "secondary" : "primary", type: "button",
        text: u.status === "active" ? "Suspend" : "Reactivate" });
      b.addEventListener("click", async () => {
        if (next === "suspended" && !confirm(`Suspend @${u.username}? They will be logged out.`)) return;
        await api(`/api/mod/users/${u.id}/status`, { method: "POST", body: { status: next } });
        loadModDashboard();
      });
      actionCell.append(b);
    }
    cells.push(actionCell);
    body.append(el("tr", {}, cells));
  });
  table.append(body);
}

function renderModAudit(entries) {
  const list = $("#mod-audit");
  list.replaceChildren();
  entries.slice(0, 50).forEach((e) => list.append(el("li", { text: `${e.ts} · ${e.actor} · ${e.action} · ${e.target}` })));
}

// Chat monitor: the moderator sees every room, with usernames, without joining.

async function refreshMonitorRoomList() {
  const data = await api("/api/rooms");
  const select = $("#mon-room");
  const previous = state.monitorRoom || select.value;
  select.replaceChildren(...data.rooms.map((r) => el("option", { value: r.id, text: `${r.name} (${r.members} joined)${r.status === "red_flag" ? " · PAUSED" : ""}` })));
  if (previous && data.rooms.some((r) => r.id === previous)) select.value = previous;
  if (!state.monitorRoom && select.value) state.monitorRoom = select.value;
  if (state.monitorRoom) await loadMonitor(state.monitorRoom);
}

async function loadMonitor(roomId) {
  try {
    const data = await api(`/api/mod/rooms/${roomId}`);
    const box = $("#mon-messages");
    box.replaceChildren();
    if (data.flags.length) {
      box.append(el("p", { class: "banner warn", text: `${data.flags.length} open flag(s) in this room. See the safety queue.` }));
    }
    data.messages.forEach((m) => box.append(buildBubble(m, true, false)));
    if (!data.messages.length) box.append(el("p", { class: "muted", text: "No messages yet." }));
    box.scrollTop = box.scrollHeight;
    renderMembers($("#mon-members"), data.members, true);
  } catch (e) {
    $("#announce-msg").textContent = e.message;
  }
}

async function postAnnouncement(e) {
  e.preventDefault();
  const input = $("#announce-input");
  const msg = $("#announce-msg");
  const text = input.value.trim();
  if (!text || !state.monitorRoom) return;
  try {
    await api(`/api/mod/rooms/${state.monitorRoom}/announce`, { method: "POST", body: { text } });
    input.value = "";
    msg.className = "small success";
    msg.textContent = "Announcement posted to the room.";
    loadMonitor(state.monitorRoom);
  } catch (err) {
    msg.className = "small error";
    msg.textContent = err.message;
  }
}

function startMonitor() {
  stopMonitor();
  state.monitorTimer = setInterval(() => {
    if (state.monitorRoom) loadMonitor(state.monitorRoom);
  }, MONITOR_POLL_MS);
}

function stopMonitor() {
  if (state.monitorTimer) clearInterval(state.monitorTimer);
  state.monitorTimer = null;
}

// ---------- Reminder ----------

function setupReminder() {
  const timeKey = "mc_reminder_time";
  if (!localStorage.getItem(timeKey)) localStorage.setItem(timeKey, "09:00");
  const check = () => {
    if (!state.user) return;
    const [h, m] = localStorage.getItem(timeKey).split(":").map(Number);
    const now = new Date();
    if (localStorage.getItem("mc_reminder_shown") === now.toDateString()) return;
    if (now.getHours() > h || (now.getHours() === h && now.getMinutes() >= m)) {
      $("#reminder").classList.remove("hidden");
      localStorage.setItem("mc_reminder_shown", now.toDateString());
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification("MindCircle", { body: "Time for your daily check-in." });
      }
    }
  };
  $("#reminder-dismiss").addEventListener("click", () => $("#reminder").classList.add("hidden"));
  check();
  setInterval(check, 60 * 1000);
}

// ---------- Wiring ----------

document.querySelectorAll(".tab[data-tab]").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
$("#logout").addEventListener("click", () => logout(false));
$("#show-login").addEventListener("click", () => showAuthTab("login"));
$("#show-signup").addEventListener("click", () => showAuthTab("signup"));
$("#login-form").addEventListener("submit", login);
$("#signup-form").addEventListener("submit", signup);
$("#checkin-submit").addEventListener("click", submitCheckin);
$("#act-mood").addEventListener("change", loadActivities);
$("#act-energy").addEventListener("change", loadActivities);
$("#act-need").addEventListener("change", loadActivities);
$("#room-back").addEventListener("click", () => { stopChat(); loadRooms(); });
$("#message-form").addEventListener("submit", sendMessage);
$("#task-form").addEventListener("submit", addTask);
$("#ics-import").addEventListener("click", importCalendar);
$("#crisis-country").addEventListener("change", loadCrisis);
$("#profile-form").addEventListener("submit", saveProfile);
$("#password-form").addEventListener("submit", changePassword);
$("#mod-refresh").addEventListener("click", loadModDashboard);
$("#mon-room").addEventListener("change", (e) => {
  state.monitorRoom = e.target.value;
  loadMonitor(state.monitorRoom);
  startMonitor();
});
$("#announce-form").addEventListener("submit", postAnnouncement);

renderMoods();
setupReminder();
restoreSession();
