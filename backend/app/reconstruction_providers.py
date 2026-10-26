from __future__ import annotations

import shutil
import shlex
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx

from .exporters import MESH_EXTENSIONS
from .settings import AppSettings


class ReconstructionProviderError(Exception):
    def __init__(self, reason: str, logs: list[str] | None = None):
        self.reason = reason
        self.logs = logs or []
        super().__init__(reason)


KIRI_PROVIDERS = {"kiri_photo", "kiri_featureless", "kiri_3dgs"}


def reconstruction_health(settings: AppSettings, *, validate_kiri_credentials: bool = False) -> dict[str, Any]:
    providers = {
        "colmap": {
            "available": True,
            "reason": None,
            "required_tools": settings.photogrammetry_required_tools,
        },
        "apple_object_capture": apple_object_capture_health(settings),
        "kiri_photo": kiri_health(settings, "kiri_photo", validate_credentials=validate_kiri_credentials),
        "kiri_featureless": kiri_health(settings, "kiri_featureless", validate_credentials=validate_kiri_credentials),
        "kiri_3dgs": kiri_health(settings, "kiri_3dgs", validate_credentials=validate_kiri_credentials),
    }
    return {"provider": settings.reconstruction_provider, "providers": providers}


def apple_object_capture_health(settings: AppSettings) -> dict[str, Any]:
    command = settings.apple_object_capture_command
    if not command:
        return {"available": False, "reason": "apple_object_capture_command_required"}
    executable = shlex.split(command)[0]
    if Path(executable).is_file() or shutil.which(executable):
        return {"available": True, "reason": None, "command": executable}
    return {"available": False, "reason": "apple_object_capture_command_not_found", "command": executable}


def kiri_health(settings: AppSettings, provider: str, *, validate_credentials: bool = False) -> dict[str, Any]:
    api_key, credential_source = resolve_kiri_api_key(settings)
    if not api_key:
        return {"available": False, "reason": "kiri_api_key_required"}
    health = {
        "available": True,
        "reason": None,
        "base_url": settings.kiri_base_url.rstrip("/"),
        "provider": provider,
        "credential_source": credential_source,
    }
    if not validate_credentials:
        return health
    credential_health = validate_kiri_credentials(settings, api_key)
    return {**health, **credential_health}


def resolve_kiri_api_key(settings: AppSettings) -> tuple[str | None, str | None]:
    if settings.kiri_api_key:
        return settings.kiri_api_key, "settings"
    return read_macos_keychain_secret(settings.kiri_keychain_services)


