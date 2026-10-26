# iPhone Real2Sim Capture 实现说明

本仓库现在包含第一版可运行闭环：

1. `backend/`：FastAPI + SQLite/Postgres 数据层、真实上传存储、依赖探测、SQLite 持久 local queue/Redis 队列入口、local/S3/MinIO object storage 发布、mesh 处理、RoomPlan parametric scene 处理、视频抽帧、COLMAP/OpenMVS 命令链路、MJCF/URDF/USD/manifest 导出和 MuJoCo 加载验证。
2. `frontend/`：React + TypeScript + three.js Web 控制台，连接真实后端 API，支持项目、任务、上传、运行、3D artifact 预览、导出包下载、QA 元数据编辑，以及删除、拆分、合并对象后的导出包重生成。
3. `ios/Real2SimCapture/`：SwiftUI iOS 采集 App，资产模式使用 RealityKit `ObjectCaptureSession`；场景模式支持 RoomPlan `RoomCaptureView` 包，以及 ARKit RGB-D scene capture 包，后者启用 `sceneDepth`、`sceneReconstruction`，导出 `images/*.jpg`、`depth/*.npy`、`poses.json`、`intrinsics.json` 和 `arkit_mesh.obj`；本地打包 ZIP 后上传到后端。

## 不仿真、不 mock、不硬编码的边界

