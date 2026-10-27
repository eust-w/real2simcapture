# 开源开发预览介绍片

更新日期：2026-10-27。源码已按 [Apache-2.0](../../LICENSE) 公开，版本为 [v0.1.0-alpha.1](https://github.com/eust-w/real2simcapture/releases/tag/v0.1.0-alpha.1)。介绍片已更新开源状态和下载地址；不再使用旧版“开源筹备”“许可证待确认”的旁白。

**这是代码与工作流介绍，不是真机扫描演示。** 画面来自实际源码和真实运行的空工作台。没有用测试网格、生成场景或第三方扫描素材冒充采集结果。真机签名安装、连续扫描和目标引擎闭环仍待验收，没有可直接安装的签名 App。未来真机实录计划见 [VIDEO.zh-CN.md](VIDEO.zh-CN.md)。

## 媒体文件

本轮输出保存在 `.build/promo-open-source-20261027/`，旧版 `.build/promo/` 保留但不再用于发布。

| 文件 | 内容 |
| --- | --- |
| `real2simcapture-intro-landscape.mp4` | 1920x1080、30 fps、H.264/AAC，约 64.82 秒；B站、YouTube |
| `real2simcapture-intro-portrait.mp4` | 1080x1920、30 fps、H.264/AAC，约 64.82 秒；抖音、小红书 |
| `intro.zh.srt` / `intro.en.srt` | 中文旁白与英文翻译，独立字幕，未烧录 |
| `landscape-0.png` / `portrait-0.png` | 横竖版封面 |
| `manifest.json` | 源码版本、生成脚本 SHA-256、旁白、镜头时长和媒体探测结果 |

封面与字幕副本在 [assets](assets/)。配音是 macOS `say` / Tingting 合成中文旁白，不是用户的克隆声音；无背景音乐、无第三方录音。发布文案必须披露合成配音，平台有相关声明选项时同步设置。

公开下载：[横版视频](https://github.com/eust-w/real2simcapture/releases/download/v0.1.0-alpha.1/real2simcapture-intro-landscape.mp4) · [竖版视频](https://github.com/eust-w/real2simcapture/releases/download/v0.1.0-alpha.1/real2simcapture-intro-portrait.mp4) · [中文字幕](https://github.com/eust-w/real2simcapture/releases/download/v0.1.0-alpha.1/intro.zh.srt) · [英文字幕](https://github.com/eust-w/real2simcapture/releases/download/v0.1.0-alpha.1/intro.en.srt)。两个视频已匿名下载，并与原文件核对 SHA-256。

已完成两个视频的完整解码、音轨存在性与非静音检查、横竖画面溢出检查及片头/片尾抽查。音轨峰值约 -2.7 dB、平均约 -18.5 dB。未声称人工逐句听审。

## 素材来源

1. `ios/Real2SimCapture/Sources/ARSceneCaptureScreen.swift`：渲染时读取实际源码，展示原生采集和周期网格上传。
2. `backend/app/exporters.py`：实际 MJCF、URDF、USD 写出代码；并非目标引擎运行画面。
3. `.build/browser/workbench-empty.png`：2026-10-26 实际工作台截图，未开始采集，不包含私人场景。
4. 本项目原创排版和旁白。公开视频不含账号密码、验证码、签名证书或云主机连接信息。

## 重新生成

需要 macOS 系统语音、FFmpeg、项目 Node 依赖和 Chrome/Chromium，以及实际空工作台截图。不要将浏览器测试生成的网格截图用作扫描成果。

```sh
PREVIEW_OUTPUT_DIR=.build/promo-open-source-20261027 node scripts/render_preview_video.mjs
```

如不使用已安装的 Chrome，可设置 `CHROMIUM_PATH`。每次修改旁白后都应重新检查时长、布局、内容准确性和“非真机演示”标注。

## 平台文案

机器可读副本见 [platform-copy.json](platform-copy.json)。所有平台使用同一事实边界，不承诺扫描精度、延迟或生产可用性。

### B站

标题：iPhone 到机器人仿真：real2simcapture 开源了，哪些环节还没跑通？

简介：扫描外观只是开始，机器人仿真还需要尺度、碰撞几何和物理参数来源。real2simcapture 已按 Apache-2.0 开源：这期用实际源码与空工作台介绍原生采集、Live 网格传输、Web 检查和 MJCF / URDF / USD 导出。当前为开发预览，真机签名安装、连续扫描和目标引擎闭环待验收，不提供签名 App。本片不是扫描效果演示，中文旁白为合成语音。源码：https://github.com/eust-w/real2simcapture

标签：开源、机器人、iPhone、ARKit、三维重建、开发记录

### YouTube

Title: real2simcapture Is Open Source | iPhone-to-Simulation Developer Preview

Description: An open-source capture and simulation-asset pipeline for robotics developers. This source-based introduction covers native iPhone capture, periodic ARKit mesh uploads, a Web workbench, and MJCF / URDF / USD export. Apache-2.0 source: https://github.com/eust-w/real2simcapture

This is a developer preview, not a physical-device scanning demo. Device signing, continuous scanning and target-engine acceptance remain pending. No signed installable iPhone app is distributed. Estimated physical parameters are not measurements. Actual code and an empty workbench are shown; no fabricated scan results. Includes synthesized Mandarin narration, with Chinese and English subtitle files.

Tags: robotics, ARKit, iPhone, open source, 3D reconstruction, developer preview

使用横版，语言设为中文，并上传中英文字幕。不将“合成配音”描述为用户本人录音。

### 抖音

标题：iPhone到仿真，工具链开源了

文案：扫描出模型，还不等于机器人能用。real2simcapture 已开源：原生采集、Live 网格、Web 检查与资产导出。当前为开发预览，真机连续扫描和引擎闭环待验收，没有签名安装包。本片是实际代码与空工作台介绍，非扫描效果演示；合成配音。源码：GitHub 搜索 eust-w/real2simcapture。#开源 #机器人 #三维重建

### 小红书

标题：iPhone到仿真，工具链开源了

正文：把手机采集接到机器人仿真，中间不只是一个模型文件。real2simcapture 已按 Apache-2.0 开源，整理了原生采集、Live 网格传输、工作台检查和 MJCF / URDF / USD 导出代码。视频展示实际源码与空工作台，不拿测试网格冒充扫描成果。当前为开发预览：签名安装、连续扫描和目标引擎闭环待验收，没有签名 App。源码在 GitHub：eust-w/real2simcapture。本片使用合成配音。#开源项目 #机器人开发 #iPhone #三维重建

## 发布台账

| 平台 | 当前状态 | 链接 |
| --- | --- | --- |
| GitHub 源码 | 已公开，Apache-2.0 | [仓库](https://github.com/eust-w/real2simcapture) |
| GitHub 视频 | 两个 MP4、双语字幕、两张封面已公开；MP4 匿名下载校验通过 | [Release](https://github.com/eust-w/real2simcapture/releases/tag/v0.1.0-alpha.1) |
| B站 | 审核完成、1080P 转码完成，公开页面与实际播放已核实 | [BV1S9xT6zEYd](https://www.bilibili.com/video/BV1S9xT6zEYd/) |
| YouTube | 已公开，实际播放已核实，中英文字幕均已发布 | [tMlDCd1nMvA](https://www.youtube.com/watch?v=tMlDCd1nMvA) |
| 抖音 | 创作者中心显示“已发布”，公开页面与实际播放已核实 | [7701264760116923690](https://www.douyin.com/video/7701264760116923690) |
| 小红书 | 提交被账号限制拒绝；已保留草稿，未公开 | 无 |

上传完成、审核中、草稿均不等于公开发布。每个平台分别核对账号、内容与公开链接，保留本地证据；不创建自动发布任务。

本轮于 2026-10-27 连接已登录浏览器，逐一核对账号和稿件，B站、YouTube、抖音各提交一次。三个公开页面均加载了对应视频并实际播放，不只依据提交成功提示；核验在当前浏览器登录状态下进行，不等同于所有地区的匿名播放测试。核验截图与详细操作台账仅保存在本地忽略目录，不将创作者后台、浏览器日志或账号信息上传源码仓库。

- 四个平台的投稿均设置 AI 内容声明，文案说明合成旁白和非真机演示。
- YouTube 自定义封面要求手机号验证，未绕过限制，改用视频内项目名画面。中文字幕与英文字幕在 Studio 中均显示“已发布”；外部链接可点击权限仍需账号自行完成平台验证。
- 抖音自动章节误识别了术语并将部分内容称为“扫描演示”。已替换为准确的五个章节和总结，公开页面已核实生效。
- 小红书提交明确返回“因违反社区规范禁止发笔记”。停止重试，并核实本条介绍片出现在草稿箱；草稿存于当前浏览器本地，清除浏览器数据会丢失。需要账号持有人通过平台处理限制，解除后再发布，当前没有公开链接。
