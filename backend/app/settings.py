from __future__ import annotations

import shlex
import sys
from importlib import util
from os import environ
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_sam2_command() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    runner = repo_root / "scripts" / "sam2_generate_masks.py"
    return (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(runner))} "
        "--capture-dir {capture_dir} --images-dir {images_dir} --output-masks-dir {output_masks_dir}"
    )


def default_apple_object_capture_command() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    runner = repo_root / "scripts" / "apple_object_capture.py"
    return (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(runner))} "
        "--images-dir {images_dir} --output-dir {output_dir} --output-mesh {output_mesh}"
    )


def default_motrixsim_validate_command() -> str | None:
    repo_root = Path(__file__).resolve().parents[2]
    if environ.get("REAL2SIM_MOTRIXSIM_SSH_COMMAND") or environ.get("REAL2SIM_MOTRIXSIM_SSH_TARGET"):
        runner = repo_root / "scripts" / "motrixsim_ssh_validate.py"
        return f"{shlex.quote(sys.executable)} {shlex.quote(str(runner))} --package-dir {{package_dir}}"
    configured_dir = environ.get("REAL2MOTRIX_DIR")
    if not configured_dir:
        return None
    real2motrix_dir = Path(configured_dir).expanduser()
    real2motrix_python = real2motrix_dir / ".venv" / "bin" / "python"
    if not real2motrix_python.is_file():
        return None
    runner = repo_root / "scripts" / "validate_with_real2motrix.py"
    return (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(runner))} "
        f"--real2motrix-dir {shlex.quote(str(real2motrix_dir))} --package-dir {{package_dir}}"
    )


def default_isaacsim_validate_command() -> str | None:
    repo_root = Path(__file__).resolve().parents[2]
    if environ.get("REAL2SIM_ISAACSIM_SSH_COMMAND") or environ.get("REAL2SIM_ISAACSIM_SSH_TARGET"):
        runner = repo_root / "scripts" / "isaacsim_ssh_validate.py"
        return f"{shlex.quote(sys.executable)} {shlex.quote(str(runner))} --package-dir {{package_dir}}"
    isaacsim_python = discover_isaacsim_python()
    if not isaacsim_python:
        return None
    runner = repo_root / "scripts" / "isaacsim_validate.py"
    return f"{shlex.quote(isaacsim_python)} {shlex.quote(str(runner))} --package-dir {{package_dir}}"


def discover_isaacsim_python() -> str | None:
    for env_name in ["REAL2SIM_ISAACSIM_PYTHON", "ISAACSIM_PYTHON"]:
        value = environ.get(env_name)
        if value and Path(value).is_file():
            return value
    if util.find_spec("isaacsim") is not None:
        return sys.executable
    for candidate in [
        Path.home() / "isaacsim" / "python.sh",
        Path("/opt/isaacsim/python.sh"),
        Path("/isaac-sim/python.sh"),
        Path("/workspace/isaac-sim/python.sh"),
    ]:
        if candidate.is_file():
            return str(candidate)
    return None


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REAL2SIM_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///data/real2sim.sqlite3"
    database_connect_timeout_seconds: int = 3
    data_dir: Path = Path("data")
    output_dir: Path = Path("outputs")
    public_base_url: str = "http://localhost:8000"
    default_density_kg_m3: float = 700.0
    default_friction: float = 0.6
    capture_min_frames: int = 12
    capture_min_usable_frames: int = 8
    capture_blur_variance_threshold: float = 100.0
    capture_min_exposure_mean: float = 25.0
    capture_max_exposure_mean: float = 230.0
    capture_max_clipped_ratio: float = 0.25
    capture_min_coverage_degrees: float = 120.0
    capture_require_scale_reference: bool = False
    reconstruction_provider: str = "colmap"
    kiri_api_key: str | None = None
    kiri_base_url: str = "https://api.kiriengine.app/api/v1/open"
    kiri_file_format: str = "OBJ"
    kiri_model_quality: int = 1
    kiri_texture_quality: int = 1
    kiri_is_mask: int = 1
    kiri_texture_smoothing: int = 1
    kiri_poll_interval_seconds: float = 10.0
    kiri_timeout_seconds: int = 60 * 60
    kiri_health_timeout_seconds: float = 15.0
    kiri_keychain_services: list[str] = Field(
        default_factory=lambda: ["REAL2SIM_KIRI_API_KEY", "KIRI_API_KEY", "KIRI_ENGINE_API_KEY"]
    )
    apple_object_capture_command: str | None = Field(default_factory=default_apple_object_capture_command)
    segmentation_provider: str = "rgbd_masks"
    sam2_command: str | None = Field(default_factory=default_sam2_command)
    motrixsim_validate_command: str | None = Field(default_factory=default_motrixsim_validate_command)
    isaacsim_validate_command: str | None = Field(default_factory=default_isaacsim_validate_command)
    genesis_validate_command: str | None = None
    simulator_validation_timeout_seconds: int = 300
    storage_backend: str = "local"
    storage_dir: Path = Path("artifacts")
    s3_public_base_url: str | None = None
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    queue_backend: str = "local"
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_queue_name: str = "real2sim:tasks"
    command_timeout_seconds: int = 60 * 60
    photogrammetry_required_tools: list[str] = Field(
        default_factory=lambda: [
            "colmap",
            "InterfaceCOLMAP",
            "DensifyPointCloud",
            "ReconstructMesh",
            "TextureMesh",
        ]
    )
    dependency_tools: list[str] = Field(
        default_factory=lambda: [
            "colmap",
            "InterfaceCOLMAP",
            "DensifyPointCloud",
            "ReconstructMesh",
            "TextureMesh",
            "blender",
            "ffmpeg",
            "python:mujoco",
        ]
    )

    @property
    def sqlite_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("Only sqlite:/// database_url is supported by the local backend runner.")
        return Path(self.database_url[len(prefix) :])