- 后端不会在照片/视频重建失败时生成假 mesh。
- 如果 `colmap`、`InterfaceCOLMAP`、`DensifyPointCloud`、`ReconstructMesh`、`TextureMesh` 等工具缺失，任务会进入 `failed`，并在日志里写出缺失工具。
- 如果上传的是真实 mesh（OBJ/GLB/PLY/STL，或 ZIP 中包含 mesh），后端会用 `trimesh` 读取真实几何，按连通组件面积真实移除小漂浮碎片，导出 visual mesh、由 CoACD 生成多个 convex collision parts，并写出仿真包。清理结果会写入 `mesh_cleanup`；CoACD 不可用或失败时才明确 fallback 到 convex hull，并把 `collision_backend` / `collision_fallback_reason` 写进报告。OBJ/MTL 或 glTF 中引用的真实外部贴图会被复制到 `textures/`，嵌入材质图像会被提取为 PNG；没有真实贴图时只标记 `textures_present=false`，不会生成假贴图。
- 如果上传的是 RoomPlan ZIP（包含 `roomplan.json`、`captured_room.json` 或 `capturedroom.json`），后端会按 JSON 中的真实尺寸、pose、类别生成 metric scene、static geometry 和独立对象资产包，不再把 RoomPlan 包误判为普通照片重建失败。ZIP 中若包含明确命名的真实场景 mesh（例如 `scene_mesh.obj`、`arkit_mesh.glb`、`residual_scene.ply`），后端会把它作为 residual static scene geometry 保留成独立 visual/collision assets，并写入 `scene.json`、`manifest.json`、MJCF、USD/USDZ 和验收报告。
- 如果上传的是视频或 ZIP 中包含视频，后端会调用真实 `ffmpeg` 抽取关键帧，再做真实采集质量检查，然后进入 COLMAP/OpenMVS 重建链路。
- 照片/视频采集包会用 Pillow + NumPy 真实计算模糊度、曝光、过暗/过亮裁剪比例、可用帧数、pose 覆盖角、tracking lost 次数和尺度参考文件；不达阈值会以 `capture_quality_failed` 失败，并把 `capture_quality` 写进任务 `report`。
- `REAL2SIM_RECONSTRUCTION_PROVIDER` 支持 `colmap`、`kiri_photo`、`kiri_featureless`、`kiri_3dgs`、`apple_object_capture`。KIRI provider 按官方 open API 执行 image upload -> getStatus -> getModelZip -> 下载 zip -> 读取真实 mesh；API key 优先读取 `REAL2SIM_KIRI_API_KEY`，也会 fallback 到 macOS Keychain 的 `REAL2SIM_KIRI_API_KEY` / `KIRI_API_KEY` / `KIRI_ENGINE_API_KEY` service，full readiness 会调用 KIRI `/balance` 做真实凭证和余额探测但不会输出 secret。Apple provider 默认执行 `scripts/apple_object_capture.py`，用 RealityKit `PhotogrammetrySession` 生成 USDZ，再用本机 Blender 转为 OBJ 交给后端 mesh pipeline。缺 API key、服务失败、Swift/RealityKit/Blender 不可用或 zip 内没有 mesh 时都会失败，不会生成假 mesh。
- 场景自动分离支持 `rgbd_masks` 数据驱动路径：上传 ZIP 中的 `masks/*.png`、`depth/*.npy|png`、`intrinsics.json`、可选 `poses.json`/`objects.json`/`surfaces.json`，后端会真实把 mask + depth 反投影成 3D 点，并按相邻有效 depth 像素生成 per-object surface mesh 作为 visual OBJ/GLB，同时用带最小厚度的碰撞 mesh 保证 MuJoCo 可加载。没有 mask 但提供了 `depth/*.npy|png` 与 `intrinsics.json` 时，会按相邻 depth 像素反投影后的 3D 距离做 connected-components 聚类，生成带真实 depth surface mesh 的 `rgbd_depth_cluster` 对象；连 depth/intrinsics 都缺失时不会伪造分割。
- `sam2` 作为显式外部 provider 接入真实 runner：当 `REAL2SIM_SEGMENTATION_PROVIDER=sam2` 且上传 scene ZIP 时，后端会解压 capture、执行默认 `scripts/sam2_generate_masks.py` 或用户覆盖的 `REAL2SIM_SAM2_COMMAND`，要求命令在 `{output_masks_dir}` 产出真实 mask 图，再复用 RGB-D lifting 生成独立对象。默认 runner 会用真实 `sam2` Python 包和 `facebook/sam2.1-hiera-tiny` 生成 mask；命令失败、模型缺失、没有输出 mask、或缺少 depth/intrinsics 都会明确失败，不会假装自动分割成功。
- `POST /api/tasks/{task_id}/scene/resegment` 会从原始上传 capture 重新运行真实 RGB-D mask lifting、RGB-D depth clustering 或已配置的 SAM2 runner，并在成功后重写 `scene.json`、assets、MJCF/URDF/USD、manifest 和 zip；没有真实分割输入时会以 `segmentation_source_not_found` 失败并保留现有完成任务。
- 每个导出的 `scene.xml` 会先做 XML parse，再用 Python MuJoCo `MjModel.from_xml_path` 真实加载并 `mj_step` 50 步，结果写入 `report.json`。
- `POST /api/tasks/{task_id}/verify-simulation` 会做包级验收：检查 manifest/scene/assets/zip 完整性、真实解析 URDF/XML、检查 USD ASCII Mesh 结构、验证 parametric scene 中物体和地面/桌面/支撑面的 AABB 接触关系，并再次用 MuJoCo 加载和 step MJCF；结果写入 `report.package_validation` 和 `report.json`。
- `POST /api/tasks/{task_id}/verify-simulation` 还支持 MotrixSim、Isaac Sim、Genesis 原生导入验证命令。当前机器存在 `$REAL2MOTRIX_DIR` 时，MotrixSim 默认使用 `scripts/validate_with_real2motrix.py` 把 Real2Sim package 映射成 Real2Motrix `motrix_scene` 并调用其真实 `validate_package`；如果 `REAL2SIM_MOTRIXSIM_SSH_COMMAND` 指向装有 MotrixLab/MotrixSim 的远端主机，MotrixSim 会默认使用 `scripts/motrixsim_ssh_validate.py` 通过 SSH 上传 package，在远端调用 `motrixsim.load_model("scene.xml")` 并 step。若 `REAL2SIM_ISAACSIM_PYTHON` / `ISAACSIM_PYTHON` 指向真实 Isaac Sim Python，或当前 Python 环境已安装 `isaacsim`，Isaac Sim 会默认使用 `scripts/isaacsim_validate.py` 在 headless `SimulationApp` 中打开 `scene.usd`、推进 frame 并统计 stage prim；如果 `REAL2SIM_ISAACSIM_SSH_TARGET` 指向装有 Isaac Sim 的远端 Linux/Windows 工作站，Isaac Sim 会默认使用 `scripts/isaacsim_ssh_validate.py` 通过 SSH 上传 package 并在远端执行同一个 headless validator。也可配置 `REAL2SIM_MOTRIXSIM_VALIDATE_COMMAND`、`REAL2SIM_ISAACSIM_VALIDATE_COMMAND`、`REAL2SIM_GENESIS_VALIDATE_COMMAND` 覆盖。后端会把真实导出目录、MJCF、URDF、USD、manifest、zip 路径传给命令并记录退出码、stdout、stderr；命令缺失或失败会写入 `report.package_validation.native_simulators`，不会被当作通过。如果当前 Python 环境已安装 `genesis-world` 且未配置 `REAL2SIM_GENESIS_VALIDATE_COMMAND`，后端会用内置 Genesis CPU headless validator 在独立 Python 子进程加载 MJCF 并 step 10 次。
- `POST /api/tasks/{task_id}/enqueue` 支持 SQLite 持久 local 队列和 Redis 队列；Redis 配置不可达时返回明确 `redis_unavailable`，不会假装入队成功。
- `REAL2SIM_DATABASE_URL` 支持 `sqlite:///...` 和 `postgresql://...`；Postgres 不可达时健康检查显示真实失败原因，不会退回 SQLite 假装可用。
- 完成任务会把 artifacts 发布到配置的 local object storage 或 S3/MinIO，并在 artifact 元数据中写入 `storage_url`；S3/MinIO 未配置或不可达时任务会以 `artifact_publish_failed` 失败，不会伪造远端 URL。
- 质量报告里的质量、摩擦、惯性、置信度都有来源标记；未提供质量时按可配置密度从体积估计。
- iOS 端只做真实采集和上传，不宣称手机端已经完成后端重建；RGB-D scene capture 要求 LiDAR scene depth 和 mesh reconstruction 支持，不支持时不会生成空包。

