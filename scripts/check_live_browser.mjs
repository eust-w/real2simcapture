// Real HTTP/browser regression test. Geometry below is a labeled test fixture, not scan footage.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.resolve('frontend/node_modules/playwright'));
const api = process.env.REAL2SIM_TEST_API || 'http://127.0.0.1:8000';
const site = process.env.REAL2SIM_TEST_WEB || 'http://127.0.0.1:5175';
const output = path.resolve('.build/browser');
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : { channel: 'chrome' }), headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(90000);
page.setDefaultNavigationTimeout(90000);
const errors = [];
page.on('pageerror', e => { errors.push(e.message); console.error('PAGE ERROR:', e.message); });
async function json(route, data) {
  const response = await fetch(api + route, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
  assert(response.ok, `${route}: ${response.status}`);
  return response.json();
}
try {
  await page.goto(site, { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'Live Mesh', exact: true }).waitFor();
  await page.screenshot({ path: path.join(output, 'workbench-empty.png'), fullPage: true });
  const project = await json('/api/projects', { name: 'Regression fixture (not device capture)' });
  const session = await json('/api/live-sessions', { project_id: project.id, name: 'Geometry transport test', category: 'test-fixture' });
  const mesh = 'v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 2 3\nf 1 4 2\nf 1 3 4\nf 2 4 3\n';
  async function upload(content) {
    const form = new FormData();
    form.append('mesh', new Blob([content], { type: 'text/plain' }), 'fixture.obj');
    const response = await fetch(`${api}/api/live-sessions/${session.id}/mesh`, { method: 'POST', body: form });
    assert(response.ok, await response.text());
  }
  await upload(mesh);
  await page.reload();
  await page.getByText('Mesh v1', { exact: true }).waitFor();
  await page.locator('canvas').waitFor();
  await page.waitForTimeout(2500);
  const canvas = page.locator('canvas');
  async function checkFraming(file) {
    const png = await canvas.screenshot({ path: path.join(output, file) });
    const bounds = await page.evaluate(async base64 => {
      const img = new Image();
      img.src = 'data:image/png;base64,' + base64;
      await img.decode();
      const probe = document.createElement('canvas');
      probe.width = img.width; probe.height = img.height;
      const context = probe.getContext('2d');
      context.drawImage(img, 0, 0);
      const { data } = context.getImageData(0, 0, img.width, img.height);
      let count = 0, minX = img.width, maxX = 0, minY = img.height, maxY = 0;
      for (let y = 0; y < img.height; y++) for (let x = 0; x < img.width; x++) {
        const i = (y * img.width + x) * 4;
        if (data[i] > 60 && data[i] < 225 && Math.abs(data[i] - data[i + 1]) < 2 && Math.abs(data[i] - data[i + 2]) < 2) {
          count++; minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y);
        }
      }
      return { count, minX, maxX, minY, maxY, width: img.width, height: img.height };
    }, png.toString('base64'));
    assert(bounds.count > bounds.width * bounds.height * 0.01, `Blank geometry: ${JSON.stringify(bounds)}`);
    assert(bounds.minX > 3 && bounds.maxX < bounds.width - 4 && bounds.minY > 3 && bounds.maxY < bounds.height - 4, `Clipped geometry: ${JSON.stringify(bounds)}`);
  }
  await checkFraming('mesh-v1.png');
  await upload(mesh.replace('v 0 0 1', 'v 0 0 2'));
  await page.getByText('Mesh v2', { exact: true }).waitFor();
  await page.waitForTimeout(1500);
  await canvas.screenshot({ path: path.join(output, 'mesh-v2.png') });
  const box = await canvas.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 80, box.y + box.height / 2 + 45, { steps: 10 });
  await page.mouse.up();
  await page.waitForTimeout(600);
  await canvas.screenshot({ path: path.join(output, 'mesh-orbit.png') });
  assert.notDeepEqual(await fs.readFile(path.join(output, 'mesh-v1.png')), await fs.readFile(path.join(output, 'mesh-v2.png')));
  assert.notDeepEqual(await fs.readFile(path.join(output, 'mesh-v2.png')), await fs.readFile(path.join(output, 'mesh-orbit.png')));
  await page.screenshot({ path: path.join(output, 'desktop-fixture.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(800);
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Mobile horizontal overflow');
  await page.locator('canvas').scrollIntoViewIfNeeded();
  await checkFraming('mesh-mobile.png');
  await page.screenshot({ path: path.join(output, 'mobile-fixture.png') });
  assert.equal(errors.length, 0, errors.join('\n'));
  console.log(JSON.stringify({ passed: true, fixture: true, realDeviceCapture: false, screenshots: output, checks: ['HTTP upload', 'mesh version refresh', 'canvas pixel changes', 'desktop/mobile geometry framing', 'orbit interaction', 'mobile overflow', 'no page errors'] }, null, 2));
} catch (error) {
  console.error('Page body:', await page.locator('body').innerText().catch(() => 'unavailable'));
  await page.screenshot({ path: path.join(output, 'failure.png'), timeout: 10000 }).catch(() => {});
  throw error;
} finally {
  await browser.close();
}
