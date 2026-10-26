#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path


REMOTE_VALIDATOR = r"""
from pathlib import Path
import json
import os
import sys

import motrixsim as mtx

package_dir = Path(sys.argv[1]).resolve()
steps = int(sys.argv[2])
scene_xml = package_dir / "scene.xml"
if not scene_xml.is_file():
    raise FileNotFoundError(str(scene_xml))
os.chdir(package_dir)
model = mtx.load_model("scene.xml")
data = mtx.SceneData(model)
for _ in range(max(steps, 1)):
    mtx.step(model, data)
print(json.dumps({"ok": True, "provider": "motrixsim", "scene_xml": "scene.xml", "steps": max(steps, 1)}), flush=True)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Real2Sim package on a real remote MotrixSim host over SSH.")
    parser.add_argument("--package-dir")
    parser.add_argument("--ssh-command", default=os.environ.get("REAL2SIM_MOTRIXSIM_SSH_COMMAND"))
    parser.add_argument("--ssh-target", default=os.environ.get("REAL2SIM_MOTRIXSIM_SSH_TARGET"))
    parser.add_argument("--remote-python", default=os.environ.get("REAL2SIM_MOTRIXSIM_REMOTE_PYTHON", "/opt/motrixlab/venv/bin/python"))
    parser.add_argument("--remote-repo", default=os.environ.get("REAL2SIM_MOTRIXSIM_REMOTE_REPO", "/opt/motrixlab/repo"))
    parser.add_argument("--remote-root", default=os.environ.get("REAL2SIM_MOTRIXSIM_REMOTE_ROOT", "/tmp/real2sim-motrixsim"))
    parser.add_argument("--steps", type=int, default=10)
    parser.add_argument("--keep-remote", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    try:
        ssh_base = resolve_ssh_base(args)
        if args.check:
            result = run_remote_check(args, ssh_base)
        else:
            result = run_remote_validation(args, ssh_base)
    except Exception as exc:
        print(json.dumps({"ok": False, "provider": "motrixsim", "mode": "ssh", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


def resolve_ssh_base(args: argparse.Namespace) -> list[str]:
    if args.ssh_command:
        base = shlex.split(args.ssh_command)
    elif args.ssh_target:
        base = ["ssh", args.ssh_target]
    else:
        raise ValueError("motrixsim_ssh_target_required")
    if not base:
        raise ValueError("motrixsim_ssh_command_required")
    if shutil.which(base[0]) is None:
        raise FileNotFoundError(f"{base[0]}_required")
    return base


def run_remote_check(args: argparse.Namespace, ssh_base: list[str]) -> dict[str, object]:
    script = """
import json
import motrixsim as mtx
print(json.dumps({"ok": True, "provider": "motrixsim", "mode": "ssh-check", "has_load_model": hasattr(mtx, "load_model")}), flush=True)
"""
    command = f"cd {shlex.quote(args.remote_repo)} && {shlex.quote(args.remote_python)} -"
    completed = ssh_run(ssh_base, command, input_data=script.encode("utf-8"), timeout=120)
    if completed.returncode != 0:
        raise RuntimeError(f"remote_motrixsim_check_failed:{completed.returncode}:{combined_output(completed)[-4000:]}")
    payload = parse_last_json_line(completed.stdout)
    return {"ok": True, "provider": "motrixsim", "mode": "ssh-check", "remote": "configured", "remote_result": payload}


def run_remote_validation(args: argparse.Namespace, ssh_base: list[str]) -> dict[str, object]:
    if not args.package_dir:
        raise ValueError("--package-dir is required")
    package_dir = Path(args.package_dir).resolve()
    if not package_dir.is_dir():
        raise FileNotFoundError(str(package_dir))

    run_id = uuid.uuid4().hex
    remote_base = f"{args.remote_root.rstrip('/')}/{run_id}"
    remote_package = f"{remote_base}/package"
    remote_script = f"{remote_base}/validate_motrixsim.py"
    ssh_run(ssh_base, f"mkdir -p {shlex.quote(remote_package)}", timeout=30, check=True)
    upload_text(ssh_base, REMOTE_VALIDATOR, remote_script)
    upload_package(ssh_base, package_dir, remote_package)
    command = (
        f"cd {shlex.quote(args.remote_repo)} && {shlex.quote(args.remote_python)} "
        f"{shlex.quote(remote_script)} {shlex.quote(remote_package)} {int(args.steps)}"
    )
    completed = ssh_run(ssh_base, command, timeout=300)
    try:
        if completed.returncode != 0:
            raise RuntimeError(f"remote_motrixsim_validation_failed:{completed.returncode}:{combined_output(completed)[-4000:]}")
        payload = parse_last_json_line(completed.stdout)
        return {"ok": True, "provider": "motrixsim", "mode": "ssh", "remote": "configured", "remote_result": payload}
    finally:
        if not args.keep_remote:
            ssh_run(ssh_base, f"rm -rf {shlex.quote(remote_base)}", timeout=30)


def upload_text(ssh_base: list[str], value: str, remote_path: str) -> None:
    command = f"cat > {shlex.quote(remote_path)} && chmod +x {shlex.quote(remote_path)}"
    completed = ssh_run(ssh_base, command, input_data=value.encode("utf-8"), timeout=60)
    if completed.returncode != 0:
        raise RuntimeError(f"remote_file_upload_failed:{completed.returncode}:{combined_output(completed)[-2000:]}")


def upload_package(ssh_base: list[str], package_dir: Path, remote_package: str) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in sorted(package_dir.rglob("*")):
            archive.add(path, arcname=path.relative_to(package_dir))
    completed = ssh_run(ssh_base, f"tar -xzf - -C {shlex.quote(remote_package)}", input_data=buffer.getvalue(), timeout=300)
    if completed.returncode != 0:
        raise RuntimeError(f"remote_package_upload_failed:{completed.returncode}:{combined_output(completed)[-2000:]}")


def ssh_run(
    ssh_base: list[str],
    remote_command: str,
    *,
    input_data: bytes | None = None,
    timeout: int | None,
    check: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(
        [*ssh_base, remote_command],
        input=input_data,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(f"ssh_failed:{completed.returncode}:{combined_output(completed)[-2000:]}")
    return completed


def combined_output(result: subprocess.CompletedProcess[bytes]) -> str:
    parts = []
    for value in [result.stdout, result.stderr]:
        if value:
            parts.append(value.decode("utf-8", errors="replace").strip())
    return "\n".join(part for part in parts if part)


def parse_last_json_line(output: bytes) -> object:
    text = output.decode("utf-8", errors="replace")
    for line in reversed([line.strip() for line in text.splitlines() if line.strip()]):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise ValueError(f"remote_json_output_missing:{text[-1000:]}")


if __name__ == "__main__":
    raise SystemExit(main())