## 运行后端

```bash
cd /path/to/real2simcapture
/opt/homebrew/bin/python3.11 -m venv .venv
. .venv/bin/activate
pip install -e 'backend[dev]'
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

安装 SAM2/Grounded-SAM2 等重型外部能力依赖：

```bash
pip install -e 'backend[external]'
pip install -r backend/requirements-external-overrides.txt
```

`requirements-external-overrides.txt` 当前固定到 MoviePy 上游 commit，用来在 Genesis 依赖 MoviePy 时继续使用安全修复版 Pillow 12.x，同时保持 `pip check` 和 `pip-audit` 通过。等 MoviePy 发布包含该 metadata 修正的新版后，可移除该覆盖。

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

生产化状态服务可通过环境变量切换：

```bash
REAL2SIM_DATABASE_URL=postgresql://real2sim:change-me@127.0.0.1:5432/real2sim
REAL2SIM_QUEUE_BACKEND=redis
REAL2SIM_REDIS_URL=redis://127.0.0.1:6379/0
REAL2SIM_STORAGE_BACKEND=s3
REAL2SIM_S3_ENDPOINT_URL=http://127.0.0.1:9000
REAL2SIM_S3_BUCKET=real2sim-artifacts
REAL2SIM_S3_ACCESS_KEY_ID=change-me
REAL2SIM_S3_SECRET_ACCESS_KEY=change-me
REAL2SIM_RECONSTRUCTION_PROVIDER=kiri_featureless
REAL2SIM_KIRI_API_KEY=change-me
# 或写入 macOS Keychain：
# security add-generic-password -s REAL2SIM_KIRI_API_KEY -a real2sim -w '<api-key>' -U
# 也可以用项目脚本，脚本不会打印 secret：
# printf '%s' '<api-key>' | .venv/bin/python scripts/kiri_credentials.py --store-keychain --check
# Apple Object Capture 默认已启用 scripts/apple_object_capture.py；需要自定义时覆盖：
# REAL2SIM_APPLE_OBJECT_CAPTURE_COMMAND="/path/to/object-capture-cli {images_dir} {output_mesh}"
REAL2SIM_MOTRIXSIM_VALIDATE_COMMAND="/path/to/motrixsim-validator {mjcf_path}"
# 或通过 SSH 使用远端真实 MotrixSim/MotrixLab 主机：
# REAL2SIM_MOTRIXSIM_SSH_COMMAND="ssh -i /path/to/key -p 22 user@linux-motrix-host"
# REAL2SIM_MOTRIXSIM_REMOTE_PYTHON="/opt/motrixlab/venv/bin/python"
# REAL2SIM_MOTRIXSIM_REMOTE_REPO="/opt/motrixlab/repo"
REAL2SIM_ISAACSIM_VALIDATE_COMMAND="/path/to/isaacsim-validator {usd_path}"
# 或让默认 IsaacSim validator 自动发现真实 Isaac Python：
# REAL2SIM_ISAACSIM_PYTHON="/path/to/isaac-sim/python.sh"
# 或通过 SSH 使用远端真实 Isaac Sim 工作站：
# REAL2SIM_ISAACSIM_SSH_COMMAND="ssh -i /path/to/key -p 22 user@linux-isaac-host"
# REAL2SIM_ISAACSIM_SSH_TARGET="user@linux-isaac-host"
# REAL2SIM_ISAACSIM_REMOTE_PYTHON="/path/to/isaac-sim/python.sh"
REAL2SIM_GENESIS_VALIDATE_COMMAND="/path/to/genesis-validator {manifest_path} {package_dir}"
```

运行队列任务：

```bash
. .venv/bin/activate
python -m app.worker --once
```

Web 控制台也可以对单个任务调用 `POST /api/tasks/{task_id}/run`。

入队但不立即运行：

```bash
curl -X POST http://127.0.0.1:8000/api/tasks/<task_id>/enqueue
python -m app.worker --once
```

## 运行真实 Postgres / Redis / MinIO

本仓库提供 `infra/docker-compose.yml`，用于本地启动真实状态服务，不走 mock：

```bash
cd /path/to/real2simcapture
docker compose -f infra/docker-compose.yml up -d postgres redis minio minio-create-bucket
```

用这些真实服务启动后端：

```bash
REAL2SIM_DATABASE_URL=postgresql://real2sim:real2sim_dev_password@127.0.0.1:55432/real2sim \
REAL2SIM_QUEUE_BACKEND=redis \
REAL2SIM_REDIS_URL=redis://127.0.0.1:56379/0 \
REAL2SIM_STORAGE_BACKEND=s3 \
REAL2SIM_S3_ENDPOINT_URL=http://127.0.0.1:59000 \
REAL2SIM_S3_BUCKET=real2sim-artifacts \
REAL2SIM_S3_ACCESS_KEY_ID=real2sim \
REAL2SIM_S3_SECRET_ACCESS_KEY=real2sim_dev_password \
REAL2SIM_S3_PUBLIC_BASE_URL=http://127.0.0.1:59000/real2sim-artifacts \
REAL2SIM_DATA_DIR=data-infra \
REAL2SIM_OUTPUT_DIR=outputs-infra \
.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

