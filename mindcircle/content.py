"""Curated content: moods, mood profiles, activities, rooms, and crisis resources.

Video links are YouTube *search* links, not hard-coded video IDs, so they
never point to a video that has been removed. Replace them with approved
video IDs once a content reviewer has checked them.
"""
import random
from urllib.parse import quote_plus

MOODS = ["happy", "calm", "anxious", "sad", "stressed", "lonely", "exhausted"]
ENERGY_LEVELS = ["low", "medium", "high"]
NEEDS = ["talk", "relax", "focus"]


def _yt(query):
    return "https://www.youtube.com/results?search_query=" + quote_plus(query)


# Each mood has its own framing, so the message changes with the feeling chosen.
MOOD_PROFILES = {
    "happy": {
        "headline": "You're feeling good, so it's a good time to build on it",
        "focus": "noticing what is working and sharing it",
        "avoid": "pushing yourself to be productive all day",
    },
    "calm": {
        "headline": "You're steady right now",
        "focus": "keeping this calm and making space for something creative",
        "avoid": "adding several new tasks at once",
    },
    "anxious": {
        "headline": "Your body may be on alert",
        "focus": "slowing your breathing and grounding your attention in the present",
        "avoid": "reassurance loops or checking news repeatedly",
    },
    "sad": {
        "headline": "It's okay to feel low today",
        "focus": "being gentle with yourself and reconnecting with something small",
        "avoid": "judging yourself for not doing more",
    },
    "stressed": {
        "headline": "There's a lot on your plate",
        "focus": "shrinking the load down to one manageable step",
        "avoid": "multitasking across several things",
    },
    "lonely": {
        "headline": "Connection matters, and wanting it is normal",
        "focus": "reaching toward one person or a shared activity",
        "avoid": "waiting for the perfect moment to reach out",
    },
    "exhausted": {
        "headline": "Your energy is low, and that is useful information",
        "focus": "resting well and doing only what is essential",
        "avoid": "skipping sleep or relying on caffeine to push through",
    },
}

NEED_NOTES = {
    "talk": "A community room is there when you want to share. You never have to share more than you choose.",
    "relax": "Pick something that asks little of you.",
    "focus": "Choose one small step and set a timer.",
}

ENERGY_NOTES = {
    "low": "Keep it under 10 minutes.",
    "medium": "",
    "high": "You have room for a longer activity today.",
}

ACTIVITIES = [
    {"id": "breathing-478", "title": "4-7-8 breathing", "type": "breathing", "minutes": 3,
     "moods": ["anxious", "stressed"], "energy": ["low", "medium", "high"], "needs": ["relax"],
     "description": "Breathe in for 4, hold for 7, breathe out for 8. Repeat four times.", "url": None},
    {"id": "box-breathing", "title": "Box breathing", "type": "breathing", "minutes": 4,
     "moods": ["anxious", "stressed"], "energy": ["medium", "high"], "needs": ["relax", "focus"],
     "description": "Breathe in for 4, hold for 4, out for 4, hold for 4. Repeat six times.", "url": None},
    {"id": "grounding-54321", "title": "5-4-3-2-1 grounding", "type": "grounding", "minutes": 5,
     "moods": ["anxious"], "energy": ["low", "medium"], "needs": ["relax", "focus"],
     "description": "Name 5 things you see, 4 you can touch, 3 you hear, 2 you smell, 1 you taste.", "url": None},
    {"id": "body-scan", "title": "Gentle body scan", "type": "meditation", "minutes": 8,
     "moods": ["exhausted", "anxious"], "energy": ["low"], "needs": ["relax"],
     "description": "Sit or lie comfortably. Notice each body part from feet to head without changing it.", "url": None},
    {"id": "gratitude-journal", "title": "Three good things journal", "type": "journaling", "minutes": 5,
     "moods": ["happy", "calm"], "energy": ["low", "medium", "high"], "needs": ["focus", "relax"],
     "description": "Write three things that went well today and why they mattered to you.", "url": None},
    {"id": "self-compassion", "title": "Self-compassion note", "type": "journaling", "minutes": 10,
     "moods": ["sad", "lonely"], "energy": ["low", "medium"], "needs": ["relax", "talk"],
     "description": "Write a short note to yourself the way you would write to a close friend.", "url": None},
    {"id": "watercolor-sketch", "title": "Simple watercolor wash", "type": "art", "minutes": 20,
     "moods": ["calm", "happy", "sad"], "energy": ["medium", "high"], "needs": ["relax"],
     "description": "Paint one loose wash of colour. A finished picture is not the goal.",
     "url": _yt("beginner watercolor tutorial for relaxing")},
    {"id": "doodle-break", "title": "Free doodle break", "type": "art", "minutes": 10,
     "moods": ["happy", "calm", "stressed"], "energy": ["low", "medium", "high"], "needs": ["relax"],
     "description": "Doodle freely for ten minutes. Judging the result is not allowed.", "url": None},
    {"id": "paper-crafts", "title": "Easy paper craft", "type": "craft", "minutes": 15,
     "moods": ["stressed", "lonely", "happy"], "energy": ["low", "medium"], "needs": ["relax", "talk"],
     "description": "Fold a paper crane or cut a simple paper garland with your hands.",
     "url": _yt("easy origami for beginners")},
    {"id": "music-listen", "title": "Listen to calming music", "type": "music", "minutes": 15,
     "moods": ["sad", "calm", "exhausted"], "energy": ["low"], "needs": ["relax"],
     "description": "Listen to one calm album from start to finish without doing anything else.",
     "url": _yt("calming music for low mood")},
    {"id": "walk-outside", "title": "Ten-minute walk", "type": "movement", "minutes": 10,
     "moods": ["stressed", "exhausted", "sad"], "energy": ["medium", "high"], "needs": ["relax", "focus"],
     "description": "Walk outside and notice three things in your surroundings.", "url": None},
    {"id": "meditation-sleep", "title": "Guided rest meditation", "type": "meditation", "minutes": 15,
     "moods": ["exhausted", "anxious"], "energy": ["low"], "needs": ["relax"],
     "description": "A slow guided meditation to help you wind down.",
     "url": _yt("guided meditation for rest and recovery")},
    {"id": "meditation-calm", "title": "Guided mindfulness meditation", "type": "meditation", "minutes": 10,
     "moods": ["calm", "stressed", "anxious"], "energy": ["low", "medium", "high"], "needs": ["relax"],
     "description": "A short guided practice focused on breath and body.",
     "url": _yt("10 minute guided mindfulness meditation")},
    {"id": "reach-out", "title": "Message one friend", "type": "social", "minutes": 5,
     "moods": ["lonely", "sad"], "energy": ["low", "medium", "high"], "needs": ["talk"],
     "description": "Send a short, low-pressure message to someone you trust.", "url": None},
    {"id": "gratitude-call", "title": "Tell someone you appreciate them", "type": "social", "minutes": 10,
     "moods": ["lonely", "happy"], "energy": ["low", "medium", "high"], "needs": ["talk"],
     "description": "Message someone you appreciate and name one specific thing they did.", "url": None},
    {"id": "focus-sprint", "title": "15-minute focus sprint", "type": "focus", "minutes": 15,
     "moods": ["happy", "calm", "stressed"], "energy": ["medium", "high"], "needs": ["focus"],
     "description": "Work on one small step of your priority task for 15 minutes.", "url": None},
    {"id": "tidy-one-space", "title": "Tidy one small space", "type": "focus", "minutes": 10,
     "moods": ["stressed", "sad"], "energy": ["low", "medium"], "needs": ["focus"],
     "description": "Clear one small surface. Stop when the timer ends.", "url": None},
]

