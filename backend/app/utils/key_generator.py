import secrets
import string

ALPHABET = string.ascii_letters + string.digits


def generate_api_key(prefix: str = "sk-", length: int = 48) -> str:
    random_part = "".join(secrets.choice(ALPHABET) for _ in range(length))
    return f"{prefix}{random_part}"
