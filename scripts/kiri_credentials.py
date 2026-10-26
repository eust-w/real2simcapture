#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.reconstruction_providers import resolve_kiri_api_key, validate_kiri_credentials  # noqa: E402
from app.settings import AppSettings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Store and verify real KIRI Engine credentials without printing secrets.")
    parser.add_argument("--check", action="store_true", help="Resolve the API key and call KIRI /balance.")
    parser.add_argument("--store-keychain", action="store_true", help="Read an API key from stdin and store it in macOS Keychain.")
    parser.add_argument("--service", default="REAL2SIM_KIRI_API_KEY")
    parser.add_argument("--account", default="real2sim")
    args = parser.parse_args()

    try:
        if args.store_keychain:
            store_keychain_secret(args.service, args.account, sys.stdin.read().strip())
        if args.check:
            result = check_credentials()
        elif args.store_keychain:
            result = {"ok": True, "stored": True, "service": args.service, "account": args.account}
        else:
            raise ValueError("Use --check, --store-keychain, or both.")
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


def store_keychain_secret(service: str, account: str, secret: str) -> None:
    if not secret:
        raise ValueError("api_key_stdin_required")
    security = shutil.which("security")
    if not security:
        raise FileNotFoundError("security_cli_required")
    completed = subprocess.run(
        [security, "add-generic-password", "-s", service, "-a", account, "-w", secret, "-U"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        output = "\n".join(part.strip() for part in [completed.stdout, completed.stderr] if part.strip())
        raise RuntimeError(f"keychain_store_failed:{completed.returncode}:{output[-1000:]}")


def check_credentials() -> dict[str, object]:
    settings = AppSettings()
    api_key, credential_source = resolve_kiri_api_key(settings)
    if not api_key:
        return {"ok": False, "available": False, "reason": "kiri_api_key_required"}
    health = validate_kiri_credentials(settings, api_key)
    return {
        "ok": bool(health.get("available")),
        "available": bool(health.get("available")),
        "reason": health.get("reason"),
        "credential_source": credential_source,
        "balance": health.get("balance"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