ROOMS = [
    {"id": "anxiety-support", "name": "Anxiety Support", "mood": "anxious",
     "description": "Share coping strategies and encouragement."},
    {"id": "gentle-peer-support", "name": "Gentle Peer Support", "mood": "sad",
     "description": "A quiet space for people who feel low."},
    {"id": "stress-relief", "name": "Stress Relief", "mood": "stressed",
     "description": "Swap quick tips for busy days."},
    {"id": "youre-not-alone", "name": "You're Not Alone", "mood": "lonely",
     "description": "A welcoming space for connection."},
    {"id": "gratitude-circle", "name": "Gratitude Circle", "mood": "happy",
     "description": "Share what is going well."},
    {"id": "mindfulness-circle", "name": "Mindfulness Circle", "mood": "calm",
     "description": "Practice calm and mindful habits together."},
    {"id": "rest-recovery", "name": "Rest & Recovery", "mood": "exhausted",
     "description": "Gentle conversation about rest and pacing."},
]

ROOM_BY_MOOD = {r["mood"]: r["id"] for r in ROOMS}

CRISIS_RESOURCES = {
    "US": {
        "country": "United States",
        "crisis": [{"label": "Suicide & Crisis Lifeline", "action": "Call or text 988"}],
        "emergency": {"label": "Immediate danger", "action": "Call 911"},
        "note": None,
    },
    "OTHER": {
        "country": "Other (not verified)",
        "crisis": [{"label": "Local crisis helpline", "action": "Search for your country's mental health helpline"}],
        "emergency": {"label": "Immediate danger", "action": "Call your local emergency number"},
        "note": "Add verified numbers for your country before any real use.",
    },
}

ADJECTIVES = ["Gentle", "Quiet", "Kind", "Brave", "Calm", "Bright", "Steady", "Warm", "Curious", "Patient"]
ANIMALS = ["Otter", "Heron", "Fox", "Panda", "Owl", "Finch", "Lynx", "Koala", "Deer", "Sparrow"]


def pseudonym(rng=random):
    return f"{rng.choice(ADJECTIVES)} {rng.choice(ANIMALS)} {rng.randint(10, 99)}"


def pick_room(mood):
    return ROOM_BY_MOOD.get(mood, ROOM_BY_MOOD["calm"])


HEAVY_MOODS = {"anxious", "stressed", "exhausted", "sad", "lonely"}


def suggested_first_step(task_title, energy, mood=None):
    """Shrink a task to a first step sized by energy and mood."""
    minutes = {"low": 10, "medium": 15, "high": 25}.get(energy, 15)
    if mood in HEAVY_MOODS:
        minutes = min(minutes, 5)
        return (f"Start with just {minutes} minutes on '{task_title}'. "
                "Getting started is the hard part; you can stop after that.")
    return f"Work on '{task_title}' for {minutes} minutes. Just start; you can stop after that."
