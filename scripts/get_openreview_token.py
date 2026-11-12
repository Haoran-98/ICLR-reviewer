#!/usr/bin/env python3
"""Issue a seven-day OpenReview session token through TOTP MFA."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import shlex
import struct
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

try:
    from .deployment_paths import OPENREVIEW_TOKEN
except ImportError:
    from deployment_paths import OPENREVIEW_TOKEN


REPO = Path(__file__).resolve().parents[1]
DEFAULT_AUTH = REPO / "auth"
DEFAULT_TOKEN = OPENREVIEW_TOKEN
TOKEN_EXPIRES_SECONDS = 7 * 24 * 60 * 60


def load_auth(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    pattern = re.compile(r"^[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?\s*=\s*(.+)$")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        match = pattern.match(line)
        if not match:
            continue
        parsed = shlex.split(match.group(2), comments=True)
        if len(parsed) == 1:
            values[match.group(1)] = parsed[0]
    return values


def token_claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def normalize_totp_secret(value: str) -> str:
    if value.startswith("otpauth://"):
        value = urllib.parse.parse_qs(urllib.parse.urlparse(value).query).get("secret", [""])[0]
    secret = re.sub(r"[\s-]+", "", value).upper()
    if not secret:
        raise ValueError("TOTP secret is empty")
    try:
        base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    except ValueError as error:
        raise ValueError("TOTP secret must be the Base32 setup secret or an otpauth URI") from error
    return secret


def totp(secret: str, timestamp: int | None = None, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    counter = int(time.time() if timestamp is None else timestamp) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return f"{code:0{digits}d}"


def atomic_write_token(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(token + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def consume_auth_key(path: Path, key: str) -> None:
    pattern = re.compile(rf"^(?:export\s+)?[\"']?{re.escape(key)}[\"']?\s*=")
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if not pattern.match(line.strip())]
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def issue_token(args: argparse.Namespace) -> None:
    import openreview
    from openreview import mfa

    auth_file = args.auth_file.expanduser().resolve()
    if not auth_file.is_file():
        raise RuntimeError(f"TOTP auth file is missing: {auth_file}; see auth.example")
    auth_file.chmod(0o600)
    credentials = load_auth(auth_file)
    legacy = load_auth(Path.home() / "auth") if (Path.home() / "auth").is_file() else {}
    username = (
        credentials.get("OPENREVIEW_username")
        or credentials.get("OPENREVIEW_USERNAME")
        or os.environ.get("OPENREVIEW_username")
        or os.environ.get("OPENREVIEW_USERNAME")
        or legacy.get("OPENREVIEW_username")
        or legacy.get("OPENREVIEW_USERNAME")
    )
    password = (
        credentials.get("OPENREVIEW_password")
        or credentials.get("OPENREVIEW_PASSWORD")
        or legacy.get("OPENREVIEW_password")
        or legacy.get("OPENREVIEW_PASSWORD")
    )
    temporary_code = credentials.get("Temporary_CODE") or credentials.get("TEMPORARY_CODE")
    if temporary_code and not re.fullmatch(r"\d{6}", temporary_code):
        raise ValueError("Temporary_CODE must contain exactly six digits")
    secret = None if temporary_code else normalize_totp_secret(
        credentials.get("OPENREVIEW_TOTP_SECRET")
        or credentials.get("TOTP_SECRET")
        or credentials.get("KEY")
        or ""
    )
    if not username or not password:
        raise RuntimeError("OpenReview username and password are required in auth or ~/auth")

    original_chooser = mfa._default_mfa_method_chooser
    original_code_prompt = mfa._default_mfa_code_prompt

    def choose_totp(methods: list[str], preferred: str | None) -> str:
        if "totp" not in methods:
            raise RuntimeError(f"OpenReview did not offer TOTP MFA; available methods: {', '.join(methods)}")
        return "totp"

    mfa._default_mfa_method_chooser = choose_totp
    mfa._default_mfa_code_prompt = lambda method: temporary_code or totp(secret)
    try:
        try:
            client = openreview.api.OpenReviewClient(
                baseurl=args.baseurl,
                username=username,
                password=password,
                tokenExpiresIn=TOKEN_EXPIRES_SECONDS,
            )
        except openreview.OpenReviewException as error:
            if "Invalid username or password" in str(error):
                raise RuntimeError("OpenReview rejected the configured username or password") from error
            raise
    finally:
        mfa._default_mfa_method_chooser = original_chooser
        mfa._default_mfa_code_prompt = original_code_prompt

    if not client.token:
        raise RuntimeError("OpenReview did not return a session token")
    claims = token_claims(client.token)
    lifetime = int(claims["exp"]) - int(claims["iat"])
    atomic_write_token(args.token_file.expanduser(), client.token)
    if temporary_code:
        consume_auth_key(auth_file, "Temporary_CODE")
        consume_auth_key(auth_file, "TEMPORARY_CODE")
    print(json.dumps({
        "status": "token_refreshed",
        "authentication": "totp_temporary_code" if temporary_code else "totp",
        "requested_lifetime_seconds": TOKEN_EXPIRES_SECONDS,
        "lifetime_seconds": lifetime,
        "expires_at": datetime.fromtimestamp(int(claims["exp"]), timezone.utc).isoformat(),
        "token_file": str(args.token_file.expanduser()),
    }))


def self_test() -> None:
    rfc_secret = normalize_totp_secret("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")
    assert totp(rfc_secret, timestamp=59, digits=8) == "94287082"
    uri = "otpauth://totp/OpenReview:test?secret=GEZDGNBVGY3TQOJQ&issuer=OpenReview"
    assert normalize_totp_secret(uri) == "GEZDGNBVGY3TQOJQ"
    sample_payload = base64.urlsafe_b64encode(json.dumps({"iat": 1, "exp": 1 + TOKEN_EXPIRES_SECONDS}).encode()).decode().rstrip("=")
    assert token_claims(f"e30.{sample_payload}.sig")["exp"] == 1 + TOKEN_EXPIRES_SECONDS
    print("self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth-file", type=Path, default=DEFAULT_AUTH)
    parser.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN)
    parser.add_argument("--baseurl", default="https://api2.openreview.net")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    self_test() if args.self_test else issue_token(args)


if __name__ == "__main__":
    main()
