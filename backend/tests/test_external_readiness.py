from pathlib import Path
from importlib import util
import shlex
import subprocess
import pytest

import app.external_readiness as external_readiness
import app.reconstruction_providers as reconstruction_providers
from app.external_readiness import build_external_readiness_report
from app.reconstruction_providers import kiri_health
from app.rgbd_lifting import depth_candidate_ids
from app.simulator_adapters import command_health, simulator_command_context
from app.settings import AppSettings, default_isaacsim_validate_command, default_motrixsim_validate_command


def test_full_external_readiness_reports_missing_real_external_capabilities(tmp_path: Path) -> None:
    settings = AppSettings(database_url=f"sqlite:///{tmp_path / 'real2sim.sqlite3'}")

    report = build_external_readiness_report(settings)

    assert report["ready"] is False
    blockers = "\n".join(report["blockers"])
    assert "kiri_featureless:kiri_api_key_required" in blockers
    assert "apple_object_capture:apple_object_capture_command_required" not in blockers
    assert report["sections"]["reconstruction"]["providers"]["apple_object_capture"]["available"] is True
    if util.find_spec("sam2") is None:
        assert "python:sam2:missing" in blockers
    else:
        assert "sam2:sam2_command_required" not in blockers
        assert report["sections"]["segmentation"]["providers"]["sam2"]["available"] is True
    if settings.motrixsim_validate_command is None:
        assert "motrixsim:motrixsim_command_required" in blockers
        assert report["sections"]["simulators"]["providers"]["motrixsim"]["available"] is False
    assert "isaacsim:isaacsim_command_required" in blockers
    if util.find_spec("genesis") is None:
        assert "genesis:genesis_command_required" in blockers
    else:
        assert report["sections"]["simulators"]["providers"]["genesis"]["available"] is True
        assert report["sections"]["simulators"]["providers"]["genesis"]["builtin"] is True
    assert isinstance(report["sections"]["xcode"]["full_xcode_available"], bool)
    assert "python_environment" in report["sections"]


def test_kiri_health_uses_keychain_secret_without_exposing_value(monkeypatch) -> None:
    monkeypatch.setattr(
        reconstruction_providers,
        "read_macos_keychain_secret",
        lambda services: ("kiri-real-secret", "keychain:REAL2SIM_KIRI_API_KEY"),
    )
    settings = AppSettings(kiri_api_key=None)

    health = kiri_health(settings, "kiri_featureless")

    assert health["available"] is True
    assert health["credential_source"] == "keychain:REAL2SIM_KIRI_API_KEY"
    assert "kiri-real-secret" not in str(health)


def test_full_external_readiness_validates_kiri_credentials(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        reconstruction_providers,
        "validate_kiri_credentials",
        lambda settings, api_key: {"available": False, "reason": "kiri_api_key_invalid"},
    )
    settings = AppSettings(database_url=f"sqlite:///{tmp_path / 'real2sim.sqlite3'}", kiri_api_key="kiri-invalid")

    report = build_external_readiness_report(settings)

    blockers = "\n".join(report["blockers"])
    assert "kiri_featureless:kiri_api_key_invalid" in blockers
    assert "kiri_3dgs:kiri_api_key_invalid" in blockers
    provider = report["sections"]["reconstruction"]["providers"]["kiri_featureless"]
    assert provider["credential_source"] == "settings"
    assert "kiri-invalid" not in str(provider)


def test_configured_external_readiness_accepts_available_runner_commands(tmp_path: Path) -> None:
    runner = tmp_path / "validator"
    runner.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    runner.chmod(0o755)
    settings = AppSettings(
        database_url=f"sqlite:///{tmp_path / 'real2sim.sqlite3'}",
        apple_object_capture_command=f"{runner} '{{images_dir}}' '{{output_mesh}}'",
        sam2_command=f"{runner} '{{output_masks_dir}}'",
        motrixsim_validate_command=f"{runner} '{{mjcf_path}}'",
        isaacsim_validate_command=f"{runner} '{{usd_path}}'",
        genesis_validate_command=f"{runner} '{{manifest_path}}'",
    )

    report = build_external_readiness_report(settings, scope="configured")

    assert report["ready"] is True
    assert report["blockers"] == []
    assert report["sections"]["reconstruction"]["providers"]["apple_object_capture"]["available"] is True
    assert report["sections"]["segmentation"]["providers"]["sam2"]["available"] is True
    assert report["sections"]["simulators"]["configured_count"] == 3


@pytest.mark.external
def test_default_sam2_runner_check_command_is_real() -> None:
    if util.find_spec("sam2") is None:
        pytest.skip("SAM2 is an optional external environment")
    settings = AppSettings()
    argv = [*shlex.split(settings.sam2_command or ""), "--check"]

    result = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)

    assert result.returncode == 0, result.stderr
    assert '"provider": "sam2"' in result.stdout


