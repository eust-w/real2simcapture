# Workstation And iPhone Setup

Use macOS/Linux, Python 3.11+ and Node.js 22+. Install the pinned core environment as shown in [README](../README.md); install optional reconstruction tools separately.

Install FFmpeg for video input and the video regression tests (`brew install ffmpeg` on macOS, or your Linux package manager). Vite development and preview servers proxy `/api` to port 8000. For a separate API host, set `VITE_API_BASE_URL` before starting/building the frontend. HTML responses from a misconfigured proxy are reported as configuration errors.

## Physical Device

1. Install full Xcode compatible with the Mac and iPhone iOS version. `xcodebuild -version` must report Xcode, not Command Line Tools. XcodeGen alone cannot build an app.
2. Install XcodeGen, run `xcodegen generate` in `ios/Real2SimCapture`, and open the generated project.
3. Choose your development team and a bundle identifier you control under Signing & Capabilities. Never commit signing secrets.
4. Connect and unlock the iPhone, trust the Mac, enable Developer Mode, select the physical device and run. Allow camera and local-network access. RGB-D mode checks for LiDAR depth and scene reconstruction support.
5. On a trusted LAN, start the API with `--host 0.0.0.0 --port 8000`. Configure the phone's Server field with the workstation's reachable hostname, for example `http://workstation.local:8000`. The phone's `localhost` is not the workstation. Limit firewall access to that trusted network.
6. Project may be empty. Choose **Start Live**, then slowly move around a well-lit, non-reflective scene.
7. Choose **Live Mesh** in the Web console. Verify increasing mesh versions and actual geometry changes; before ARKit produces a mesh the viewer stays empty.
8. Choose **Finalize Live** and wait for deferred frames and the final mesh to upload. Errors remain visible and finalization can be retried. Keep the app in the foreground.
9. Run the queued task, inspect its outputs and validate them in a separately installed engine.

This preview has no application-level API authentication and is not a public upload service. Use a trusted LAN or a suitably protected private network. Local frames are retained during a session, but recovery after app termination or storage exhaustion is not guaranteed.

## Coordinates

ARKit camera-to-world poses are column-major in a right-handed y-up world. Intrinsics label `camera_convention=arkit` and `world_up_axis=y`. Optical depth `(x,y,z)` becomes camera `(x,-y,-z)` before applying the pose. World `(x,y,z)` becomes exported `(x,-z,y)`, in meters, z-up. Native mesh export uses the same conversion. Old captures without these labels retain their original interpretation.

## Optional Tools

Set `REAL2MOTRIX_DIR` for a separately installed Real2Motrix checkout, or configure SSH adapters using `backend/.env.example`. Apple Object Capture, COLMAP/OpenMVS, Blender, SAM2, engines and API credentials are separate requirements. Audit those environments separately from the core lock. Missing tools remain missing capabilities; never count unavailable providers as passed validation.

## Acceptance Evidence

Record commit, device/iOS, Xcode, workstation, input hashes, scan duration, frame/depth counts, deferred uploads, mesh versions, dimensions against a physical reference, processing duration, engine version and actual result. Keep continuous original footage and disclose accelerated editing. Only a successful physical run supports a phone-to-simulator demonstration claim.

## Browser Regression

The `browser` CI job starts an isolated database, actual API and production Web preview. It uploads explicitly labeled geometric test fixtures over HTTP and verifies version refresh, visible pixels, unclipped geometry, orbit controls, mobile overflow and browser errors. These images must not be used as device footage.

To reproduce locally, use a disposable API data directory, start the Web preview on port 5176 and run from the repository root:

```sh
frontend/node_modules/.bin/playwright install chromium
export CHROMIUM_PATH="$(node -p 'require("./frontend/node_modules/playwright").chromium.executablePath()')"
REAL2SIM_TEST_WEB=http://127.0.0.1:5176 node scripts/check_live_browser.mjs
```

The script creates test projects and sessions. Do not point it at a production database. Screenshots are stored under `.build/browser` and excluded from Git.
