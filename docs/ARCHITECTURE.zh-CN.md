# real2simcapture 历史架构方案

本页保留早期设计与实现说明，能力状态以根目录 README 和当前发布记录为准。

iPhone 采集到机器人仿真资产的开发工具链，包含原生采集、Web 控制台、处理流水线和仿真格式导出。

> **开发预览，尚未完成公开发布验收。** 以下内容同时包含已有实现和设计目标。当前 Live 路径接收 RGB-D 帧并更新场景包围盒、尺寸及帧数，尚不是持续融合的完整三维表面重建。iPhone 真机采集到仿真运行的完整闭环仍需实测；测试中生成的输入不作为真机演示证据。后端目前没有应用层访问认证，应在受控开发网络中使用。
> 开源准备状态见 [发布审计](launch/READINESS.zh-CN.md)，介绍视频分镜和平台文案见 [视频与发布方案](launch/VIDEO.zh-CN.md)。

## 项目说明

> 当前仓库已经从方案文档扩展为第一版可运行实现。代码入口见 `backend/`、`frontend/`、`ios/Real2SimCapture/`，运行和验收说明见 [IMPLEMENTATION.md](../IMPLEMENTATION.md)。
> 真实 Postgres / Redis / MinIO 本地环境见 `infra/docker-compose.yml`，端到端验证脚本见 `scripts/verify_real_infra.py`。
> 外部能力全量 readiness 审计见 `scripts/check_external_readiness.py`。
> SAM2/Grounded-SAM2 依赖可通过 `pip install -e 'backend[external]'` 安装；后端默认提供 `scripts/sam2_generate_masks.py`，可用真实 `sam2` 包和公开 `facebook/sam2.1-hiera-tiny` 生成 mask。iOS 场景采集提供 RoomPlan 包和 ARKit RGB-D 包，RGB-D 包会导出真实 RGB、LiDAR depth、pose、intrinsics 和 ARKit mesh。Apple Object Capture 默认通过 `scripts/apple_object_capture.py` 调用 RealityKit PhotogrammetrySession 并用 Blender 转 OBJ。KIRI fallback 支持环境变量或 macOS Keychain 读取 API key，full readiness 会调用官方 balance API 验证凭证和余额。如果本机存在 `$REAL2MOTRIX_DIR`，MotrixSim 默认通过 `scripts/validate_with_real2motrix.py` 调用 Real2Motrix 真实 package validator；也可通过 SSH 远端 MotrixSim/MotrixLab 主机自动接入 `scripts/motrixsim_ssh_validate.py`。Isaac Sim 可通过真实本机 Isaac Python 自动接入 `scripts/isaacsim_validate.py`，或通过 SSH 远端 Isaac 工作站自动接入 `scripts/isaacsim_ssh_validate.py` headless validator。如果环境中已安装 `genesis-world`，后端会自动启用内置 Genesis headless validator。

## 实时 Live 构建链路

iPhone `RGB-D` 模式支持实时 live session，不需要等 `Stop` 后才产生场景状态：

1. Web 控制台启动后端：`http://<workstation-ip>:8000`，Web 端访问 `http://<workstation-ip>:5173`。
2. iPhone App 进入 `RGB-D`，`Server` 填后端地址，例如 `http://workstation.local:8000`。
3. `Project` 可以留空；App 会通过真实 `/api/projects` 自动创建项目。已有项目时也可以手填 Project UUID。
4. 点击 `Start Live` 后，App 每 0.5 秒上传真实 ARKit frame：JPEG、LiDAR depth `.npy`、camera pose、intrinsics、tracking state。
5. 后端 `/api/live-sessions/{id}/frames` 每收到一帧，会用 depth + intrinsics + pose 反投影点云并更新 `live_scene.json`，Web 控制台 `Live Scene` 面板会轮询显示当前几何状态。
6. 点击 `Finalize Live` 后，后端把累计的 live capture 打成 `live_capture.zip`，创建普通 queued task；随后可以在 Web 控制台运行完整 pipeline、导出 Motrix/MuJoCo/URDF/USD 包，并调用真实 simulator validator。

Live 阶段提供持续更新的包围盒、尺寸和采集状态；Web 当前展示这些状态数据，不提供流式点云或网格预览。高质量重建、语义分割、QA 编辑和仿真包验证仍走 finalize 后的完整后端 pipeline，并受对应依赖和输入条件限制。

## 结论

