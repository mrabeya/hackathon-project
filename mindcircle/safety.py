"""Rule-based safety screening for MindCircle.

This is a hackathon prototype, NOT a clinically validated classifier.
It flags phrases so that a trained human moderator can review them.
Expect false positives and missed messages. Never rely on it alone.
"""
import re

LEVEL_NAMES = {
    0: "normal",
    1: "distress",
    2: "concerning",
    3: "serious",
    4: "imminent",
}

# (level, category, pattern). Matching is case-insensitive.
RULES = [
    # Level 4: imminent self-harm
    (4, "self_harm", r"\b(kill myself|end my life|end it all|suicide)\b.*\b(tonight|today|right now|now|in an hour)\b"),
    (4, "self_harm", r"\b(i'?m|i am|going to|about to) (kill myself|end my life|end it all)\b"),
    (4, "self_harm", r"\b(i have|i'?ve got|i got)\b.*\b(pills|a gun|rope|a knife)\b.*\b(ready|now|tonight)\b"),
    # Level 3: serious self-harm or direct threats
    (3, "self_harm", r"\b(want to die|wish i was dead|kill myself|end my life|suicidal|suicide plan)\b"),
    (3, "self_harm", r"\b(hurt|harm|cut) myself\b"),
    (3, "threat", r"\b(i will|i'?m going to|gonna|i'?ll) (kill|shoot|stab|bomb|hurt|beat up) (him|her|them|you|someone|everyone)\b"),
    (3, "crime_planning", r"\b(plan(ning)? to|going to) (rob|steal from|break into|mug|assault|poison|kidnap)\b"),
    (3, "crime_planning", r"\b(how to|how do i) (make|build) (a )?(bomb|explosive|poison|gun)\b"),
    # Level 2: concerning
    (2, "self_harm", r"\b(self[- ]harm|don'?t want to be here|no point (in )?living|hopeless|can'?t go on)\b"),
    (2, "hostility", r"\b(hate|sick of) (everyone|them|you|people)\b"),
    # Level 1: distress
    (1, "distress", r"\b(sad|lonely|anxious|stressed|overwhelmed|exhausted|scared|hurting)\b"),
]

COMPILED = [(lvl, cat, re.compile(pat, re.IGNORECASE)) for lvl, cat, pat in RULES]

FIRST_PERSON = re.compile(r"\b(i|i'm|me|my|myself)\b", re.IGNORECASE)
EDUCATIONAL = re.compile(
    r"\b(prevention|news|article|book|documentary|research|study|awareness|lecture)\b",
    re.IGNORECASE,
)
CRIME_CATEGORIES = {"crime_planning", "threat"}


def assess(text):
    """Return a safety assessment dict for one message."""
    text = (text or "").strip()
    hits = [(lvl, cat) for lvl, cat, rx in COMPILED if rx.search(text)]
    level = max((lvl for lvl, _ in hits), default=0)
    categories = sorted({cat for _, cat in hits})

    # Context guard: third-person, educational talk (e.g. "I read a book about
    # suicide prevention" has first-person words, so it is NOT lowered) is
    # de-escalated by one level only for levels 2-3 with no first-person intent
    # and no crime/threat category.
    if (
        level in (2, 3)
        and EDUCATIONAL.search(text)
        and not FIRST_PERSON.search(text)
        and not (CRIME_CATEGORIES & set(categories))
    ):
        level -= 1

    crime_or_threat = bool(CRIME_CATEGORIES & set(categories))
    red_flag = level >= 4 or crime_or_threat
    hold = red_flag or level >= 3

    return {
        "level": level,
        "level_name": LEVEL_NAMES[level],
        "categories": categories,
        "hold": hold,               # message is not posted publicly
        "red_flag": red_flag,       # room is paused for moderator review
        "show_crisis": level >= 3,  # show crisis/emergency panel to the author
        "show_support_tip": level >= 1,
        "needs_review": hold or level == 2,
    }
