"""Parent PIN, and the honest limits of it.

What this protects against: a 13-year-old opening the app and reading the answer
key to the assessment he's about to take. That is a real, everyday problem and a
PIN solves it.

What this does not protect against: the same 13-year-old opening `compass.db` in
any SQLite viewer, or reading the lesson JSON in a text editor. The data sits on
a machine he uses. Treat this as a lock on a cupboard door, not a safe — it stops
the accident and the idle glance, not a determined search.

The PIN is stored as a salted PBKDF2 hash rather than plaintext, because it will
be reused from somewhere else no matter how often people are told not to.
"""

from __future__ import annotations

import hashlib
import hmac
import os

PIN_SETTING = "parent_pin_hash"
ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 200_000
MIN_PIN_LENGTH = 4


class PinError(ValueError):
    """Raised when a PIN is rejected at set time. Message is user-facing."""


def hash_pin(pin: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, ITERATIONS)
    return f"{ALGORITHM}${ITERATIONS}${salt.hex()}${derived.hex()}"


def check_pin(stored: str | None, pin: str) -> bool:
    if not stored or not pin:
        return False
    try:
        algorithm, iterations, salt_hex, expected_hex = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        derived = hashlib.pbkdf2_hmac(
            "sha256", pin.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, AttributeError):
        return False
    # Constant-time so a wrong PIN can't be narrowed down by timing.
    return hmac.compare_digest(derived.hex(), expected_hex)


# --- database-facing helpers -------------------------------------------------


def pin_is_set(db) -> bool:
    return bool(db.get_setting(PIN_SETTING, ""))


def set_pin(db, pin: str) -> None:
    pin = (pin or "").strip()
    if len(pin) < MIN_PIN_LENGTH:
        raise PinError(f"Use at least {MIN_PIN_LENGTH} characters.")
    db.set_setting(PIN_SETTING, hash_pin(pin))


def verify(db, pin: str) -> bool:
    return check_pin(db.get_setting(PIN_SETTING, ""), (pin or "").strip())


def clear_pin(db) -> None:
    db.set_setting(PIN_SETTING, "")