这个需求可以做成真实可用的平台，但不能把“好看的 3D 扫描”和“机器人仿真可用资产”混为一件事。

推荐方案是：`iPhone 原生采集 App + Web 控制台 + 后端重建/处理流水线 + 仿真导出器`。Web 控制台负责 B/S 侧的项目、任务、预览、质检和导出；iPhone App 负责 ARKit、RoomPlan、LiDAR、Object Capture 这些浏览器拿不到或拿不稳的能力。纯 Safari/PWA 只能作为低配入口，用于拍照/录像上传，不能作为高质量 LiDAR/RoomPlan 扫描主链路。

最终输出不要只做一个 `glb`。要输出一套仿真包：

1. `visual.glb` / `visual.obj`：高模视觉资产，带贴图。
2. `collision.obj` / `collision.stl`：简化碰撞网格或凸分解结果。
3. `asset.json`：尺度、类别、质量、摩擦、材质、坐标系、来源、置信度。
4. `scene.json`：场景布局、物体实例、pose、语义、层级。
5. `scene.xml` / MJCF：给 MuJoCo 和 MotrixSim。
6. `scene.urdf`：给 URDF 兼容链路。
7. `scene.usd` / `scene.usdz`：给 Isaac Sim / Omniverse / AR 预览。

其中 3DGS/NeRF 可以做高保真视觉层，但不能直接当物理仿真碰撞体；机器人仿真必须有 mesh、尺度、质量、惯性、摩擦和 collision geometry。

## 两个功能拆分

### 1. 资产扫描

目标：扫描一个独立物体，比如瓶子、杯子、盒子、零件，生成细致 3D 模型和材质。

推荐采集方式：

1. iPhone App 使用 `ObjectCaptureSession` 做引导式拍摄。
2. 对普通非反光物体，用默认 Apple Object Capture runner 或服务端 COLMAP/OpenMVS 重建 mesh。
3. 对透明、反光、低纹理物体，用 KIRI Engine 的 Featureless Object Scan / 3DGS to Mesh 作为商业 API fallback。
4. 对要求最高的资产，增加受控采集：转台、均匀灯光、背景板、标尺、可选偏振片。

资产扫描的真实边界：

1. 普通 iPhone 照片可以恢复几何和颜色贴图，但很难精确测量 PBR 材质参数。
2. 透明瓶子、金属高光、黑色亮面、玻璃、纯白无纹理物体是 photogrammetry 难点。
3. “材质很细致”可以做到视觉上接近，但 `roughness`、`metallic`、`normal`、`specular` 多数是推断或生成，不是严格物理测量。
4. 仿真里真正重要的是：尺度、碰撞体、质量、惯性、摩擦、抓取接触面；视觉贴图只是给相机观测和渲染用。

资产处理流水线：

```text
iPhone guided capture
  -> upload images/video/depth/poses
  -> quality check: blur, exposure, overlap, coverage, scale marker
  -> mask foreground object
  -> reconstruction: Object Capture / COLMAP+OpenMVS / KIRI API / 3DGS-to-mesh
  -> mesh cleanup: remove floaters, fill holes, decimate, remesh, UV unwrap
  -> texture bake: albedo-like texture, optional normal/roughness estimation
  -> scale alignment: LiDAR/ARKit scale or marker scale
  -> collision generation: primitive fit + CoACD/V-HACD convex decomposition
  -> physical metadata: category, mass, density, friction, inertia estimate
  -> export: GLB, OBJ, USDZ, MJCF, URDF, manifest
```

### 2. 场景扫描

目标：扫描一个房间、工位、桌面、实验区、仓库角落，重建整体场景，并尽量把场景和资产分离。

推荐采集方式：

1. iPhone Pro / iPad Pro 用 ARKit LiDAR mesh 获取实时尺度和粗几何。
2. RoomPlan 获取墙、门、窗、地面、家具类型、尺寸和布局。
3. 同步采集 RGB 视频、相机 pose、深度、ARMeshAnchor、RoomPlan JSON/USD。
4. 服务端再训练或重建 3DGS/NeRF，得到高保真视觉场景。
5. 用 RoomPlan 语义框 + SAM2/Grounded-SAM mask + RGB-D 投影，把物体实例从场景中分离出来。

场景输出分两层：