def read_macos_keychain_secret(services: list[str]) -> tuple[str | None, str | None]:
    security = shutil.which("security")
    if not security:
        return None, None
    for service in services:
        try:
            result = subprocess.run(
                [security, "find-generic-password", "-s", service, "-w"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        secret = result.stdout.strip()
        if result.returncode == 0 and secret:
            return secret, f"keychain:{service}"
    return None, None


def validate_kiri_credentials(settings: AppSettings, api_key: str) -> dict[str, Any]:
    try:
        with httpx.Client(
            base_url=settings.kiri_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=settings.kiri_health_timeout_seconds,
            follow_redirects=True,
        ) as client:
            payload = parse_kiri_response(client.get("/balance"))
    except ReconstructionProviderError as exc:
        reason = "kiri_api_key_invalid" if any("401" in log or "Unauthorized" in log for log in exc.logs) else "kiri_balance_check_failed"
        return {"available": False, "reason": reason}
    except httpx.HTTPError as exc:
        return {"available": False, "reason": "kiri_balance_check_failed", "error": type(exc).__name__}

    balance = payload.get("data", {}).get("balance")
    if not isinstance(balance, (int, float)):
        return {"available": False, "reason": "kiri_balance_missing"}
    if balance <= 0:
        return {"available": False, "reason": "kiri_credit_required", "balance": balance}
    return {"available": True, "reason": None, "balance": balance}


def run_external_reconstruction_provider(
    *,
    provider: str,
    task: dict[str, Any],
    settings: AppSettings,
    images_dir: Path,
    capture_dir: Path,
    work_dir: Path,
    logs: list[str],
) -> Path:
    if provider in KIRI_PROVIDERS:
        return run_kiri_reconstruction(provider, settings, images_dir, work_dir, logs)
    if provider == "apple_object_capture":
        return run_apple_object_capture(settings, images_dir, work_dir, logs)
    raise ReconstructionProviderError("unsupported_reconstruction_provider", [f"unsupported provider: {provider}"])


def run_kiri_reconstruction(provider: str, settings: AppSettings, images_dir: Path, work_dir: Path, logs: list[str]) -> Path:
    api_key, credential_source = resolve_kiri_api_key(settings)
    if not api_key:
        raise ReconstructionProviderError("kiri_api_key_required")
    image_paths = sorted(path for path in images_dir.rglob("*") if path.suffix.lower() in {".jpg", ".jpeg", ".png"})
    if not 20 <= len(image_paths) <= 300:
        raise ReconstructionProviderError("kiri_requires_20_to_300_images", [f"KIRI requires 20-300 images, got {len(image_paths)}."])

    client = httpx.Client(
        base_url=settings.kiri_base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=settings.kiri_timeout_seconds,
        follow_redirects=True,
    )
    try:
        logs.append(f"KIRI credential source={credential_source}")
        serialize = upload_kiri_images(client, provider, settings, image_paths)
        logs.append(f"KIRI upload accepted provider={provider} serialize={serialize}")
        wait_for_kiri_success(client, serialize, settings, logs)
        model_zip = download_kiri_model_zip(client, serialize, work_dir, logs)
    finally:
        client.close()

    extract_dir = work_dir / "kiri_model"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True)
    with zipfile.ZipFile(model_zip) as archive:
        archive.extractall(extract_dir)
    mesh_path = find_first_mesh(extract_dir)
    if mesh_path is None:
        raise ReconstructionProviderError("kiri_model_mesh_missing", [f"No supported mesh found in KIRI zip {model_zip}."])
    return mesh_path


def upload_kiri_images(client: httpx.Client, provider: str, settings: AppSettings, image_paths: list[Path]) -> str:
    endpoint = {
        "kiri_photo": "/photo/image",
        "kiri_featureless": "/featureless/image",
        "kiri_3dgs": "/3dgs/image",
    }[provider]
    data: dict[str, str] = {"fileFormat": settings.kiri_file_format}
    if provider == "kiri_photo":
        data.update(
            {
                "modelQuality": str(settings.kiri_model_quality),
                "textureQuality": str(settings.kiri_texture_quality),
                "isMask": str(settings.kiri_is_mask),
                "textureSmoothing": str(settings.kiri_texture_smoothing),
            }
        )
    elif provider == "kiri_3dgs":
        data.update({"isMesh": "1", "isMask": str(settings.kiri_is_mask)})

    handles = [path.open("rb") for path in image_paths]
    try:
        files = [("imagesFiles", (path.name, handle, content_type_for_image(path))) for path, handle in zip(image_paths, handles)]
        response = client.post(endpoint, data=data, files=files)
    finally:
        for handle in handles:
            handle.close()
    payload = parse_kiri_response(response)
    serialize = payload.get("data", {}).get("serialize")
    if not serialize:
        raise ReconstructionProviderError("kiri_upload_missing_serialize", [str(payload)])
    return str(serialize)


def wait_for_kiri_success(client: httpx.Client, serialize: str, settings: AppSettings, logs: list[str]) -> None:
    deadline = time.monotonic() + settings.kiri_timeout_seconds
    while time.monotonic() < deadline:
        payload = parse_kiri_response(client.get("/model/getStatus", params={"serialize": serialize}))
        status = payload.get("data", {}).get("status")
        logs.append(f"KIRI status serialize={serialize} status={status}")
        if status == 2:
            return
        if status == 1:
            raise ReconstructionProviderError("kiri_reconstruction_failed", [str(payload)])
        time.sleep(settings.kiri_poll_interval_seconds)
    raise ReconstructionProviderError("kiri_reconstruction_timeout", [f"serialize={serialize}"])


def download_kiri_model_zip(client: httpx.Client, serialize: str, work_dir: Path, logs: list[str]) -> Path:
    payload = parse_kiri_response(client.get("/model/getModelZip", params={"serialize": serialize}))
    model_url = payload.get("data", {}).get("modelUrl")
    if not model_url:
        raise ReconstructionProviderError("kiri_model_url_missing", [str(payload)])
    target = work_dir / "kiri_model.zip"
    with httpx.stream("GET", str(model_url), timeout=300, follow_redirects=True) as response:
        response.raise_for_status()
        with target.open("wb") as file:
            for chunk in response.iter_bytes():
                file.write(chunk)
    logs.append(f"KIRI model zip downloaded to {target}")
    return target


def parse_kiri_response(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        raise ReconstructionProviderError("kiri_invalid_json_response", [response.text[:1000]]) from exc
    if response.status_code >= 400 or payload.get("ok") is False or payload.get("code") not in {0, None}:
        raise ReconstructionProviderError("kiri_api_error", [f"status={response.status_code} payload={payload}"])
    return payload


def run_apple_object_capture(settings: AppSettings, images_dir: Path, work_dir: Path, logs: list[str]) -> Path:
    if not settings.apple_object_capture_command:
        raise ReconstructionProviderError("apple_object_capture_command_required")
    output_dir = work_dir / "apple_object_capture"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_mesh = output_dir / "apple_object_capture.obj"
    command_template = settings.apple_object_capture_command
    if "{" in command_template:
        command = shlex.split(
            command_template.format(
                images_dir=str(images_dir),
                output_dir=str(output_dir),
                output_mesh=str(output_mesh),
            )
        )
    else:
        command = [*shlex.split(command_template), str(images_dir), str(output_mesh)]
    executable = command[0]
    if not (Path(executable).is_file() or shutil.which(executable)):
        raise ReconstructionProviderError("apple_object_capture_command_not_found", [executable])
    logs.append(f"running Apple Object Capture command: {' '.join(command)}")
    result = subprocess.run(command, cwd=work_dir, capture_output=True, text=True, timeout=settings.command_timeout_seconds, check=False)
    output = "\n".join(part.strip() for part in [result.stdout, result.stderr] if part.strip())
    if output:
        logs.append(output[-4000:])
    if result.returncode != 0:
        raise ReconstructionProviderError("apple_object_capture_failed", [f"exit={result.returncode}"])
    mesh_path = find_first_mesh(output_dir)
    if mesh_path is None:
        raise ReconstructionProviderError("apple_object_capture_mesh_missing", [str(output_dir)])
    return mesh_path


def find_first_mesh(root: Path) -> Path | None:
    meshes = sorted(path for path in root.rglob("*") if path.suffix.lower() in MESH_EXTENSIONS)
    return meshes[0] if meshes else None


def content_type_for_image(path: Path) -> str:
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if path.suffix.lower() == ".png":
        return "image/png"
    return "application/octet-stream"
