from __future__ import annotations

import json
import shutil
import subprocess
import sys
from importlib import util
from pathlib import Path
from typing import Any

from .reconstruction_providers import reconstruction_health
from .segmentation import segmentation_health
from .settings import AppSettings
from .simulator_adapters import simulator_adapters_health


FULL_REQUIRED_RECONSTRUCTION_PROVIDERS = ["kiri_featureless", "kiri_3dgs", "apple_object_capture"]
FULL_REQUIRED_SEGMENTATION_PROVIDERS = ["sam2"]
FULL_REQUIRED_SIMULATORS = ["motrixsim", "isaacsim", "genesis"]
FULL_REQUIRED_PYTHON_PACKAGES = ["mujoco", "sam2", "segment_anything", "groundingdino", "genesis"]


def build_external_readiness_report(settings: AppSettings, scope: str = "full") -> dict[str, Any]:
    if scope not in {"full", "configured"}:
        raise ValueError("scope must be 'full' or 'configured'")
    reconstruction = reconstruction_health(settings, validate_kiri_credentials=scope == "full")
    segmentation = segmentation_health(settings)
    simulators = simulator_adapters_health(settings, validate_commands=scope == "full")
    xcode = xcode_readiness()
    python_packages = python_package_readiness(FULL_REQUIRED_PYTHON_PACKAGES)
    python_environment = python_environment_readiness()

    blockers: list[str] = []
    if scope == "full":
        blockers.extend(required_provider_blockers(reconstruction["providers"], FULL_REQUIRED_RECONSTRUCTION_PROVIDERS))
        blockers.extend(required_provider_blockers(segmentation["providers"], FULL_REQUIRED_SEGMENTATION_PROVIDERS))
        blockers.extend(required_provider_blockers(simulators["providers"], FULL_REQUIRED_SIMULATORS))
        if not xcode["full_xcode_available"]:
            blockers.append(f"xcode:{xcode['reason']}")
        for package_name in FULL_REQUIRED_PYTHON_PACKAGES:
            if not python_packages[package_name]["available"]:
                blockers.append(f"python:{package_name}:missing")
        if not python_environment["valid"]:
            blockers.append(f"python_environment:{python_environment['reason']}")
    else:
        blockers.extend(configured_provider_blockers(reconstruction["providers"]))
        blockers.extend(configured_provider_blockers(segmentation["providers"]))
        blockers.extend(configured_provider_blockers(simulators["providers"]))

    return {
        "ready": not blockers,
        "scope": scope,
        "blockers": blockers,
        "sections": {
            "reconstruction": reconstruction,
            "segmentation": segmentation,
            "simulators": simulators,
            "xcode": xcode,
            "python_packages": python_packages,
            "python_environment": python_environment,
        },
    }


def required_provider_blockers(providers: dict[str, dict[str, Any]], provider_names: list[str]) -> list[str]:
    blockers: list[str] = []
    for name in provider_names:
        provider = providers.get(name, {})
        if not provider.get("available"):
            blockers.append(f"{name}:{provider.get('reason') or 'unavailable'}")
    return blockers


def configured_provider_blockers(providers: dict[str, dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for name, provider in providers.items():
        is_configured = bool(
            provider.get("command_configured")
            or provider.get("command")
            or provider.get("base_url")
            or provider.get("provider") in {"kiri_photo", "kiri_featureless", "kiri_3dgs"}
        )
        if is_configured and not provider.get("available"):
            blockers.append(f"{name}:{provider.get('reason') or 'unavailable'}")
    return blockers


def xcode_readiness() -> dict[str, Any]:
    developer_dir = command_stdout(["xcode-select", "-p"])
    full_xcode_available = bool(developer_dir and developer_dir.endswith("/Contents/Developer"))
    simctl = command_stdout(["xcrun", "-find", "simctl"]) if full_xcode_available else None
    xcodebuild = shutil.which("xcodebuild")
    if not developer_dir:
        reason = "xcode_select_unavailable"
    elif not full_xcode_available:
        reason = "active_developer_dir_is_command_line_tools"
    elif not simctl:
        reason = "simctl_unavailable"
    else:
        reason = None
    return {
        "full_xcode_available": full_xcode_available and bool(simctl),
        "developer_dir": developer_dir,
        "xcodebuild": xcodebuild,
        "simctl": simctl,
        "reason": reason,
    }


def python_package_readiness(package_names: list[str]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for package_name in package_names:
        spec = util.find_spec(package_name)
        results[package_name] = {"available": spec is not None, "path": spec.origin if spec else None}
    return results


def python_environment_readiness() -> dict[str, Any]:
    command = [sys.executable, "-m", "pip", "check"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "valid": False,
            "reason": "pip_check_unavailable",
            "command": " ".join(command),
            "stdout": "",
            "stderr": str(exc),
        }
    output = "\n".join(part.strip() for part in [result.stdout, result.stderr] if part.strip())
    return {
        "valid": result.returncode == 0,
        "reason": None if result.returncode == 0 else "pip_check_failed",
        "command": " ".join(command),
        "output": output[-4000:],
    }


def command_stdout(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = result.stdout.strip()
    return output or None


def readiness_json(settings: AppSettings, scope: str = "full") -> str:
    return json.dumps(build_external_readiness_report(settings, scope=scope), ensure_ascii=False, indent=2)
