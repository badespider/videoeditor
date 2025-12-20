"""
Smoke checks for webhook authentication helpers.

Run from repo root (PowerShell):
  python backend\\scripts\\webhook_auth_smoke.py
"""

from __future__ import annotations

import sys
import hmac
import hashlib


def main() -> int:
    sys.path.insert(0, "backend")

    from app.routers.webhooks import _verify_hmac_sha256, _normalize_signature  # noqa: WPS433

    secret = "test_secret"
    body = b'{"code":"0000","status":"PARSE"}'

    expected_hex = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    assert _normalize_signature(f"sha256={expected_hex}") == expected_hex
    assert _normalize_signature(expected_hex) == expected_hex

    assert _verify_hmac_sha256(secret, body, expected_hex) is True
    assert _verify_hmac_sha256(secret, body, f"sha256={expected_hex}") is True
    assert _verify_hmac_sha256(secret, body, "sha256=deadbeef") is False
    assert _verify_hmac_sha256("", body, expected_hex) is False

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


