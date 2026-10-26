from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
import time
from importlib import util
from pathlib import Path
from typing import Any

from .settings import AppSettings


SIMULATOR_COMMAND_FIELDS = {
    "motrixsim": "motrixsim_validate_command",
    "isaacsim": "isaacsim_validate_command",
    "genesis": "genesis_validate_command",
}

CHECKABLE_VALIDATOR_NAMES = {
    "validate_with_real2motrix.py",
    "motrixsim_ssh_validate.py",
    "isaacsim_validate.py",
    "isaacsim_ssh_validate.py",
}


def simulator_adapters_health(settings: AppSettings, *, validate_commands: bool = False) -> dict[str, Any]:
    providers = {
        simulator: command_health(simulator, getattr(settings, field), validate_command=validate_commands)
        for simulator, field in SIMULATOR_COMMAND_FIELDS.items()
    }
    return {
        "providers": providers,
        "configured_count": sum(1 for provider in providers.values() if provider["command_configured"]),
    }


def run_native_simulator_validations(settings: AppSettings, output_dir: Path) -> dict[str, Any]:
    providers = {
        simulator: run_simulator_validation(
            simulator=simulator,
            command_template=getattr(settings, field),
            output_dir=output_dir,
            timeout_seconds=settings.simulator_validation_timeout_seconds,
        )
        for simulator, field in SIMULATOR_COMMAND_FIELDS.items()
    }
    configured = [provider for provider in providers.values() if provider["command_configured"]]
    return {
        "valid": bool(configured) and all(provider["valid"] for provider in configured),
        "configured_count": len(configured),
        **providers,
    }


def command_health(simulator: str, command_template: str | None, *, validate_command: bool = False) -> dict[str, Any]:
    if not command_template:
        if simulator == "genesis" and util.find_spec("genesis") is not None:
            return {
                "available": True,
                "command_configured": False,
                "builtin": True,
                "reason": None,
                "executable": "python:genesis",
            }
        return {
            "available": False,
            "command_configured": False,
            "builtin": False,
            "reason": f"{simulator}_command_required",
            "executable": None,
        }
    try:
        executable = shlex.split(command_template)[0]
    except ValueError as exc:
        return {
            "available": False,
            "command_configured": True,
            "builtin": False,
            "reason": f"invalid_command: {exc}",
            "executable": None,
        }
    resolved = resolve_executable(executable)
    health = {
        "available": resolved is not None,
        "command_configured": True,
        "builtin": False,
        "reason": None if resolved else f"{executable}_not_found",
        "executable": resolved,
    }
    if validate_command and resolved and command_supports_check(command_template):
        return validator_check_health(simulator, command_template, health)
    return health


def command_supports_check(command_template: str) -> bool:
    try:
        argv = shlex.split(command_template)
    except ValueError:
        return False
    return any(Path(arg).name in CHECKABLE_VALIDATOR_NAMES for arg in argv)


def validator_check_health(simulator: str, command_template: str, base_health: dict[str, Any]) -> dict[str, Any]:
    try:
        command = command_template.format(**simulator_command_context(simulator, Path.cwd()))
        argv = [*shlex.split(command), "--check"]
    except (KeyError, ValueError) as exc:
        return {**base_health, "available": False, "reason": f"invalid_command: {exc}", "check_attempted": False}
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            **base_health,
            "available": False,
            "reason": f"{simulator}_check_failed",
            "check_attempted": True,
            "check_stdout": "",
            "check_stderr": trim_output(str(exc)),
        }
    if completed.returncode != 0:
        return {
            **base_health,
            "available": False,
            "reason": f"{simulator}_check_failed",
            "check_attempted": True,
            "check_stdout": trim_output(completed.stdout),
            "check_stderr": trim_output(completed.stderr),
        }
    return {
        **base_health,
        "available": True,
        "reason": None,
        "check_attempted": True,
        "check_stdout": trim_output(completed.stdout),
        "check_stderr": trim_output(completed.stderr),
    }