1. `metric scene layer`：RoomPlan/ARKit 生成的可测量几何、地面、墙面、家具 bounding boxes、坐标系。
2. `visual scene layer`：mesh 或 3DGS，负责视觉真实感。
3. `simulation layer`：地面/墙体/桌面用稳定 primitive 或简化 mesh；可交互物体用独立资产包。

场景处理流水线：

```text
iPhone room/scene scan
  -> upload RGB video + depth + camera poses + ARKit mesh + RoomPlan result
  -> scene quality check: loop closure, tracking lost, exposure, coverage
  -> metric reconstruction: room planes, floor, table, shelves, obstacles
  -> visual reconstruction: 3DGS/NeRF or textured mesh
  -> object proposals: RoomPlan categories + Grounded-SAM/SAM2 masks
  -> 2D mask tracking across frames
  -> lift masks to 3D using depth/pose
  -> cluster per-object points / mesh faces / gaussians
  -> extract assets and residual static scene
  -> generate scene.json layout and per-object pose
  -> export to MJCF/URDF/USD package
```

## 自动分离资产和场景

可以做，但要定义成“自动分离 + 人工校正”，不能承诺 100% 全自动。

推荐算法组合：

1. RoomPlan：先拿墙、门、窗、家具类型、家具 3D boxes。
2. Grounded-SAM / Grounded-SAM2：根据类别文本自动检测并分割，比如 `bottle . cup . table . chair`。
3. SAM2：对视频里同一物体做 mask tracking。
4. RGB-D lifting：用每帧 depth + camera pose 把 mask 投到 3D 点，并按相邻有效 depth 像素生成 per-object surface mesh。
5. 3D clustering：没有 mask 但有 depth/intrinsics 时，先用相邻 depth 像素反投影后的 3D 距离做 connected components，把同一物体聚合为带真实 depth surface mesh 的 `rgbd_depth_cluster` 对象；后续可替换为 DBSCAN / graph cut。
6. Mesh face labeling：把 2D mask 票投到 mesh face，生成 per-object mesh。
7. QA UI：Web 端允许点选、合并、拆分、重命名、重新分割。

分离策略：

1. 独立小物体：优先当 asset，单独重建、单独导出。
2. 大件家具：可作为 scene prop，也可抽成 asset；取决于是否要机器人交互。
3. 墙、地、门、窗、固定柜体：作为 scene geometry。
4. 桌面、货架、台面：作为可放置 surface，优先生成稳定 collision primitive。
5. 透明/反光物：不要只靠 mask，最好单独走资产扫描模式。

## 推荐 B/S 架构

```mermaid
flowchart LR
  IOS["iPhone Capture App<br/>SwiftUI + ARKit + RoomPlan + RealityKit"] --> Upload["Upload API<br/>images / video / depth / poses / RoomPlan"]
  Web["Web Console<br/>React + three.js"] --> API["Backend API<br/>FastAPI / Postgres"]
  Upload --> API
  API --> Queue["Job Queue<br/>Redis/RQ or Celery"]
  Queue --> Worker["Reconstruction Workers<br/>GPU + CPU"]
  Worker --> Recon["Photogrammetry / 3DGS / Segmentation<br/>COLMAP OpenMVS Nerfstudio SAM2 KIRI"]
  Recon --> Process["Asset Processing<br/>Blender trimesh Open3D CoACD"]
  Process --> Store["Object Storage<br/>S3/MinIO"]
  Process --> Export["Exporters<br/>GLB OBJ USD URDF MJCF"]
  Store --> Web
  Export --> Sim["MuJoCo / MotrixSim / Isaac Sim / Genesis"]
```

### 移动端

1. SwiftUI 原生 App，不建议纯 Web 起步。
2. Asset mode：
   - ObjectCaptureSession 引导用户绕物体拍摄。
   - 采集照片、相机内参、可选 LiDAR 深度、尺度提示。
3. Scene mode：
   - ARKit world tracking。
   - Scene reconstruction mesh。
   - RoomPlan scan。
   - RGB 视频和关键帧。
4. Capture QA：
   - 模糊检测、曝光检测、覆盖角度、跟踪丢失提示。
   - 标尺/AR ruler 校验真实尺度。

### Web 端

