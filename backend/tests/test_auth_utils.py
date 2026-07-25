from starlette.requests import Request

from app.services.auth import (
    create_access_token,
    hash_api_key,
    hash_password,
    verify_password,
)
from app.utils.ip_check import get_client_ip
from app.utils.key_generator import generate_api_key

def test_password_hash_verify():
    plain = "test-password-123"
    hashed = hash_password(plain)
    assert hashed != plain
    assert verify_password(plain, hashed) is True
    assert verify_password("wrong", hashed) is False


def test_hash_api_key_deterministic():
    key = "sk-abc123"
    h1 = hash_api_key(key)
    h2 = hash_api_key(key)
    assert h1 == h2
    assert len(h1) == 64


def test_hash_api_key_different_keys():
    assert hash_api_key("sk-a") != hash_api_key("sk-b")


def test_create_access_token():
    token = create_access_token({"sub": 1})
    assert isinstance(token, str)
    assert len(token) > 20


def test_generate_api_key_format():
    key = generate_api_key()
    assert key.startswith("sk-")
    assert len(key) == 51  # "sk-" + 48 chars


def test_generate_api_key_unique():
    keys = {generate_api_key() for _ in range(100)}
    assert len(keys) == 100


def test_generate_api_key_custom_prefix():
    key = generate_api_key(prefix="five-", length=32)
    assert key.startswith("five-")
    assert len(key) == 37


def test_client_ip_does_not_trust_forwarded_header():
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-forwarded-for", b"203.0.113.99")],
        "client": ("10.0.0.8", 12345),
    })
    assert get_client_ip(request) == "10.0.0.8"
