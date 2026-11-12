#!/usr/bin/env python3
"""Interactively issue a seven-day OpenReview token with an MFA code."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from get_openreview_token import (
    DEFAULT_AUTH,
    DEFAULT_TOKEN,
    TOKEN_EXPIRES_SECONDS,
    atomic_write_token,
    load_auth,
    token_claims,
)


def choose_code_method(methods: list[str], preferred: str | None = None) -> str:
    for method in ("totp", "emailOtp"):
        if method in methods:
            print(f"Using OpenReview MFA method: {method}")
            return method
    raise RuntimeError(f"OpenReview offered no code-based MFA method: {', '.join(methods)}")


def issue_token(args: argparse.Namespace) -> None:
    import openreview
    from openreview import mfa

    if not sys.stdin.isatty():
        raise RuntimeError("Run this script directly in an interactive terminal")

    local = load_auth(args.auth_file.expanduser()) if args.auth_file.expanduser().is_file() else {}
    legacy = load_auth(Path.home() / "auth") if (Path.home() / "auth").is_file() else {}
    username = (
        local.get("OPENREVIEW_username")
        or local.get("OPENREVIEW_USERNAME")
        or os.environ.get("OPENREVIEW_username")
        or os.environ.get("OPENREVIEW_USERNAME")
        or legacy.get("OPENREVIEW_username")
        or legacy.get("OPENREVIEW_USERNAME")
    )
    password = (
        local.get("OPENREVIEW_password")
        or local.get("OPENREVIEW_PASSWORD")
        or legacy.get("OPENREVIEW_password")
        or legacy.get("OPENREVIEW_PASSWORD")
    )
    if not username or not password:
        raise RuntimeError("OpenReview username and password are required in auth or /home/yhr/auth")

    original_chooser = mfa._default_mfa_method_chooser
    mfa._default_mfa_method_chooser = choose_code_method
    try:
        client = openreview.api.OpenReviewClient(
            baseurl=args.baseurl,
            username=username,
            password=password,
            tokenExpiresIn=TOKEN_EXPIRES_SECONDS,
        )
    finally:
        mfa._default_mfa_method_chooser = original_chooser

    claims = token_claims(client.token)
    lifetime = int(claims["exp"]) - int(claims["iat"])
    atomic_write_token(args.token_file.expanduser(), client.token)
    print(json.dumps({
        "status": "token_refreshed",
        "requested_lifetime_seconds": TOKEN_EXPIRES_SECONDS,
        "lifetime_seconds": lifetime,
        "server_limited_lifetime": lifetime != TOKEN_EXPIRES_SECONDS,
        "expires_at": datetime.fromtimestamp(int(claims["exp"]), timezone.utc).isoformat(),
        "token_file": str(args.token_file.expanduser()),
    }))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth-file", type=Path, default=DEFAULT_AUTH)
    parser.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN)
    parser.add_argument("--baseurl", default="https://api2.openreview.net")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        assert choose_code_method(["emailOtp", "passkey"]) == "emailOtp"
        assert choose_code_method(["totp", "emailOtp"]) == "totp"
        print("self-test: ok")
        return
    issue_token(args)


if __name__ == "__main__":
    main()
