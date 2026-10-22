import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { fixture, toolEvents, textEvents, reply } from './perspective-fixture.mjs';
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}) });
try {
  const page = await browser.newPage();
  const errors = [], replies = [];
  page.on('pageerror', error => errors.push(error.message));
  const cases = [
    { args: { ...fixture, view: { ...fixture.view, plugin: 'Not installed' } }, expected: /Unavailable plugin/ },
    { args: { ...fixture, view: { ...fixture.view, columns: ['Missing'] } }, expected: /Unknown field/ },
    { args: { ...fixture, view: { ...fixture.view, filter: [['Missing', '==', 'x']] } }, expected: /Unknown field/ },
    { args: { ...fixture, table: { ...fixture.table, rows: [{ Day: '2026-09-01', Revenue: 'bad' }] } }, expected: /valid float/ },
    { args: { ...fixture, layout: { type: 'tab-layout', tabs: ['old'] }, panels: [] }, expected: /Unrecognized keys?/ },
    { args: { ...fixture, view: { ...fixture.view, plugin: 'Number Card', columns: ['Revenue', 'Units'] } }, expected: /exactly one numeric column/ },
    { args: { ...fixture, view: { ...fixture.view, plugin: 'Number Card', group_by: [], aggregates: {} } }, expected: /single value/ },
    { args: { ...fixture, view: { ...fixture.view, plugin: 'Number Card', aggregates: {} } }, expected: /explicit aggregate/ },
    { args: { ...fixture, view: { ...fixture.view, plugin: 'Number Card', plugin_config: { locale: 'invalid_locale' } } }, expected: /locale|language tag/i },
  ];
  let index = 0, continuation = false;
  await page.route('**/api/agent', async route => {
    const input = route.request().postDataJSON();
    if (!continuation) {
      continuation = true;
      await reply(route, input, toolEvents(`bad-${index}`, 'render_perspective', cases[index].args));
    } else {
      const outcome = JSON.parse(input.messages.find(message => message.role === 'tool' && message.toolCallId === `bad-${index}`).content);
      assert.equal(outcome.status, 'error'); assert.match(outcome.error, cases[index].expected);
      replies.push(outcome);
      await reply(route, input, textEvents(`final-${index}`, `Error ${index} received.`));
      continuation = false;
    }
  });
  await page.goto(process.env.ASSISTANT_UI_URL ?? 'http://localhost:3001', { waitUntil: 'networkidle' });
  for (index = 0; index < cases.length; index++) {
    if (index) await page.getByRole('button', { name: 'New Thread', exact: true }).click();
    const input = page.getByRole('textbox', { name: 'Message input', exact: true });
    await input.fill(`Invalid view case ${index}`); await input.press('Enter');
    await page.getByText(`Error ${index} received.`, { exact: true }).waitFor({ timeout: 45000 });
    assert.equal(await page.getByTestId('perspective-card').getByRole('status').count(), 0);
    await page.getByRole('alert').filter({ hasText: 'Không thể hiển thị Perspective' }).waitFor();
  }
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ status: 'passed', cases: replies.length, rejectsDashboard: true, errorSentToAgent: true, noStuckLoader: true }));
} finally { await browser.close(); }
