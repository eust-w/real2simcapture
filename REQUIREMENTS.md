# 需求说明

## 项目目标

建设一个面向 iPhone 扫描的 B/S 架构平台，支持通过手机采集真实物体和真实场景，重建为可预览、可编辑、可导出到机器人仿真器和机器学习管线的 3D 资产包。

平台必须服务两个不同功能：

1. 资产扫描：扫描单个物体，例如瓶子、杯子、零件，生成细致 3D 模型、贴图、材质估计、碰撞体和物理属性。
2. 场景扫描：扫描整个房间、桌面、工位或实验场景，重建场景几何和视觉层，并尽量自动分离可交互资产与静态场景。

## 核心需求

### 采集端

1. 支持 iPhone 作为主采集设备。
2. 支持实时或非实时采集，两种方式都可接受。
3. 资产扫描需要引导用户围绕物体采集足够多角度图像。
4. 场景扫描需要采集 RGB、深度、相机位姿、场景 mesh 和 RoomPlan 语义布局。
5. 采集过程中要做质量提示，包括模糊、曝光、覆盖角度、跟踪丢失和尺度校验。

### 重建端

1. 可以从手机照片、视频、深度和位姿数据生成 3D mesh。
2. 资产重建要尽量保留细节和贴图。
3. 场景重建要区分可测量几何层和高保真视觉层。
4. 需要支持透明、反光、低纹理物体的 fallback 方案。
5. 重建结果需要可追踪每一步输入、输出、日志、失败原因和质量报告。

### 自动分离

1. 系统应自动识别并分离场景中的物体、桌面、墙、地面、家具和固定结构。
2. 自动分离不能假定 100% 正确，必须提供 Web 端人工校正能力。
3. 用户应能在 Web 端合并、拆分、重命名、删除和重新分割物体。
4. 分离后的物体应能作为独立资产导出。
5. 静态场景应能作为 residual scene geometry 导出。

### 仿真导出

1. 不只导出好看的 3D 模型，还必须导出仿真可用资产。
2. 必须区分 visual mesh 和 collision mesh。
3. 必须生成尺度、质量、惯性、摩擦、材质类别、语义类别和 pose 元数据。
4. 首要支持 MuJoCo/MotrixSim 的 MJCF 输出。
5. 同时支持 URDF、USD/USDZ、GLB、OBJ 和统一 manifest。
6. 导出的包应能进入机器人仿真器、视觉训练、强化学习或模仿学习数据管线。

## 目标输出

一个完整任务输出包应至少包含：

1. `assets/*_visual.glb` 或 `assets/*_visual.obj`
2. `assets/*_collision.obj`
3. `textures/*`
4. `scene.json`
5. `asset.json` 或 `manifest.json`
6. `scene.xml`
7. `scene.urdf`
8. `scene.usd` 或 `scene.usdz`
9. `report.json`
10. `README.md`

## 验收标准

### 资产扫描验收

1. 一个普通非反光瓶子能通过 iPhone 采集生成带贴图 visual mesh。
2. 同一瓶子能生成低面数 collision mesh。
3. MuJoCo/MotrixSim 能加载瓶子资产并完成基本接触测试。
4. Web 端能预览 visual mesh、collision mesh 和导出包内容。
5. 质量报告能显示尺度、面数、贴图、碰撞体、物理参数和置信度。

### 场景扫描验收

1. 一个桌面或房间角落能被扫描成带尺度的场景。
2. 系统能识别地面、桌面、墙体和至少一个独立物体。
3. 用户能在 Web 端修正自动分割结果。
4. 导出场景在 MuJoCo/MotrixSim 中能保持地面、桌面和物体的基本接触关系。
5. 视觉层和物理层坐标对齐。

## 非目标

1. 第一版不承诺纯浏览器完成高质量 LiDAR/RoomPlan 扫描。
2. 第一版不承诺普通手机照片能精确测量真实 PBR 材质参数。
3. 第一版不承诺透明玻璃、强反光金属和纯黑/纯白低纹理物体一次性自动重建完美。
4. 第一版不承诺全自动分离完全正确，必须允许人工校正。

## 当前推荐实现方向

1. iPhone 原生采集 App：SwiftUI + ARKit + RoomPlan + RealityKit Object Capture。
2. Web 控制台：React + TypeScript + three.js。
3. 后端：FastAPI + Postgres + Redis queue + object storage。
4. 重建：Apple Object Capture、COLMAP/OpenMVS、Nerfstudio/3DGS、KIRI API fallback。
5. 分割：RoomPlan + Grounded-SAM2/SAM2 + RGB-D lifting + 3D clustering。
6. Mesh/物理处理：Blender、trimesh、Open3D、CoACD/V-HACD。
7. 导出：MJCF、URDF、USD、GLB、OBJ、manifest。