@pytest.mark.external
def test_default_apple_object_capture_runner_check_command_is_real() -> None:
    import sys
    if sys.platform != "darwin":
        pytest.skip("Apple Object Capture requires macOS")
    settings = AppSettings()
    argv = [*shlex.split(settings.apple_object_capture_command or ""), "--check"]

    result = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)

    assert result.returncode == 0, result.stderr
    assert '"provider": "apple_object_capture"' in result.stdout


@pytest.mark.external
def test_default_motrixsim_validator_check_command_is_real_when_real2motrix_exists() -> None:
    settings = AppSettings()
    if not settings.motrixsim_validate_command:
        pytest.skip("Real2Motrix is not configured")
    argv = [*shlex.split(settings.motrixsim_validate_command.format(package_dir="/tmp")), "--check"]

    result = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)

    assert result.returncode == 0, result.stderr
    assert '"provider": "motrixsim"' in result.stdout


def test_default_motrixsim_validator_uses_full_ssh_command(monkeypatch) -> None:
    monkeypatch.setenv("REAL2SIM_MOTRIXSIM_SSH_COMMAND", "ssh -i /tmp/key root@example")

    command = default_motrixsim_validate_command()

    assert command is not None
    assert "motrixsim_ssh_validate.py" in command


def test_default_isaacsim_validator_uses_explicit_isaacsim_python(monkeypatch, tmp_path: Path) -> None:
    fake_python = tmp_path / "isaacsim-python"
    fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)
    monkeypatch.setenv("REAL2SIM_ISAACSIM_PYTHON", str(fake_python))

    command = default_isaacsim_validate_command()

    assert command is not None
    assert str(fake_python) in command
    assert "isaacsim_validate.py" in command
    assert "--package-dir {package_dir}" in command


def test_default_isaacsim_validator_uses_ssh_target(monkeypatch) -> None:
    monkeypatch.delenv("REAL2SIM_ISAACSIM_SSH_COMMAND", raising=False)
    monkeypatch.delenv("REAL2SIM_ISAACSIM_PYTHON", raising=False)
    monkeypatch.delenv("ISAACSIM_PYTHON", raising=False)
    monkeypatch.setenv("REAL2SIM_ISAACSIM_SSH_TARGET", "isaac-host")

    command = default_isaacsim_validate_command()

    assert command is not None
    assert "isaacsim_ssh_validate.py" in command
    assert "--package-dir {package_dir}" in command


def test_default_isaacsim_validator_uses_full_ssh_command(monkeypatch) -> None:
    monkeypatch.delenv("REAL2SIM_ISAACSIM_PYTHON", raising=False)
    monkeypatch.delenv("ISAACSIM_PYTHON", raising=False)
    monkeypatch.delenv("REAL2SIM_ISAACSIM_SSH_TARGET", raising=False)
    monkeypatch.setenv("REAL2SIM_ISAACSIM_SSH_COMMAND", "ssh -i /tmp/key root@example")

    command = default_isaacsim_validate_command()

    assert command is not None
    assert "isaacsim_ssh_validate.py" in command


def test_simulator_command_health_runs_check_for_known_validator(tmp_path: Path) -> None:
    validator = tmp_path / "isaacsim_validate.py"
    validator.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "raise SystemExit(0 if '--check' in sys.argv else 1)\n",
        encoding="utf-8",
    )
    validator.chmod(0o755)
    command = f"{shlex.quote(str(validator))} --package-dir {{package_dir}}"

    health = command_health("isaacsim", command, validate_command=True)

    assert health["available"] is True
    assert health["check_attempted"] is True


def test_sam2_mask_stem_matches_source_depth_frame() -> None:
    assert depth_candidate_ids("frame_001_sam2_003") == ["frame_001_sam2_003", "frame_001"]


def test_full_external_readiness_reports_python_environment_blocker(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(external_readiness, "python_environment_readiness", lambda: {"valid": False, "reason": "pip_check_failed"})
    settings = AppSettings(database_url=f"sqlite:///{tmp_path / 'real2sim.sqlite3'}")

    report = build_external_readiness_report(settings)

    assert "python_environment:pip_check_failed" in report["blockers"]


def test_simulator_command_context_uses_absolute_package_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    relative_output_dir = Path("outputs") / "task-001"
    relative_output_dir.mkdir(parents=True)

    context = simulator_command_context("genesis", relative_output_dir)

    for key in ["package_dir", "mjcf_path", "urdf_path", "usd_path", "usdz_path", "manifest_path", "scene_json_path", "zip_path"]:
        assert Path(context[key]).is_absolute()
