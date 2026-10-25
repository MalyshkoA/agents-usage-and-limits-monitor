from __future__ import annotations

import hashlib
import hmac


def body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_request(
    *, method: str, path: str, timestamp: str, nonce: str, body: bytes
) -> bytes:
    parts = [method.upper(), path, timestamp, nonce, body_sha256(body)]
    return "\n".join(parts).encode("utf-8")


def sign_request(
    *, secret: str, method: str, path: str, timestamp: str, nonce: str, body: bytes
) -> str:
    message = canonical_request(
        method=method, path=path, timestamp=timestamp, nonce=nonce, body=body
    )
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_signature(*, expected: str, provided: str) -> bool:
    return hmac.compare_digest(expected, provided)
