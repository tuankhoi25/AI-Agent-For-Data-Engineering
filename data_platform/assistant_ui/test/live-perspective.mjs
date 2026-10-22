// Opt-in: configured LUNA model, simulator-generated Bakery data and real MCP queries.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}) });
const events = [], requests = [], errors = [];
let page;
try {
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (request.url().endsWith('/api/agent')) requests.push(request.postDataJSON()); });
  page.on('response', async response => {
    if (!response.url().endsWith('/api/agent')) return;
    try {
      for (const line of (await response.text()).split('\n')) if (line.startsWith('data: ')) events.push(JSON.parse(line.slice(6)));
      console.log('Run completed. Tools:', events.filter(event => event.type === 'TOOL_CALL_START').map(event => event.toolCallName).join(', '));
    } catch {}
  });
  await page.goto(process.env.ASSISTANT_UI_URL ?? 'http://localhost:3000', { waitUntil: 'networkidle' });
  assert.equal(await page.locator('main').getAttribute('data-perspective-build'), 'single-view-5.5.1');
  const input = page.getByRole('textbox', { name: 'Message input', exact: true });
  await input.fill(process.env.PERSPECTIVE_TEST_QUESTION ?? 'Show one interactive chart of completed receipt revenue by day for September 2026, Asia/Ho_Chi_Minh. Use verified data and explain the grain, units and missing days.');
  await input.press('Enter');
  await page.getByRole('button', { name: 'Reset view', exact: true }).last().waitFor({ timeout: 240000 });
  await page.waitForFunction(() => Array.from(document.querySelectorAll('[data-testid="perspective-card"] button')).some(button => button.textContent === 'Reset view' && !button.disabled), undefined, { timeout: 120000 });
  const deadline = Date.now() + 120000;
  let idleSince;
  while (true) {
    assert(Date.now() < deadline, 'Agent did not finish');
    assert(!events.some(event => event.type === 'RUN_ERROR'), 'RUN_ERROR received');
    if (requests.length >= 2 && events.filter(event => event.type === 'RUN_FINISHED').length === requests.length) {
      idleSince ??= Date.now(); if (Date.now() - idleSince > 800) break;
    } else idleSince = undefined;
    await page.waitForTimeout(100);
  }
  const tools = events.filter(event => event.type === 'TOOL_CALL_START').map(event => event.toolCallName);
  assert(tools.includes('render_perspective'));
  assert(tools.includes('run_cube_query') || tools.includes('execute_sql'));
  assert(!tools.some(name => /echarts|render_dashboard/.test(name)));
  const renderIds = new Set(events.filter(event => event.type === 'TOOL_CALL_START' && event.toolCallName === 'render_perspective').map(event => event.toolCallId));
  const renderErrors = requests.flatMap(request => request.messages).filter(message => message.role === 'tool' && renderIds.has(message.toolCallId)).map(message => { try { return JSON.parse(message.content); } catch { return null; } }).filter(result => result?.status === 'error');
  assert.deepEqual(renderErrors, [], 'Report should render without an invalid first attempt');
  const outcome = requests.flatMap(request => request.messages).filter(message => message.role === 'tool').map(message => { try { return JSON.parse(message.content); } catch { return null; } }).find(result => result?.status === 'ready' && result.filter_scope === 'supplied_table');
  assert(outcome, 'Missing successful single-view result');
  const viewer = page.locator('perspective-viewer').last();
  const config = await viewer.evaluate(node => node.save());
  assert(config.plugin);
  assert.equal(await page.locator('perspective-viewer').count(), 1);
  assert.equal(await page.getByTestId('turn-tool-trace').count(), 1);
  assert.deepEqual(errors, []);
  await page.getByRole('button', { name: 'Expand view', exact: true }).last().click();
  await page.waitForFunction(() => !!document.fullscreenElement);
  await viewer.evaluate(node => node.flush());
  await page.screenshot({ path: '/tmp/bakery-perspective-live.png' });
  const reportSpecs = requests.flatMap(request => request.messages).flatMap(message => message.toolCalls ?? []).filter(call => call.function?.name === 'render_perspective').map(call => { try { return JSON.parse(call.function.arguments); } catch { return null; } }).filter(Boolean);
  await fs.writeFile('/tmp/bakery-perspective-live-specs.json', JSON.stringify(reportSpecs, null, 2));
  const summary = { status: 'passed', tools, runs: requests.length, view: { plugin: config.plugin, group_by: config.group_by, columns: config.columns }, filterScope: outcome.filter_scope, pageErrors: errors };
  await fs.writeFile('/tmp/bakery-perspective-live.json', JSON.stringify(summary, null, 2));
  console.log(JSON.stringify(summary, null, 2));
} catch (error) {
  await page?.screenshot({ path: '/tmp/bakery-perspective-live-failure.png' }).catch(() => {});
  console.error('Tools before failure:', events.filter(event => event.type === 'TOOL_CALL_START').map(event => event.toolCallName));
  console.error('Errors:', events.filter(event => event.type === 'RUN_ERROR'));
  throw error;
} finally { await browser.close(); }