1. 项目/任务管理。
2. 扫描包上传、队列状态、失败原因。
3. three.js 预览：mesh、texture、collision、RoomPlan layout、3DGS preview。
4. 分割校正：点击物体、合并/拆分、重命名类别、重新生成。
5. 仿真导出：选择 MuJoCo、MotrixSim、Isaac Sim、Genesis；也可以把场景中任一分离对象单独导出为只包含该对象 visual/collision/metadata/simulator files 的资产 ZIP。
6. 质检面板：尺度、面数、贴图大小、collision hull 数量、watertight、物理参数。
7. 原生引擎验收：显示 MotrixSim、Isaac Sim、Genesis validator 是否配置，以及每次包验证的实际执行结果。

### 后端

推荐技术：

1. API：FastAPI。
2. DB：Postgres；MVP 可 SQLite，但生产建议 Postgres。
3. 存储：S3/MinIO，按 `project/task/artifacts` 分层。
4. 队列：Redis + RQ/Celery。
5. GPU worker：NVIDIA GPU，跑 Nerfstudio/3DGS/SAM2。
6. CPU worker：COLMAP/OpenMVS/Blender/trimesh/Open3D/CoACD。
7. 第三方重建：KIRI API 作为商业 fallback，不要让它成为唯一链路。
8. Apple Object Capture：默认 runner 会用 RealityKit PhotogrammetrySession 生成 USDZ，并用 Blender 转出 OBJ 交给后端仿真导出 pipeline；失败时不生成假 mesh。
9. 原生仿真导入验证：MotrixSim 可默认调用本机 Real2Motrix validator，也可通过 SSH 调用远端 MotrixLab/MotrixSim 主机真实加载 `scene.xml`；Isaac Sim 在配置真实本机 Isaac Python 或远端 SSH Isaac 工作站后可默认调用 `scripts/isaacsim_validate.py` / `scripts/isaacsim_ssh_validate.py`，Genesis 可通过内置或环境变量配置真实 validator；后端只记录真实退出码和输出，不做伪通过。
10. 自动分割 runner：`REAL2SIM_SEGMENTATION_PROVIDER=sam2` 时，后端会调用默认 SAM2 runner 或配置的 Grounded-SAM2/SAM2 命令生成真实 mask，并把 mask + depth + intrinsics 交给 RGB-D lifting。

## 仿真导出设计

### MuJoCo / MotrixSim

MuJoCo 使用 MJCF XML，mesh asset 可以被 geom 引用；MotrixSim 文档说明它高度兼容 MJCF。导出策略：

```xml
<mujoco model="scanned_scene">
  <asset>
    <mesh name="bottle_collision" file="assets/bottle_collision.obj"/>
  </asset>
  <worldbody>
    <geom name="floor" type="plane" size="5 5 0.05" friction="0.8 0.1 0.1"/>
    <body name="bottle" pos="0.3 0.1 0.85" quat="1 0 0 0">
      <freejoint/>
      <inertial mass="0.08" pos="0 0 0" diaginertia="0.0001 0.0001 0.0001"/>
      <geom name="bottle_col" type="mesh" mesh="bottle_collision" contype="1" conaffinity="1" friction="0.6 0.1 0.1"/>
    </body>
  </worldbody>
</mujoco>
```

实际导出时要把 `visual` 和 `collision` 分开：高模或 RGB-D surface visual mesh 会保留在包和 manifest/URDF/USD 中；MJCF 为了保证 MuJoCo 对零体积/开曲面也能真实加载，只引用 collision mesh。当前后端会先按连通组件面积移除小漂浮碎片，把 cleanup 结果写进 report；随后保留兼容的 `assets/*_collision.obj`，并在 CoACD 产生多个凸部件时导出 `assets/*_collision_part_###.obj`，让 MJCF/URDF 分别引用这些 collision parts。

### Isaac Sim

Isaac Sim 主链路是 USD。可以从 URDF 导入并转 USD，也可以直接生成 USD stage。推荐导出：

1. `scene.usd` / `scene.usdz`：完整场景和可分发 USDZ 包。
2. `assets/*.usd`：独立资产。
3. `textures/*`：PBR/贴图。
4. `physics` metadata：mass、collider、material、friction。

### Genesis / 其他 ML 管线

输出一个统一 `manifest.json`，让不同 simulator adapter 读取：

```json
{
  "unit": "meter",
  "up_axis": "z",
  "assets": [
    {
      "id": "bottle_001",
      "category": "bottle",
      "visual_mesh": "assets/bottle_visual.glb",
      "collision_mesh": "assets/bottle_collision.obj",
      "mass_kg": 0.08,
      "friction": 0.6,
      "pose": {"position": [0.3, 0.1, 0.85], "quaternion": [1, 0, 0, 0]},
      "confidence": {"geometry": 0.82, "material": 0.55, "physics": 0.45}
    }
  ]
}
```

