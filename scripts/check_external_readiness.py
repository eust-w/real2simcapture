from __future__ import annotations

import argparse
import json
import sys

from app.external_readiness import build_external_readiness_report
from app.settings import AppSettings


def main() -> int:
    parser = argparse.ArgumentParser(description="Check real external Real2Sim capability readiness.")
    parser.add_argument("--scope", choices=["full", "configured"], default="full")
    parser.add_argument("--output", choices=["json", "text"], default="json")
    args = parser.parse_args()

    report = build_external_readiness_report(AppSettings(), scope=args.scope)
    if args.output == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"ready={str(report['ready']).lower()} scope={report['scope']}")
        for blocker in report["blockers"]:
            print(f"blocker={blocker}")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
