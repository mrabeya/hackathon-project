"""Personalised suggestions based on the chosen mood, energy, need, and this user's history.

Scoring (higher is better):
  +4  activity is meant for the chosen mood (required; others are skipped)
  +2  fits the energy level, +1 more if energy is low and it is short
  +2  matches what the user said they need (relax / talk / focus)
  +4  user previously marked this activity helpful
  +2  user has marked this activity type helpful before
  -6  user marked this activity "not for me"
  -5  shown in the user's last few suggestions (keeps variety)
"""
from content import ACTIVITIES, ENERGY_NOTES, MOOD_PROFILES, NEED_NOTES

RECENT_LIMIT = 6


def build_message(mood, energy, need):
    p = MOOD_PROFILES[mood]
    parts = [
        f"{p['headline']}. Today, focus on {p['focus']}.",
        f"Try to avoid {p['avoid']}.",
        NEED_NOTES.get(need, ""),
        ENERGY_NOTES.get(energy, ""),
    ]
    return " ".join(x for x in parts if x)


def empty_history():
    return {"helpful": set(), "not_helpful": set(), "helpful_types": set(), "recent": []}


def build_history(feedback_entries, recent_ids):
    """feedback_entries: list of {activity_id, helpful}. recent_ids: last suggested ids."""
    by_id = {a["id"]: a for a in ACTIVITIES}
    history = empty_history()
    for entry in feedback_entries:
        aid = entry["activity_id"]
        if aid not in by_id:
            continue
        if entry["helpful"]:
            history["helpful"].add(aid)
            history["helpful_types"].add(by_id[aid]["type"])
        else:
            history["not_helpful"].add(aid)
    history["recent"] = list(recent_ids)[-RECENT_LIMIT:]
    return history


def _score(act, mood, energy, need, history):
    if mood not in act["moods"]:
        return None, []
    score = 4
    reasons = [f"it suits feeling {mood}"]
    if energy in act["energy"]:
        score += 2
        reasons.append(f"it fits {energy} energy")
        if energy == "low" and act["minutes"] <= 10:
            score += 1
    else:
        score -= 2
    if need in act["needs"]:
        score += 2
        reasons.append(f"it helps when you want to {need}")
    if act["id"] in history["helpful"]:
        score += 4
        reasons.append("you found it helpful before")
    elif act["type"] in history["helpful_types"]:
        score += 2
        reasons.append(f"you have liked {act['type']} activities")
    if act["id"] in history["not_helpful"]:
        score -= 6
    if act["id"] in history["recent"]:
        score -= 5
    return score, reasons


def recommend(mood, energy, need, history, limit=3):
    scored = []
    for act in ACTIVITIES:
        score, reasons = _score(act, mood, energy, need, history)
        if score is None:
            continue
        scored.append((score, act["minutes"], act["id"], act, reasons))
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    results = []
    for score, _, _, act, reasons in scored[:limit]:
        results.append({
            **act,
            "why": "Picked because " + "; ".join(reasons[:3]) + "." if reasons else "",
        })
    return results