后端的 `verify-simulation` 接口支持给这些适配器配置真实验证命令。命令模板可使用 `{package_dir}`、`{mjcf_path}`、`{urdf_path}`、`{usd_path}`、`{usdz_path}`、`{manifest_path}`、`{scene_json_path}`、`{zip_path}` 和 `{simulator}` 占位符；命令失败或未配置时会在报告里显示为未通过，而不是静态通过。

## 技术选型

| 模块 | 首选 | 备用 / 补充 | 说明 |
|---|---|---|---|
| iPhone 资产采集 | RealityKit Object Capture | KIRI API / Polycam 手工导出 | Apple 适合自研闭环，KIRI 适合快速商业 API |
| iPhone 场景采集 | ARKit + RoomPlan | Polycam / Scaniverse 手工导出 | RoomPlan 有尺度和语义，第三方适合验证效果 |
| 普通 mesh 重建 | COLMAP + OpenMVS | Apple Object Capture | 开源可控，速度和稳定性需要工程调参 |
| 高保真视觉场景 | Nerfstudio / 3DGS | KIRI 3DGS Scan | 视觉真实，但不是物理碰撞资产 |
| 自动分割 | Grounded-SAM2 + SAM2 | RoomPlan boxes + manual QA | 必须保留人工校正 |
| Mesh 清理 | Blender + trimesh + Open3D | MeshLab / PyMeshLab | 修洞、简化、重拓扑、UV、贴图 |
| 碰撞体 | primitive fit + CoACD/V-HACD | simplified triangle mesh | 仿真稳定优先于视觉精细 |
| MuJoCo/MotrixSim | MJCF | URDF -> converter | MotrixSim 兼容 MJCF，优先 MJCF |
| Isaac Sim | USD | URDF import to USD | USD 更适合场景和材质 |

## 真实可用落地顺序

### 第一版：先跑通闭环

1. iPhone App 支持 asset mode 和 scene mode。
2. 上传照片/视频/depth/pose/RoomPlan 到后端。
3. 资产模式先用 Apple Object Capture 或 KIRI API 出 mesh。
4. 场景模式先用 RoomPlan + ARKit mesh 出场景骨架；上传包中的 `scene_mesh.*` / `arkit_mesh.*` 会作为 residual static scene geometry 保留进导出包。
5. 后端生成 GLB/OBJ、collision OBJ、MJCF、URDF、manifest。
6. Web 端能预览 visual/collision/scene 三个视图。
7. MuJoCo 和 MotrixSim 能加载一个瓶子 + 桌面 + 地面场景。

### 第二版：增强自动分离

1. 把通用 SAM2 runner 命令模板绑定到具体 Grounded-SAM2/SAM2 部署脚本。
2. RoomPlan 3D boxes 和 2D masks 融合。
3. 支持用户在 Web 端修正分割。
4. 对每个 extracted object 单独生成资产包；当前后端提供 `POST /api/tasks/{id}/scene/objects/{object_id}/export`，Web 端可直接下载独立对象 ZIP。
5. 支持“场景残留 mesh + 独立可交互资产”组合导出。

### 第三版：提高细节和材料

1. 受控灯光和转台采集。
2. 3DGS visual layer。
3. 贴图 delight / normal / roughness 估计。
4. 物理属性库：按类别给质量、密度、摩擦先验。
5. 自动质量检查失败后重试或提示补拍。

## 质检标准

资产级：

1. 尺度误差：普通物体控制在 2-5 cm 以内；有标尺时争取 1-2 cm。
2. visual mesh：无明显缺面、漂浮碎片、贴图错位。
3. collision mesh：面数低、稳定、不穿地、不爆炸。
4. 材质：贴图清晰；PBR 参数必须标记为 `estimated` 或 `measured`。
5. 导入测试：MuJoCo/MotrixSim 加载不报错，Isaac Sim/three.js 可预览。

场景级：

1. 地面水平、尺度正确、墙/门/桌面位置可用。
2. 关键物体能分离成独立 asset 或标为不可交互 scene prop。
3. scene.json 中每个 object 都有 pose、scale、category、source。
4. collision 场景能跑基本接触测试：机器人/物体不穿地，桌面可承托。
5. 包级验收会检查 parametric scene 中物体底面与地面/桌面/支撑面的 AABB 接触关系，悬空物体会列入 `unsupported_objects`。
6. 视觉层和物理层坐标对齐。

