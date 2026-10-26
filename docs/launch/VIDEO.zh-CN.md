# real2simcapture 介绍视频与平台发布草案

状态：这是未来真机演示片的拍摄方案，尚未对外发布。平台范围已确认：GitHub README、B站、YouTube、抖音、小红书。目标账号尚未确认。单独制作的开发预览介绍片不能替代本方案要求的真机镜头。

## 核心叙事

用同一份真实场景贯穿“实物 -> iPhone 采集 -> Web 检查 -> 导出 -> 仿真运行”，展示开发者怎样复现。名称统一使用 real2simcapture。

候选中文标题：**用 iPhone 把桌面带进机器人仿真：real2simcapture**。

候选英文标题：**From iPhone Capture to Robot Simulation | real2simcapture**。

上面两个标题及下面首发台词仅在真机闭环验收完成后使用。现阶段若发布进展内容，标题用“real2simcapture 开发记录：iPhone 到机器人仿真的工具链”，明确说明真机验收仍在进行。

## 素材清单

| 素材 | 要拍到的内容 | 验收要求 |
| --- | --- | --- |
| A 实物 | 桌面、物体与可见标尺 | 场景和素材有公开授权，画面无个人信息 |
| B 手机 | App 启动、采集、结束、上传 | 同时保留手机录屏和能看到手机绕场景移动的外拍 |
| C Web | 同一个 session 的网格版本与三维几何更新 | 必须来自本次真机采集；现有上传/刷新代码仍需设备验收 |
| D 模型 | 本次任务生成的视觉模型和碰撞几何 | 不用测试立方体、他人样例或生成动画替代真实结果 |
| E 仿真 | 对应导出包实际加载、运行 | 记录引擎版本；仅 headless 通过不能冒充已经有图形演示 |
| F 证据 | 输入摘要、参数来源、验证报告 | 能对应同一个任务；密钥、用户名、主机地址不入镜 |
| G 仓库 | 公开 release、示例和安装说明 | 仓库公开并可用后才录“已经开源”的结尾 |

目前项目目录未发现成片源视频，不能开始以真机结果为主角的正式剪辑。代码截图或架构动画只能用于技术说明。

## 90 秒横版分镜

这是建议节奏，不是对采集或重建耗时的承诺。等待或处理片段如有压缩，画面注明实际用时/加速倍数。

| 时间 | 画面 | 中文旁白草案 | 证据要求 |
| --- | --- | --- | --- |
| 0-6 秒 | 实物与同一场景在引擎里的结果对照 | “这张桌面，用 iPhone 采集后，被带进了机器人仿真。” | 仅在真实闭环完成后录制 |
| 6-16 秒 | iPhone 绕桌面移动，叠加 App 实际录屏 | “real2simcapture 记录图像、深度和相机位姿，保留场景处理需要的原始数据。” | 来自真机采集包；实测机型字幕 |
| 16-28 秒 | Web 收到帧和实际 ARKit 网格快照 | “数据上传到工作站，网格随采集更新。高质量贴图和最终资产包在后续步骤处理。” | 必须拍到真实网格，不用 bounds 或测试夹具替代 |
| 28-43 秒 | 实际处理完成后的几何检查 | “接着检查几何与尺度，并查看物理参数的来源。估算的质量和摩擦仍需要按用途校正。” | 模型须来自此次任务；参数标记可读 |
| 43-58 秒 | 视觉/碰撞切换，展示导出目录 | “仿真包包含视觉、碰撞和场景描述。这个例子导出为 MuJoCo 使用的 MJCF。” | 不加入尚未验证的引擎徽标或效果 |
| 58-73 秒 | 引擎加载同一导出包并运行 | “这里显示的是导出包的实际加载与运行。能运行是起点，物理精度还要继续测量。” | 保留引擎运行记录；有真实交互才描述交互 |
| 73-83 秒 | 输入样例与复现命令 | “同一份采集样例和复现步骤随版本提供，方便检查结果、替换模块和报告问题。” | 示例已经获准公开并确实随 release 提供 |
| 83-90 秒 | 仓库名、版本、公开地址 | “real2simcapture，一个面向机器人开发者的 iPhone 采集到仿真工具链。” | 版本与公开状态真实；不承诺无人验收的一键流程 |

英文配音或字幕采用相同证据边界。例如 Live 片段使用：

> Frames are uploaded to the workstation as capture continues. The current live view shows capture status and scene bounds; full model processing happens afterward.

## 40 秒竖版结构

