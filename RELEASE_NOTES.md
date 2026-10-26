# v0.1.0-alpha.1

First Apache-2.0 open-source developer preview of real2simcapture.

## Included

- Native iPhone RGB-D, camera-pose, RoomPlan and ARKit scene-mesh capture code.
- Periodic Live mesh uploads, bounded frame uploads, deferred-frame finalization and actual geometry in the React/Three.js workbench.
- Serialized and atomic capture storage, malformed-mesh rejection, idempotent finalization and ARKit coordinate conversion.
- Geometry processing and visual/collision asset export to MJCF, URDF and USD.
- Bilingual documentation, contribution and security guidance, pinned core dependencies, and third-party integration boundaries.
- CI for backend tests, frontend tests/build, actual HTTP/browser mesh regression and an unsigned physical-iOS-target build.
- Safer optional infrastructure defaults: loopback ports, required user-supplied passwords and private object storage.

## What This Release Does Not Claim

- A completed physical iPhone-to-engine acceptance run. Full Xcode, signing, a compatible LiDAR device and actual scanning are still required.
- A signed IPA, bundled Apple SDK, proprietary simulator, model checkpoint or licensed real capture dataset.
- Photorealistic live reconstruction, measured accuracy, fixed latency, or validated physical parameters.
- A secure public multi-user API. Use loopback or a protected private network; see SECURITY.md.
- Validation of every optional engine, GPU model or paid service. Automated geometry fixtures are not device footage.

## 中文

这是首个 Apache-2.0 开源开发预览，包含原生采集、Live 网格上传与 Web 查看、资产处理与导出、安装文档和自动验证。

代码和 CI 通过不等于真机验收完成。本版本不附带签名安装包、第三方引擎、模型权重或真实扫描样例；不能直接作为公网上传服务部署。可选 Docker 服务默认仅监听本机，密码需自行配置，存储桶默认私有。

从 README 开始安装，真机配置见 docs/SETUP.md。欢迎提交可复现的问题、设备兼容报告和有明确授权的数据样例。