def run_simulator_validation(
    *,
    simulator: str,
    command_template: str | None,
    output_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    health = command_health(simulator, command_template)
    result: dict[str, Any] = {
        **health,
        "attempted": False,
        "valid": False,
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "duration_seconds": 0.0,
    }
    if not command_template and health.get("builtin") and simulator == "genesis":
        return run_builtin_genesis_validation(output_dir, result)
    if not command_template or not health["available"]:
        return result

    context = simulator_command_context(simulator, output_dir)
    try:
        command = command_template.format(**context)
        argv = shlex.split(command)
    except (KeyError, ValueError) as exc:
        return {**result, "reason": f"invalid_command: {exc}"}

    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        valid = completed.returncode == 0
        return {
            **result,
            "attempted": True,
            "valid": valid,
            "exit_code": completed.returncode,
            "stdout": trim_output(completed.stdout),
            "stderr": trim_output(completed.stderr),
            "duration_seconds": round(time.monotonic() - started, 3),
            "reason": None if valid else f"{simulator}_validation_failed",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            **result,
            "attempted": True,
            "exit_code": None,
            "stdout": trim_output(exc.stdout or ""),
            "stderr": trim_output(exc.stderr or ""),
            "duration_seconds": round(time.monotonic() - started, 3),
            "reason": f"{simulator}_validation_timeout",
        }
    except OSError as exc:
        return {**result, "attempted": True, "duration_seconds": round(time.monotonic() - started, 3), "reason": str(exc)}


def simulator_command_context(simulator: str, output_dir: Path) -> dict[str, str]:
    output_dir = output_dir.resolve()
    return {
        "simulator": simulator,
        "package_dir": str(output_dir),
        "mjcf_path": str(output_dir / "scene.xml"),
        "urdf_path": str(output_dir / "scene.urdf"),
        "usd_path": str(output_dir / "scene.usd"),
        "usdz_path": str(output_dir / "scene.usdz"),
        "manifest_path": str(output_dir / "manifest.json"),
        "scene_json_path": str(output_dir / "scene.json"),
        "zip_path": str(output_dir / "real2sim_package.zip"),
    }


def run_builtin_genesis_validation(output_dir: Path, base_result: dict[str, Any]) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    started = time.monotonic()
    script = """
from pathlib import Path
import sys
import genesis as gs

output_dir = Path(sys.argv[1])
gs.init(backend=gs.cpu, logging_level="warning")
scene = gs.Scene(show_viewer=False)
scene.add_entity(gs.morphs.MJCF(file=str(output_dir / "scene.xml")))
scene.build()
for _ in range(10):
    scene.step()
print("genesis_builtin_step_valid steps=10")
"""
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script, str(output_dir)],
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if completed.returncode != 0:
            return {
                **base_result,
                "attempted": True,
                "valid": False,
                "exit_code": completed.returncode,
                "stdout": trim_output(completed.stdout),
                "stderr": trim_output(completed.stderr),
                "duration_seconds": round(time.monotonic() - started, 3),
                "reason": "genesis_builtin_validation_failed",
            }
        return {
            **base_result,
            "attempted": True,
            "valid": True,
            "exit_code": 0,
            "stdout": trim_output(completed.stdout),
            "stderr": trim_output(completed.stderr),
            "duration_seconds": round(time.monotonic() - started, 3),
            "steps": 10,
            "reason": None,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            **base_result,
            "attempted": True,
            "valid": False,
            "exit_code": None,
            "stdout": trim_output(exc.stdout or ""),
            "stderr": trim_output(exc.stderr or ""),
            "duration_seconds": round(time.monotonic() - started, 3),
            "reason": "genesis_builtin_validation_timeout",
        }
    except Exception as exc:
        return {
            **base_result,
            "attempted": True,
            "valid": False,
            "exit_code": 1,
            "stderr": trim_output(f"{type(exc).__name__}: {exc}"),
            "duration_seconds": round(time.monotonic() - started, 3),
            "reason": "genesis_builtin_validation_failed",
        }


def resolve_executable(executable: str) -> str | None:
    path = Path(executable)
    if path.is_absolute() and path.is_file():
        return str(path)
    return shutil.which(executable)


def trim_output(value: str, limit: int = 4000) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[-limit:]
