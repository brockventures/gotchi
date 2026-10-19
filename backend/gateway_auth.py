#!/usr/bin/env python3
"""
GOTCHI V1 — T3.2 Per-Device Bearer Token Auth & Remote Tunnel Gateway
=====================================================================
Provides:
1. `BearerTokenVerifier`: Constant-time (`hmac.compare_digest`) per-device bearer token
   and `sha256:<hex>` digest verification with per-IP sliding-window brute-force rate limiting
   for off-LAN requests arriving from mobile hotspots or the Android BLE-to-Tailscale forwarder.
2. `extract_bearer_token`: Parses RFC 6750 `Authorization: Bearer <token>` headers.
3. `verify_gateway_request`: Middleware helper returning `(ok, status_code, error_dict)`
   matching the Mirrormere voice contract (`401 unauthorized`, `403 forbidden`, `429 rate_limited`).
"""

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple


def extract_bearer_token(headers: Mapping[str, str]) -> Optional[str]:
    """Extract RFC 6750 Bearer token from case-insensitive HTTP headers."""
    for k, v in headers.items():
        if k.lower() == "authorization" and isinstance(v, str):
            parts = v.strip().split(None, 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                token = parts[1].strip()
                return token if token else None
    return None


@dataclass
class RateLimitBucket:
    failures: list = field(default_factory=list)


class BearerTokenVerifier:
    """
    Verifies per-device (`node_id -> token_or_sha256`) or global fleet bearer tokens
    using constant-time comparison and bounded per-client failure rate limiting.
    """

    def __init__(
        self,
        device_tokens: Optional[Dict[str, str]] = None,
        max_failures_per_minute: int = 10,
        window_seconds: float = 60.0,
    ):
        # Map of node_id (or "*" wildcard) -> raw secret or "sha256:<hex_digest>"
        self.device_tokens: Dict[str, str] = dict(device_tokens or {})
        self.max_failures = max_failures_per_minute
        self.window_seconds = window_seconds
        self._buckets: Dict[str, RateLimitBucket] = {}

    @classmethod
    def from_env_or_file(cls, env_var: str = "GOTCHI_DEVICE_TOKENS", json_path: Optional[str] = None) -> "BearerTokenVerifier":
        tokens: Dict[str, str] = {}
        if json_path and os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    tokens.update({str(k): str(v) for k, v in data.items()})
        raw_env = os.environ.get(env_var, "").strip()
        if raw_env:
            if raw_env.startswith("{"):
                tokens.update({str(k): str(v) for k, v in json.loads(raw_env).items()})
            else:
                # Support comma-separated "node_id:token" or single wildcard token
                for item in raw_env.split(","):
                    item = item.strip()
                    if not item:
                        continue
                    if ":" in item and not item.startswith("sha256:"):
                        nid, tok = item.split(":", 1)
                        tokens[nid.strip()] = tok.strip()
                    else:
                        tokens["*"] = item
        return cls(device_tokens=tokens)

    @staticmethod
    def _matches_secret(candidate: str, expected: str) -> bool:
        if expected.startswith("sha256:"):
            expected_hex = expected.split(":", 1)[1].strip().lower()
            cand_hex = hashlib.sha256(candidate.encode("utf-8")).hexdigest().lower()
            return hmac.compare_digest(cand_hex, expected_hex)
        return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))

    def is_rate_limited(self, client_ip: str, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        bucket = self._buckets.get(client_ip)
        if not bucket:
            return False
        cutoff = now - self.window_seconds
        bucket.failures = [ts for ts in bucket.failures if ts >= cutoff]
        return len(bucket.failures) >= self.max_failures

    def record_failure(self, client_ip: str, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        bucket = self._buckets.setdefault(client_ip, RateLimitBucket())
        cutoff = now - self.window_seconds
        bucket.failures = [ts for ts in bucket.failures if ts >= cutoff]
        bucket.failures.append(now)

    def verify(
        self,
        headers: Mapping[str, str],
        node_id: Optional[str] = None,
        client_ip: str = "0.0.0.0",
        now: Optional[float] = None,
    ) -> Tuple[bool, int, Dict[str, str]]:
        """
        Validate request headers against configured device tokens.
        Returns `(ok, http_status, error_payload)`.
        """
        if self.is_rate_limited(client_ip, now=now):
            return False, 429, {"error": "rate_limited", "message": "Too many failed auth attempts"}

        token = extract_bearer_token(headers)
        if not token:
            self.record_failure(client_ip, now=now)
            return False, 401, {"error": "unauthorized", "message": "Missing Bearer token"}

        resolved_node = node_id or headers.get("X-Gotchi-Node") or headers.get("x-gotchi-node")
        if resolved_node and resolved_node in self.device_tokens:
            expected = self.device_tokens[resolved_node]
            if self._matches_secret(token, expected):
                return True, 200, {}
            self.record_failure(client_ip, now=now)
            return False, 403, {"error": "forbidden", "message": "Invalid token for node"}

        # Check wildcard token or any registered device token when node_id is inside multipart body
        for reg_node, expected in self.device_tokens.items():
            if reg_node == "*" or resolved_node is None:
                if self._matches_secret(token, expected):
                    return True, 200, {}

        self.record_failure(client_ip, now=now)
        return False, 403, {"error": "forbidden", "message": "Invalid Bearer token"}
