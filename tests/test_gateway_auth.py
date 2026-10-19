import hashlib
from backend.gateway_auth import BearerTokenVerifier, extract_bearer_token


def test_extract_bearer_token():
    assert extract_bearer_token({"Authorization": "Bearer secret-123"}) == "secret-123"
    assert extract_bearer_token({"authorization": "bearer   tok_abc  "}) == "tok_abc"
    assert extract_bearer_token({"Authorization": "Basic dXNlcjpwYXNz"}) is None
    assert extract_bearer_token({}) is None


def test_per_device_and_sha256_verification():
    hashed = "sha256:" + hashlib.sha256(b"pi-zero-secret").hexdigest()
    verifier = BearerTokenVerifier(
        device_tokens={
            "gotchi-v1-01": "xiao-secret-token",
            "gotchi-poc-01": hashed,
        },
        max_failures_per_minute=3,
    )

    ok, code, _ = verifier.verify(
        {"Authorization": "Bearer xiao-secret-token", "X-Gotchi-Node": "gotchi-v1-01"},
        client_ip="198.51.100.10",
        now=100.0,
    )
    assert ok is True and code == 200

    ok, code, _ = verifier.verify(
        {"Authorization": "Bearer pi-zero-secret"},
        node_id="gotchi-poc-01",
        client_ip="198.51.100.11",
        now=100.0,
    )
    assert ok is True and code == 200

    # Missing token -> 401
    ok, code, err = verifier.verify({}, node_id="gotchi-v1-01", client_ip="198.51.100.99", now=101.0)
    assert ok is False and code == 401 and err["error"] == "unauthorized"

    # Wrong token -> 403, and after 3 failures triggers 429 rate limit
    verifier.verify({"Authorization": "Bearer wrong1"}, node_id="gotchi-v1-01", client_ip="198.51.100.99", now=102.0)
    verifier.verify({"Authorization": "Bearer wrong2"}, node_id="gotchi-v1-01", client_ip="198.51.100.99", now=103.0)
    ok, code, err = verifier.verify(
        {"Authorization": "Bearer xiao-secret-token"},
        node_id="gotchi-v1-01",
        client_ip="198.51.100.99",
        now=104.0,
    )
    assert ok is False and code == 429 and err["error"] == "rate_limited"
