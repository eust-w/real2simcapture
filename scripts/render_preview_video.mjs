// Source-based project introduction, never a substitute for device demonstration footage.
import fs from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.resolve('frontend/node_modules/playwright'));
const root = process.cwd();
const out = path.resolve(process.env.PREVIEW_OUTPUT_DIR || path.join(root, '.build/promo'));
await fs.mkdir(out, { recursive: true });
const escape = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const swift = await fs.readFile('ios/Real2SimCapture/Sources/ARSceneCaptureScreen.swift', 'utf8');
const exports = await fs.readFile('backend/app/exporters.py', 'utf8');
function excerpt(source, marker, count) {
  const lines = source.split('\n');
  const start = lines.findIndex(line => line.includes(marker));
  if (start < 0) throw new Error(`Source marker missing: ${marker}`);
  const selected = lines.slice(start, start + count);
  const indent = Math.min(...selected.filter(line => line.trim()).map(line => line.search(/\S/)));
  return selected.map((line, index) => `${start + index + 1}  ${line.slice(indent)}`).join('\n');
}
const screenshot = await fs.readFile('.build/browser/workbench-empty.png');
const scenes = [
  {
    label: 'OPEN SOURCE / APACHE-2.0', title: 'real2simcapture', accent: '从 iPhone 采集，到机器人仿真资产',
    body: '<div class="pipeline"><span>CAPTURE</span><b>→</b><span>INSPECT</span><b>→</b><span>EXPORT</span></div><p class="note">已开源 · 面向机器人开发者的工具链</p>',
    zh: 'real2simcapture 已经开源。这是面向机器人开发者的采集与资产处理工具链。本片介绍实际代码和工作流，不是真机扫描演示。',
    en: 'real2simcapture is now open source: a capture and asset pipeline for robotics developers. This video shows actual code and workflow, not a physical-device scanning demonstration.',
  },
  {
    label: '01 / NATIVE CAPTURE', title: '保留原始数据', accent: 'RGB · 深度 · 位姿 · 相机内参',
    body: `<pre>${escape(excerpt(swift, 'trackingState: trackingState,', 7))}</pre><p class="source">ARSceneCaptureScreen.swift · 实际源码节选</p>`,
    zh: '原生采集代码记录图像、深度、相机位姿和内参。设备能力必须实际支持，缺少深度的手机不能冒充激光雷达采集。',
    en: 'The native capture code records images, depth, camera poses and intrinsics. Capture requires compatible hardware; missing depth is never a substitute for LiDAR data.',
  },
  {
    label: '02 / LIVE MESH', title: '网格随采集更新', accent: 'ARKit 重建 → 网格快照 → HTTP 上传',
    body: `<pre>${escape(excerpt(swift, 'let snapshot = root.appendingPathComponent', 7))}</pre><p class="source">ARSceneCaptureScreen.swift · 周期上传实现</p>`,
    zh: 'Live 路径把 ARKit 生成的网格快照周期上传。网络积压时，采样帧保留在手机本地。实际延迟还需要真机测量。',
    en: 'The Live path periodically uploads mesh snapshots reconstructed by ARKit. Sampled frames are retained locally during network backlog. Device latency still requires measurement.',
  },
  {
    label: '03 / WEB WORKBENCH', title: '检查，而不是猜测', accent: '采集状态 · 网格版本 · 任务与依赖',
    body: `<div class="screen"><img src="data:image/png;base64,${screenshot.toString('base64')}" alt="Actual workbench before capture" /></div><p class="source">实际工作台截图 · 未开始采集 · 不展示合成扫描结果</p>`,
    zh: '工作台显示采集状态、网格版本和处理任务。这里是实际运行的空工作台；没有真实采集结果，就不填入虚构的场景。',
    en: 'The workbench shows capture status, mesh versions and processing tasks. This is an actual empty workbench, with no fabricated scan result.',
  },
  {
    label: '04 / SIMULATION ASSETS', title: '不止于一个模型', accent: '视觉几何 · 碰撞几何 · 参数来源',
    body: `<pre>${escape(excerpt(exports, '(output_dir / "scene.xml").write_text', 3))}</pre><div class="formats"><span>MJCF</span><span>URDF</span><span>USD</span></div><p class="source">exporters.py · 导出代码；引擎验收另行进行</p>`,
    zh: '导出代码支持 MJCF、URDF 和 USD，并区分视觉与碰撞几何。估算的质量和摩擦不是测量值，输出还需要在目标引擎里验收。',
    en: 'Export code supports MJCF, URDF and USD, with separate visual and collision geometry. Estimated mass and friction are not measurements. Outputs require target-engine acceptance.',
  },
  {
    label: 'OPEN-SOURCE DEVELOPER PREVIEW', title: '源码已公开', accent: 'Apache-2.0 · v0.1.0-alpha.1',
    body: '<div class="checklist"><p><b>已有</b> 原生采集、Live 网格与导出代码</p><p><b>待验收</b> 签名安装、连续扫描与引擎导入</p><p><b>参与</b> 阅读源码、报告问题、贡献改进</p></div><p class="note">github.com/eust-w/real2simcapture</p>',
    zh: '源码已按 Apache 二点零许可证公开，欢迎查看和贡献。当前仍是开发预览：真机签名安装、连续扫描和引擎导入待验收，还没有可直接安装的签名应用。',
    en: 'Source is available under Apache-2.0. Explore the code and contribute. This remains a developer preview: device signing, continuous capture and engine import await acceptance. No signed installable app is distributed.',
  },
];
const browser = await chromium.launch({ ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : { channel: 'chrome' }), headless: true });
const page = await browser.newPage();
const durations = [];
const run = (command, args) => execFileSync(command, args, { stdio: 'pipe', timeout: 300000 });
const probe = file => JSON.parse(run('ffprobe', ['-v', 'error', '-show_format', '-show_streams', '-of', 'json', file]).toString());
const voice = process.env.PREVIEW_VOICE || 'Tingting';
try {
  for (let i = 0; i < scenes.length; i++) {
    const audio = path.join(out, `voice-${i}.aiff`);
    run('say', ['-v', voice, '-r', '195', '-o', audio, scenes[i].zh]);
    durations.push(Math.ceil((Number(probe(audio).format.duration) + 0.7) * 30) / 30);
  }
  for (const [format, width, height] of [['landscape', 1920, 1080], ['portrait', 1080, 1920]]) {
    await page.setViewportSize({ width, height });
    const clips = [];
    for (let i = 0; i < scenes.length; i++) {
      const scene = scenes[i];
      const html = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>
        *{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;background:#101314;color:#f5f7f7;font-family:"PingFang SC",sans-serif;letter-spacing:0}
        main{height:100%;padding:64px 88px 50px;display:grid;grid-template-rows:44px 1fr 116px;gap:28px;border-top:10px solid #a8ee66}
        header{display:flex;justify-content:space-between;align-items:center;font-size:26px;color:#b8c0c1}header b{color:#a8ee66;font-weight:600}
        section{display:flex;flex-direction:column;justify-content:center;min-height:0;min-width:0}h1{font-size:${i === 0 ? 126 : 88}px;line-height:1.15;margin:0 0 20px;font-weight:650;overflow-wrap:anywhere}
        h2{font-size:36px;font-weight:500;color:#8ae0e0;margin:0 0 38px}pre{font:27px/1.65 Menlo,monospace;white-space:pre-wrap;overflow-wrap:anywhere;border-left:5px solid #a8ee66;padding:20px 0 20px 30px;margin:0;color:#d8e4df}
        .source{font-size:24px;color:#a4adae;margin:20px 0 0}.note{font-size:34px;color:#b9c2c3;margin-top:36px}.pipeline{display:flex;gap:42px;font-size:48px;margin:40px 0}.pipeline b{color:#ffb286}.formats{display:flex;gap:52px;font-size:50px;color:#a8ee66;margin-top:40px}
        .screen{width:100%;height:360px;overflow:hidden;background:#fff}.screen img{display:block;width:100%;height:auto}.checklist p{font-size:34px;margin:28px 0}.checklist b{color:#a8ee66;margin-right:20px}
        footer{border-top:1px solid #424a4c;padding-top:24px;display:flex;justify-content:space-between;align-items:start;gap:30px;font-size:25px;color:#c7cecf}footer strong{color:#ffb286;font-weight:500}.count{font:30px Menlo,monospace}.bar{position:fixed;bottom:0;left:0;width:${(i + 1) / scenes.length * 100}%;height:8px;background:#8ae0e0}
        ${format === 'portrait' ? `main{padding:112px 64px 120px;grid-template-rows:72px 1fr 220px;gap:50px}header{font-size:25px;align-items:start;gap:40px}header b{max-width:340px;text-align:right}h1{font-size:${i === 0 ? 88 : 82}px;line-height:1.25}h2{font-size:38px;line-height:1.65;margin-bottom:55px}pre{font-size:24px;line-height:1.9;padding-left:22px}.pipeline{flex-direction:column;gap:22px;font-size:60px;margin:25px 0}.pipeline b{font-size:38px}.source{font-size:26px;line-height:1.7}.screen{height:620px}.screen img{width:1600px;max-width:none;transform:translateX(-330px)}.checklist p{font-size:35px;line-height:1.8;margin:32px 0}.checklist b{display:block}.formats{font-size:48px;gap:36px}.note{font-size:34px;line-height:1.8}footer{font-size:28px;line-height:1.75;flex-direction:column;gap:16px}` : ''}
        </style><main><header><span>real2simcapture</span><b>${escape(scene.label)}</b></header><section><h1>${escape(scene.title)}</h1><h2>${escape(scene.accent)}</h2>${scene.body}</section><footer><div>项目介绍 / 非真机扫描演示<br><strong>开发预览 · 真机验收待完成</strong></div><div class="count">0${i + 1} / 06</div></footer></main><div class="bar"></div></html>`;
      await page.setContent(html, { waitUntil: 'load' });
      await page.evaluate(() => document.fonts.ready);
      const fits = await page.evaluate(() => document.documentElement.scrollHeight === innerHeight && document.documentElement.scrollWidth === innerWidth && document.querySelector('section').getBoundingClientRect().bottom <= document.querySelector('footer').getBoundingClientRect().top);
      if (!fits) throw new Error(`Slide overflow: ${format}/${i}`);
      const png = path.join(out, `${format}-${i}.png`);
      await page.screenshot({ path: png });
      const clip = path.join(out, `${format}-${i}.mp4`);
      const duration = durations[i];
      run('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-loop', '1', '-framerate', '30', '-i', png, '-i', path.join(out, `voice-${i}.aiff`), '-t', String(duration), '-vf', `fade=t=in:st=0:d=0.3,fade=t=out:st=${duration - 0.3}:d=0.3,format=yuv420p`, '-af', 'apad', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-threads', '2', '-c:a', 'aac', '-b:a', '160k', '-ar', '48000', '-movflags', '+faststart', clip]);
      clips.push(clip);
      console.log(`Rendered ${format} ${i + 1}/${scenes.length}`);
    }
    const concat = path.join(out, `${format}-concat.txt`);
    await fs.writeFile(concat, clips.map(file => `file '${file.replaceAll("'", "'\\''")}'`).join('\n'));
    run('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', concat, '-c', 'copy', '-movflags', '+faststart', path.join(out, `real2simcapture-intro-${format}.mp4`)]);
  }
} finally {
  await browser.close();
}
const stamp = seconds => new Date(Math.round(seconds * 1000)).toISOString().slice(11, 23).replace('.', ',');
for (const lang of ['zh', 'en']) {
  let start = 0;
  const subtitles = scenes.map((scene, i) => {
    const end = start + durations[i];
    const cue = `${i + 1}\n${stamp(start)} --> ${stamp(end)}\n${scene[lang]}\n`;
    start = end;
    return cue;
  }).join('\n');
  await fs.writeFile(path.join(out, `intro.${lang}.srt`), subtitles);
}
const manifest = {
  createdAt: new Date().toISOString(), commit: run('git', ['rev-parse', 'HEAD']).toString().trim(),
  classification: 'open-source-developer-preview-project-introduction', physicalDeviceFootage: false,
  repository: 'https://github.com/eust-w/real2simcapture', license: 'Apache-2.0', release: 'v0.1.0-alpha.1',
  scriptSha256: createHash('sha256').update(await fs.readFile(new URL(import.meta.url))).digest('hex'),
  voice: { provider: 'macOS say', voice, synthetic: true }, music: false,
  sources: ['ios/Real2SimCapture/Sources/ARSceneCaptureScreen.swift', 'backend/app/exporters.py', '.build/browser/workbench-empty.png'],
  videos: ['landscape', 'portrait'].map(format => ({ file: `real2simcapture-intro-${format}.mp4`, probe: probe(path.join(out, `real2simcapture-intro-${format}.mp4`)) })),
  scenes: scenes.map((scene, index) => ({ label: scene.label, zh: scene.zh, en: scene.en, duration: durations[index] })),
};
await fs.writeFile(path.join(out, 'manifest.json'), JSON.stringify(manifest, null, 2));
console.log(JSON.stringify({ output: out, seconds: durations.reduce((a, b) => a + b, 0), physicalDeviceFootage: false }));
