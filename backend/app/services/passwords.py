"""Password policy and one-time temporary password generation for management accounts."""
import secrets

MIN_PASSWORD_CHARS = 12
MAX_PASSWORD_BYTES = 72  # bcrypt ignores everything after 72 bytes
MIN_CHARACTER_CLASSES = 3

# Look-alike characters are left out so a password read from a screen can be typed back.
_LOWER = "abcdefghijkmnopqrstuvwxyz"
_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_DIGITS = "23456789"
_GROUPS = 4
_GROUP_SIZE = 4


def _character_classes(value: str) -> int:
    """Count how many of lowercase, uppercase, digit and other characters appear."""
    return sum((
        any(char.islower() for char in value),
        any(char.isupper() for char in value),
        any(char.isdigit() for char in value),
        any(not char.isalnum() for char in value),
    ))


def password_problem(value: str) -> str | None:
    """Return why a new password is rejected, or None when it is acceptable."""
    if len(value) < MIN_PASSWORD_CHARS:
        return f"Password must be at least {MIN_PASSWORD_CHARS} characters"
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return f"Password must not exceed {MAX_PASSWORD_BYTES} UTF-8 bytes"
    if _character_classes(value) < MIN_CHARACTER_CLASSES:
        return ("Password must mix at least three of: lowercase letters, uppercase letters, "
                "digits, symbols")
    return None


def generate_temporary_password() -> str:
    """Random one-time password such as `kTq7-mN4x-Pw9c-Hs2d`; always satisfies the policy."""
    alphabet = _LOWER + _UPPER + _DIGITS
    while True:
        chars = [secrets.choice(alphabet) for _ in range(_GROUPS * _GROUP_SIZE)]
        if (any(c in _LOWER for c in chars) and any(c in _UPPER for c in chars)
                and any(c in _DIGITS for c in chars)):
            break
    groups = ["".join(chars[i:i + _GROUP_SIZE]) for i in range(0, len(chars), _GROUP_SIZE)]
    password = "-".join(groups)
    assert password_problem(password) is None, "Generated password must satisfy the policy"
    return password


def resolve_new_password(requested: str | None) -> tuple[str, bool]:
    """Use the explicit password, or generate one. Returns (password, was_generated)."""
    if requested:
        return requested, False
    return generate_temporary_password(), True
