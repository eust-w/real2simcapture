from __future__ import annotations

import shutil
import subprocess
from importlib import metadata, util
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    available: bool
    path: str | None
    version: str | None

    def to_dict(self) -> dict[str, str | bool | None]:
        return asdict(self)


def check_tool(name: str, timeout_seconds: int = 8) -> DependencyStatus:
    if name.startswith("python:"):
        package_name = name.split(":", 1)[1]
        spec = util.find_spec(package_name)
        version = None
        if spec is not None:
            try:
                version = metadata.version(package_name)
            except metadata.PackageNotFoundError:
                version = "installed"
        return DependencyStatus(name=name, available=spec is not None, path=spec.origin if spec else None, version=version)

    path = shutil.which(name)
    if not path:
        return DependencyStatus(name=name, available=False, path=None, version=None)

    version = None
    for args in ([path, "--version"], [path, "-version"], [path]):
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=timeout_seconds, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        output = "\n".join(part.strip() for part in [result.stdout, result.stderr] if part.strip())
        if output:
            version = output.splitlines()[0][:240]
            break

    return DependencyStatus(name=name, available=True, path=path, version=version)


def check_dependencies(names: list[str], timeout_seconds: int = 8) -> dict[str, dict[str, str | bool | None]]:
    return {name: check_tool(name, timeout_seconds).to_dict() for name in names}


def missing_tools(names: list[str]) -> list[str]:
    return [name for name in names if shutil.which(name) is None]
