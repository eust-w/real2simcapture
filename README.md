# real2simcapture

An iPhone capture and simulation-asset pipeline for robotics developers.

[中文](README.zh-CN.md) · [Setup](docs/SETUP.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Release status](docs/launch/READINESS.zh-CN.md)

**Developer preview.** The complete phone-to-engine workflow still needs physical-device acceptance. No verified public scan dataset is bundled. Repository publication and license approval are pending.

## Capabilities

- Native capture of RGB, LiDAR depth, camera poses, RoomPlan data and ARKit scene meshes.
- Bounded sequential RGB-D uploads and periodic ARKit mesh snapshots during capture, with actual geometry displayed in the Web console.
- Geometry processing, visual/collision asset separation, and MJCF, URDF and USD export.
- Task inspection, physical-parameter provenance, and configured native-engine validation with actual outcomes.

ARKit performs on-device scene reconstruction. Mesh uploads are attempted approximately every two seconds when bandwidth and tracking permit. This is not a guaranteed latency or a photorealistic reconstruction claim. Texture reconstruction and final asset processing are separate. Estimated physical parameters are not measurements.

## Quick Start

Use macOS/Linux, Python 3.11+, and Node.js 22+. Physical capture additionally requires a supported LiDAR device, full Xcode and signing.

```sh
git clone https://github.com/eust-w/real2simcapture.git
cd real2simcapture
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-lock.txt
.venv/bin/python -m pip install --no-deps -e backend
npm --prefix frontend ci
```

Start the API and console in separate terminals:

```sh
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```sh
npm --prefix frontend run dev -- --host 127.0.0.1
```

Open `http://localhost:5173`. For phone access, follow [device setup](docs/SETUP.md). The API currently has no application-level authentication; do not expose it directly to the internet.

## Verification Boundaries

| Area | Status |
| --- | --- |
| API and exports | Automated regression tests using explicitly labeled fixtures |
| Live geometry delivery | Real HTTP upload/download, atomic replacement and version refresh |
| iOS sources | XcodeGen project; compilation and hardware checks tracked separately |
| Phone-to-simulator demonstration | Pending physical-device capture and acceptance footage |
| Photorealistic live reconstruction | Not provided |
| External engines, GPU models and paid APIs | Optional; separately installed, no credentials or binaries bundled |

## Development

```sh
.venv/bin/python -m pytest backend/tests -q -m 'not external'
npm --prefix frontend test
npm --prefix frontend run build
```

External tests require separately installed tools. CI compiles iOS without signing; compilation is not proof of device capture.

`ios/Real2SimCapture` contains native capture, `backend/app` contains processing/export APIs, `frontend/src` contains the React/Three.js workbench, and `scripts` contains external tool adapters. Historical design notes are in [docs](docs/ARCHITECTURE.zh-CN.md).

## Roadmap

1. Verified device capture, licensed real samples and reproducible engine import.
2. Measured latency and long-scan stability on real networks.
3. Better reconstruction quality and object-level editing.
4. Additional tested devices, engines and community datasets.

## Licensing

Project licensing awaits owner confirmation. Third-party SDKs, code, weights and datasets retain their own terms; see [THIRD_PARTY.md](THIRD_PARTY.md). No Apple SDK or proprietary engine is redistributed.