## 风险和限制

1. 纯 B/S 浏览器方案不适合高质量 iPhone 扫描主链路；ARKit、RoomPlan、LiDAR mesh 需要原生 App。
2. 自动分离不可能一次全对，必须有 Web QA 修正。
3. 透明、反光、无纹理物体是最大难点，瓶子如果是透明塑料或玻璃，建议单独资产模式 + KIRI Featureless/3DGS fallback + 人工质检。
4. 3DGS 视觉非常好，但不是 watertight mesh，不能直接用于碰撞、质量、惯性。
5. PBR 材质从普通手机照片中只能估计；如果要真实物理材质，需要受控光照、偏振、材质库或人工标注。
6. 仿真导出不是格式转换那么简单，必须生成 collision mesh、尺度、惯性、摩擦，否则导入成功也不能稳定用于机器人学习。
7. 云端重建会涉及隐私和数据合规，室内场景尤其要支持本地部署或私有化存储。

## 推荐方案

最实用的产品方案：

1. 自研 iPhone 采集 App，保证 capture 数据可控。
2. 自研 B/S Web 控制台和后端任务系统。
3. 第一版资产重建接 Apple Object Capture / KIRI API，避免早期卡死在重建质量上。
4. 场景重建以 RoomPlan/ARKit metric layer 为核心，3DGS 只作为视觉增强。
5. 仿真导出以 MJCF 为第一目标，兼容 MuJoCo 和 MotrixSim；同时产出 URDF/USD。
6. 所有输出都强制区分 `visual asset`、`collision asset`、`semantic layout`、`physics metadata`。
7. 上传包里有真实 OBJ/MTL 或 glTF 贴图时，把贴图保留到 `textures/` 并写进 manifest；没有真实贴图时明确标记缺失，不生成假材质。
8. Web 端重新分割必须重跑原始 RGB-D masks、RGB-D depth clustering 或配置的 SAM2 runner；没有真实 depth/intrinsics 且没有真实 mask 时返回失败。
9. 碰撞体优先走 CoACD convex decomposition；失败时在 report 中暴露 fallback 原因，不静默伪装成分解成功。
10. Mesh cleanup 会报告移除的小漂浮组件数量和面数；Web 质检面板显示 visual/collision 面数、collision part 数、贴图和 watertight 状态。
11. 场景验收会验证桌面、地面和物体的支撑接触关系；悬空物体不会被标记为通过。

如果要对接已有 Real2Motrix，建议沿用当前包结构：`scene.xml`、`scene.urdf`、`scene.json`、visual mesh、collision mesh、metadata/report、zip package。这样可以把这次方案直接变成 Real2Motrix 的产品化升级，而不是另起炉灶。

## 资料来源

1. Apple RealityKit Object Capture: https://developer.apple.com/documentation/realitykit/realitykit-object-capture
2. Apple RoomPlan overview: https://developer.apple.com/augmented-reality/roomplan/
3. Apple RoomPlan ML research: https://machinelearning.apple.com/research/roomplan
4. Apple ARKit scene reconstruction: https://developer.apple.com/documentation/arkit/visualizing-and-interacting-with-a-reconstructed-scene
5. COLMAP documentation: https://colmap.readthedocs.io/
6. OpenMVS repository: https://github.com/cdcseacave/openMVS
7. Nerfstudio export geometry: https://docs.nerf.studio/quickstart/export_geometry.html
8. 3D Gaussian Splatting paper: https://arxiv.org/abs/2308.04079
9. Meta SAM2: https://ai.meta.com/research/sam2/
10. Grounded-Segment-Anything: https://github.com/IDEA-Research/Grounded-Segment-Anything
11. KIRI Engine API: https://www.kiriengine.app/api
12. KIRI export formats: https://www.kiriengine.app/faq/what-kind-of-file-formats-can-kiri-engine-export
13. Polycam export formats: https://learn.poly.cam/hc/en-us/articles/27756102599572-What-File-Types-Can-Polycam-Export
14. MuJoCo XML reference: https://mujoco.readthedocs.io/en/3.3.3/XMLreference.html
15. MotrixSim documentation: https://motrixsim.readthedocs.io/
16. Isaac Sim URDF import: https://docs.isaacsim.omniverse.nvidia.com/latest/importer_exporter/import_urdf.html