端到端验证真实数据库、队列、对象存储和 worker：

```bash
REAL2SIM_DATABASE_URL=postgresql://real2sim:real2sim_dev_password@127.0.0.1:55432/real2sim \
REAL2SIM_QUEUE_BACKEND=redis \
REAL2SIM_REDIS_URL=redis://127.0.0.1:56379/0 \
REAL2SIM_STORAGE_BACKEND=s3 \
REAL2SIM_S3_ENDPOINT_URL=http://127.0.0.1:59000 \
REAL2SIM_S3_BUCKET=real2sim-artifacts \
REAL2SIM_S3_ACCESS_KEY_ID=real2sim \
REAL2SIM_S3_SECRET_ACCESS_KEY=real2sim_dev_password \
REAL2SIM_S3_PUBLIC_BASE_URL=http://127.0.0.1:59000/real2sim-artifacts \
REAL2SIM_DATA_DIR=data-infra \
REAL2SIM_OUTPUT_DIR=outputs-infra \
PYTHONPATH=backend .venv/bin/python scripts/verify_real_infra.py
```

该脚本会通过真实 API 创建任务、推入 Redis、调用 worker 消费、把 artifact 发布到 MinIO，再执行 package verification。

## 外部能力 readiness 审计

全量验收不能只看本地核心测试。运行下面命令可检查 KIRI、Apple Object Capture、SAM2/Grounded-SAM2、MotrixSim、Isaac Sim、Genesis、完整 Xcode 和 Python 依赖一致性是否真的齐备。KIRI 在 full scope 下会真实请求 `/balance`，因此没有 API key、key 无效或余额不足都会阻塞全量 ready：

```bash
PYTHONPATH=backend .venv/bin/python scripts/check_external_readiness.py --scope full --output text
```

`--scope full` 缺任何外部能力或 `python -m pip check` 失败都会以非 0 退出码返回，并列出 `blocker=...`。日常 CI 可用 `--scope configured` 只检查已经配置的外部 runner 是否可执行：

```bash
PYTHONPATH=backend .venv/bin/python scripts/check_external_readiness.py --scope configured --output json
```

