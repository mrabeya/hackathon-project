"""Accounts: password hashing, validation, and session tokens.

Passwords are hashed with PBKDF2-SHA256 and a random salt. Session tokens are
random; only their SHA-256 hash is stored, so a copy of the data file cannot
be used to log in.
"""
import hashlib
import hmac
import re
import secrets

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
PBKDF2_ROUNDS = 200_000
SESSION_TTL_SECONDS = 12 * 60 * 60
MAX_FAILED_LOGINS = 5
LOCKOUT_SECONDS = 15 * 60
MIN_PASSWORD_LENGTH = 8


def hash_password(password, salt_hex=None):
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return salt.hex(), digest.hex()


def verify_password(password, salt_hex, hash_hex):
    _, candidate = hash_password(password, salt_hex)
    return hmac.compare_digest(candidate, hash_hex)


def new_token():
    return secrets.token_urlsafe(32)


def token_key(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_password(password):
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > 128:
        return "Password must be 128 characters or fewer."
    return None


def validate_signup(username, password, confirm, display_name, adult, consent):
    """Return a list of human-readable errors (empty list means valid)."""
    errors = []
    if not USERNAME_RE.match(username or ""):
        errors.append("Username must be 3 to 20 characters: letters, numbers, or underscore.")
    pw_error = validate_password(password)
    if pw_error:
        errors.append(pw_error)
    if password != confirm:
        errors.append("Passwords do not match.")
    if not display_name or len(display_name.strip()) > 40:
        errors.append("Display name is required (40 characters or fewer).")
    if adult is not True:
        errors.append("You must confirm you are 18 or older.")
    if consent is not True:
        errors.append("You must agree that chat messages are safety-screened.")
    return errors


CHAT_NAME_RE = re.compile(r"^[A-Za-z0-9_ ]{2,24}$")


def validate_chat_name(name):
    """Chat names are shown in groups. Letters, numbers, spaces, and underscores only."""
    if not CHAT_NAME_RE.match(name or "") or not name.strip():
        return "Chat name must be 2 to 24 letters, numbers, spaces, or underscores."
    return None