1. 0-5 秒：实物与真实导出结果的对照，占据主体画面。
2. 5-14 秒：手机采集，字幕“图像 / 深度 / 相机位姿”。
3. 14-24 秒：真实处理后的视觉和碰撞结果。等待过程标出时间压缩。
4. 24-34 秒：同一仿真包加载运行，显示实际引擎名。
5. 34-40 秒：real2simcapture 名称和简短硬件要求，仓库地址按平台允许方式呈现。

竖版不把整个桌面 UI 缩成难以阅读的小窗；按镜头裁切对应操作区域，保留模型和结果。字幕不覆盖关键几何或平台常见交互区域，并在实际预览中检查。

## 成片规格

以下是制作目标，不是各平台上传上限；上传前再检查目标账号后台规则。

- 横版：1920x1080、16:9、30 fps，90 秒，MP4/H.264/AAC；B站中文主版，YouTube 提供英文字幕或独立英文版。
- 竖版：1080x1920、9:16、30 fps，约 40 秒；分别为抖音、小红书调整封面和结尾。
- GitHub：8-12 秒短循环，取真实采集与结果对照；静态封面和完整视频链接配套提供。
- 交付：横竖版 MP4、无字幕母版、中文/英文 SRT、封面、公开素材来源说明。
- 使用原创旁白或有授权的音频；背景音乐不得遮盖操作讲解。

## 平台文案

以下为闭环验收及仓库公开后的候选文案，不可直接当作当前完成情况发布。

### B站

标题：用 iPhone 把桌面带进机器人仿真 | real2simcapture 开发预览

简介：

> 这个视频展示一次真实采集到仿真运行的流程：iPhone 记录图像、深度和位姿，工作站处理数据，再导出带视觉与碰撞几何的资产包。
>
> real2simcapture 面向机器人开发者，目前是开发预览。Live 路径显示采集状态和场景范围；完整模型需要后续处理。质量、摩擦等估算参数不能当作测量值。
>
> 代码、已授权的样例和复现步骤见仓库。视频说明中补充本次实测机型、软件版本和处理用时。

### YouTube

Title: From iPhone Capture to Robot Simulation | real2simcapture

Description:

> A walkthrough of one captured scene, from iPhone RGB-D data to an exported simulation package.
>
> real2simcapture is a developer preview for robotics workflows. This demonstration covers capture, inspection, visual and collision geometry, and a verified simulator import. The current live path reports capture status and scene bounds; full model processing is a separate step. Estimated physical parameters require validation.
>
> Source code, the licensed sample, and reproduction steps are linked in the repository. Hardware, software versions, and actual processing time accompany this demo.

### 抖音

封面：iPhone 采集 -> 机器人仿真

文案：这次用同一张桌面，走完手机采集、模型处理和仿真导入。real2simcapture 仍是开发预览，处理过程有耗时，物理参数需要校正。视频保留真实结果和当前限制。

### 小红书

封面：用手机做机器人仿真资产

文案：做机器人场景，除了扫描外观，还要处理尺度、碰撞和物理参数来源。real2simcapture 把这些环节连成一条可检查的流程。这条记录展示同一场景从 iPhone 到仿真的过程，并附实测设备、输入数据和复现步骤。当前适合愿意配置开发环境的开发者，不是面向所有手机的一键扫描工具。

### GitHub README

首屏建议：项目名、一句话定位、真实演示、三个可证实能力、快速开始、硬件/限制、许可证和贡献入口。中英文文档互链，长篇架构设计移入 docs。发布后的短演示说明：

> One capture, one reproducible simulation package. See the sample and reproduction instructions for the exact hardware, inputs, and validated output.

## 发布检查

- [ ] 每个镜头都对应实际功能与同一份真实输入；未知结果不补画。
- [ ] 机型、软件版本、处理时间和加速片段标注准确。
- [ ] 中文字幕、英文字幕、封面与手机/桌面预览通过检查。
- [ ] 无账号、密码、验证码、私人场景信息或未授权内容。
- [ ] LICENSE、代码、样例和公开 release 链接均可访问。
- [ ] 各平台目标账号、可见性、封面和发布时间已确定。
- [ ] 平台发布成功后记录实际链接；失败或等待审核不记为发布成功。

账号侧尚未完成连接。插件目录中发现可提供社交发布能力的 Metricool，但当前未安装，且未验证它覆盖本次全部平台；不能据此承诺已能自动跨平台发布。本文未创建定时发布任务。