单独检查 KIRI 凭证：

```bash
.venv/bin/python scripts/kiri_credentials.py --check
```

## 运行前端

```bash
cd /path/to/real2simcapture/frontend
npm install
npm run dev
```

默认前端会把 `localhost:5173` 映射到 `localhost:8000` 后端。需要覆盖时创建 `frontend/.env.local`：

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## iOS App

生成 Xcode 项目：

```bash
cd /path/to/real2simcapture/ios/Real2SimCapture
xcodegen generate
```

本机当前 `xcodebuild` 指向 Command Line Tools，不是完整 Xcode，因此只能生成 `.xcodeproj`，不能在命令行完成 iOS 编译和真机部署。切换完整 Xcode 后可构建并在真机上验收 Object Capture、RoomPlan 和 ARKit RGB-D scene capture：

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
xcodebuild -project Real2SimCapture.xcodeproj -scheme Real2SimCapture -destination 'generic/platform=iOS' build
```

## 验证命令

```bash
cd /path/to/real2simcapture
. .venv/bin/activate
pytest -q
PYTHONPATH=backend .venv/bin/python scripts/check_external_readiness.py --scope configured

cd frontend
npm test
npm run build
npm audit
```

## 第一版验收覆盖

- 上传普通 OBJ/GLB/PLY/STL mesh 后可导出：
  - `assets/*_visual.obj`
  - `assets/*_visual.glb`
  - `assets/*_collision.obj`
  - `assets/*_collision_part_###.obj`（CoACD 产生多个 convex parts 时）
  - `manifest.json`
  - `asset.json`
  - `scene.json`
  - `scene.xml`
  - `scene.urdf`
  - `scene.usd`
  - `scene.usdz`
  - `report.json`
  - `README.md`
  - `real2sim_package.zip`
- Web 端可预览 visual/collision mesh，并下载导出包。
- 上传真实 mesh 时，报告会显示 `mesh_cleanup`、`collision_backend`、`collision_part_count`、collision faces/vertices；MJCF/URDF 会引用每个 `collision_part`，而不是只引用视觉高模。
- Web 端 Task Inspector 会显示 visual/collision 面数、CoACD collision part 数、watertight、贴图状态和 cleanup 移除的组件/面数。
- QA 编辑会更新 scene object 的名称、类别、质量和摩擦，并重新生成 manifest/MJCF/URDF/USD/USDZ 元数据。
- Web 端 QA 校正支持真实删除、按 X 轴拆分、合并对象；后端会更新 `scene.json`、重新物化 assets，并重写 manifest/MJCF/URDF/USD/USDZ/zip。
- Web 端 QA 校正支持重新分割；该动作会调用后端真实重跑原始 scene capture 的 RGB-D masks、RGB-D depth clustering 或 SAM2 runner，失败时不会覆盖已有 scene。
- `POST /api/tasks/{task_id}/scene/objects/{object_id}/export` 会把已完成场景中的某个分离对象导出成独立 Real2Sim 资产 ZIP，包内只包含该对象的 visual/collision mesh、manifest、asset.json、scene.json、MJCF、URDF、USD/USDZ、report 和 README；不会把同场景其他对象或 static geometry 混进独立资产包。
- 带真实贴图的 OBJ/MTL 或 glTF 包会把贴图写入 `textures/`，并在 `scene.json`、`manifest.json`、`asset.json` 和包级验收中保留引用；包级校验会检查声明的贴图文件是否真实存在。
- RoomPlan ZIP 会生成带 `static_geometry` 和多个 objects 的 metric scene package；如果 ZIP 中带真实 `scene_mesh.*`/`arkit_mesh.*`，该 mesh 会被作为 residual scene geometry 导出，而不是被丢弃。
- iOS ARKit RGB-D scene capture 会打包真实相机帧、LiDAR depth、相机 pose/intrinsics 和 ARKit mesh；上传后可走后端 RGB-D depth clustering 或 residual static geometry pipeline。
- 照片 ZIP、视频文件或 iOS Object Capture ZIP 先做 capture quality gate；质量通过且真实重建依赖齐备时才启动 COLMAP/OpenMVS，否则失败并写结构化 report/logs。
- 需要透明、反光、低纹理 fallback 时，可切到 `kiri_featureless` / `kiri_3dgs`；需要 Apple Object Capture 时，默认 runner 会调用 RealityKit PhotogrammetrySession，必要时可覆盖 `REAL2SIM_APPLE_OBJECT_CAPTURE_COMMAND` 为真实命令模板，例如包含 `{images_dir}`、`{output_dir}`、`{output_mesh}` 占位符。
- 需要 KIRI fallback 时，可把 API key 放入环境变量或 macOS Keychain；full readiness 会用 KIRI balance API 证明凭证可用，不会只因为存在一个字符串就标记通过。
- 需要基于已有分割结果做场景资产抽取时，上传 RGB-D lifting ZIP。后端会把每个 mask/depth 对应的有效像素反投影为真实 object-local surface mesh，导出到 `assets/<object_id>_visual.obj` / `.glb`；collision mesh 会由该 surface 的 bounds/hull 派生，不会把 visual mesh 退化成固定盒子：
  - `masks/<object_id>.png`
  - `depth/<object_id>.npy` 或 `depth/<object_id>.png`
  - `intrinsics.json`，包含 `fx`、`fy`、`cx`、`cy`、可选 `depth_scale`
  - 可选 `poses.json`，每帧包含 `id` 和 4x4 `transform`
  - 可选 `objects.json`，给每个 object 填 `name`、`category`、`mass_kg`、`friction`
  - 可选 `surfaces.json`，作为 residual/static scene geometry
- 没有 `masks/` 但有 `depth/*.npy|png` 和 `intrinsics.json` 时，后端会执行 RGB-D depth clustering fallback；聚类对象会在 `source.kind` 中标记为 `rgbd_depth_cluster`，visual mesh 来自该 cluster 的真实 depth surface，并在 `report.segmentation` 中写入 cluster 数、过滤的小组件数和阈值。
- Web 端 Task Inspector 会显示 capture quality 的帧数、可用帧、模糊/曝光问题、尺度参考、覆盖角和 tracking lost 计数。
- MJCF 导出会通过 MuJoCo Python 加载和 step 验证；验证失败不会被标记为成功。
- Web 端可以触发 `Verify simulation package`，并显示 artifact、manifest、MJCF、URDF、USD、USDZ、支撑接触关系、zip 和已配置 MotrixSim/Isaac/Genesis 原生命令的验收结果。
- local object storage 可通过 `/api/storage/tasks/<task_id>/<artifact>` 访问已发布 artifact；S3/MinIO 模式会返回 `s3://bucket/key` 或 `REAL2SIM_S3_PUBLIC_BASE_URL/key`。
- `infra/docker-compose.yml` 可启动真实 Postgres、Redis、MinIO；`scripts/verify_real_infra.py` 已验证 Postgres health、Redis 入队/worker 消费、MinIO artifact 发布和 package verification。
- `backend[external]` 可安装 `sam2`、`segment-anything`、`groundingdino-py`、`torch`、`torchvision` 等外部分割依赖；如果当前环境已安装 `genesis-world`，Genesis 可通过内置 validator 真实加载导出的 MJCF 并 step。

## 后续增强

1. 在真实 Postgres、Redis、MinIO 环境上增加多 worker 并发压测、重试策略和故障恢复验收。
2. 用真实 iPhone 场景视频继续验收默认 SAM2 runner，并按需要升级为 Grounded-SAM2 文本提示检测 + SAM2 mask tracking。
3. 给 Isaac Sim 配置真实本机或远端 Isaac Python，并用 `scripts/isaacsim_validate.py` / `scripts/isaacsim_ssh_validate.py` 在实际引擎里完成 USD stage 导入、接触关系和坐标系验收。
4. 给 iOS 端增加项目列表拉取和局域网后端发现，并在完整 Xcode + 真机上完成 Object Capture、RoomPlan、ARKit RGB-D 采集上传验收。

## 外部 API 参考

- KIRI image upload: https://docs.kiriengine.app/photo-scan/image-upload/
- KIRI featureless image upload: https://docs.kiriengine.app/featureless-object-scan/image-upload/
- KIRI model status: https://docs.kiriengine.app/model/retrieve-3d-model-status/
- KIRI zipped model download: https://docs.kiriengine.app/model/download-3d-models-zipped/
- KIRI balance: https://docs.kiriengine.app/balance/get-balance/
- Isaac Sim SimulationApp: https://docs.isaacsim.omniverse.nvidia.com/latest/py/source/extensions/isaacsim.simulation_app/docs/api.html
