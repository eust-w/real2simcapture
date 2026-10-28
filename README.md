# real2simcapture

An iPhone capture and simulation-asset pipeline for robotics developers.

[中文](README.zh-CN.md) · [Setup](docs/SETUP.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Releases](https://github.com/eust-w/real2simcapture/releases)

**Apache-2.0 open-source developer preview.** The complete phone-to-engine workflow still needs physical-device acceptance. No verified public scan dataset or signed iPhone app is bundled.

[![Verify](https://github.com/eust-w/real2simcapture/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/eust-w/real2simcapture/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)

![Developer-preview project introduction, not device footage](docs/launch/assets/preview-cover.png)

[Watch/download the 65-second introduction](https://github.com/eust-w/real2simcapture/releases/download/v0.1.0-alpha.1/real2simcapture-intro-landscape.mp4) · [Portrait video](https://github.com/eust-w/real2simcapture/releases/download/v0.1.0-alpha.1/real2simcapture-intro-portrait.mp4) · [Subtitles and production notes](docs/launch/PUBLISHING.zh-CN.md). Actual source excerpts and an empty workbench, not device footage or fabricated scan results. Synthesized Mandarin narration; Chinese and English subtitle files are included in the release.

Watch on [YouTube](https://www.youtube.com/watch?v=tMlDCd1nMvA) (Chinese and English captions), [Bilibili](https://www.bilibili.com/video/BV1S9xT6zEYd/), or [Douyin](https://www.douyin.com/video/7701264760116923690). Public pages and playback verified on October 27, 2026. Xiaohongshu publication is blocked by an account restriction; its draft is not a public post.

Also on [X](https://x.com/eustancewu/status/2115537584411873510): native video, English post, Chinese captions and AI-content disclosure. Post and playback verified on October 29, 2026.

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
| iOS sources | Unsigned physical-device target compiled in macOS CI; signing and hardware checks pending |
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

The project's original code and documentation are licensed under [Apache-2.0](LICENSE). See [NOTICE](NOTICE) for attribution. Third-party SDKs, code, weights and datasets retain their own terms; see [THIRD_PARTY.md](THIRD_PARTY.md). No Apple SDK, model weights or proprietary engine is redistributed.
