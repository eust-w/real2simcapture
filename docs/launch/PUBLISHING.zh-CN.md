# 开发预览介绍片交付

日期：2026-10-26。**视频已导出，尚未在任何平台上传或发布。仓库仍为私有，许可证待确认。**

本片介绍代码和项目工作流，不是真机扫描演示。没有使用回归测试网格、生成场景或第三方扫描素材冒充采集结果。未来的真机演示分镜另见 [VIDEO.zh-CN.md](VIDEO.zh-CN.md)。

## 文件

本地输出位于仓库的 `.build/promo/`，不随 Git 分发：

| 文件 | 内容 |
| --- | --- |
| `real2simcapture-intro-landscape.mp4` | 1920x1080、30 fps、H.264/AAC，约 62.29 秒 |
| `real2simcapture-intro-portrait.mp4` | 1080x1920、30 fps、H.264/AAC，约 62.29 秒 |
| `intro.zh.srt` / `intro.en.srt` | 中文旁白字幕、英文翻译；独立字幕文件，未烧录到画面 |
| `landscape-0.png` / `portrait-0.png` | 横竖封面 |
| `manifest.json` | 生成时间、源码版本、素材来源、各镜头时长和媒体探测结果 |

封面和字幕的可版本管理副本在 [assets](assets/)。没有制作虚假的“扫描结果”短循环。

配音为 macOS `say` / Tingting 合成中文旁白，不是用户的克隆声音；无背景音乐、无第三方录音。发布时按平台要求披露合成配音。音轨峰值约 -2.7 dB、平均约 -18.6 dB；完成了音轨存在性、解码和非静音检查，没有声称进行人工逐句听审。

## 素材来源

1. 原生采集片段：`ios/Real2SimCapture/Sources/ARSceneCaptureScreen.swift`，渲染时直接读取文件，不另编演示代码。
2. 导出片段：`backend/app/exporters.py` 的实际 MJCF、URDF、USD 写出语句。
3. Web：本项目实际运行的未采集工作台截图，只展示界面，不伪造采集结果；发布画面裁切不包含本地依赖路径。
4. 标题、流程排版和旁白为本项目新制内容。源码公开权属仍需确认。

两个方向均完成页面尺寸溢出检查，并抽查源码帧、界面帧、结尾和编码后视频帧。视频不包含账号密码、验证码、签名证书、真实私人房间或云主机连接信息。

## 重新生成

需要 macOS 系统语音、FFmpeg、项目 Node 依赖及 Chromium/Chrome。先按[安装说明](../SETUP.md)运行浏览器检查，得到实际工作台截图，再从仓库根目录执行：

```sh
export CHROMIUM_PATH="$(node -p 'require("./frontend/node_modules/playwright").chromium.executablePath()')"
node scripts/render_preview_video.mjs
```

脚本会生成音轨、画面、两个 MP4、中英文 SRT 和 manifest。修改台词后必须重新检查时长、布局、内容准确性及是否仍符合“非真机演示”标注。

## 各平台文案

以下专门对应当前开发预览片，不可替换为“已完成真实扫描”或“已经开源”的说法。

### B站

标题：iPhone 到机器人仿真，工具链怎么搭？real2simcapture 开发预览

简介：扫描外观只是开始，机器人仿真还需要尺度、碰撞几何和物理参数来源。这期用实际源码和运行中的工作台介绍 real2simcapture：原生采集、Live 网格传输、Web 检查与资产导出。当前仍是开发预览，真机签名安装、连续采集及引擎闭环待验收。项目开源筹备中，公开授权和许可证确认后再发布。这不是扫描效果演示；中文旁白由语音合成生成。

标签：机器人、计算机视觉、iPhone、ARKit、三维重建、开发记录

### YouTube

Title: Building an iPhone-to-Simulation Pipeline | real2simcapture Developer Preview

Description: A source-based introduction to real2simcapture: native capture, periodic ARKit mesh uploads, a Web workbench, and simulation asset export. This is not a physical-device scanning demo. Device signing, continuous capture and engine acceptance remain pending. Public source release awaits ownership and license confirmation. Includes synthesized Mandarin narration and an English subtitle file. Estimated physical parameters are not measurements.

Tags: robotics, ARKit, iPhone, 3D reconstruction, simulation assets, developer preview

使用横版，并上传 `intro.en.srt` 与 `intro.zh.srt`。不要填尚不可公开访问的仓库地址作为可用下载链接。

### 抖音

封面：iPhone 采集，怎样接到机器人仿真？

文案：模型外观之外，还要处理尺度、碰撞和参数来源。real2simcapture 开发记录：原生采集、Live 网格与导出代码。真机闭环待验收，开源筹备中。本条为代码介绍，非扫描效果演示；使用合成配音。#机器人 #三维重建 #开发日常

### 小红书

标题：做机器人仿真资产，扫描之后还缺什么？

正文：最近在整理 real2simcapture。目标是连接 iPhone 原生采集、工作台检查和仿真资产导出。视频里展示的是实际代码与空工作台，没有用测试几何冒充真实扫描。当前已补上 Live 网格传输；签名安装、长时间采集、真实引擎闭环还需要设备验收。准备开源，但公开授权和许可证尚未确认。使用合成配音。#机器人开发 #iPhone #三维重建 #项目记录

### GitHub README

首屏封面已加入中英文 README。公开后才追加真正可访问的视频或 release 链接，当前不编造发布地址。

## 发布台账

| 平台 | 目标账号 | 状态 | 公开链接 |
| --- | --- | --- | --- |
| GitHub | 已有私有仓库 eust-w/real2simcapture | 私有预览分支及草稿 PR；未公开 | 无公开 release |
| B站 | 未确认 | 文件与文案已备；未上传 | 无 |
| YouTube | 未确认 | 文件与中英文字幕已备；未上传 | 无 |
| 抖音 | 未确认 | 竖版与文案已备；未上传 | 无 |
| 小红书 | 未确认 | 竖版与文案已备；未上传 | 无 |

发布前需要：权利人确认源码及画面可公开、选择许可证、确认每个平台目标账号并完成登录。任何平台的“上传中”“待审核”“草稿”都不能记录为公开发布成功。本轮没有创建自动发布任务。
