// node --test opencode/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { dedupParts } from './dedup-core.js';
import * as plugin from './genie-dedup.js';
import genieHarness from './genie-harness.js';

const tool = (tool, input, output, status = 'completed') => ({ type: 'tool', tool, callID: `${tool}${JSON.stringify(input)}${Math.random()}`, state: status === 'error' ? { status, input, error: 'boom' } : { status, input, output } });
const msg = (role, ...parts) => ({ info: { role }, parts });
const big = (c) => c.repeat(5000);

test('module exposes one { id, server } plugin (opencode 1.19 rejects { id, setup })', () => {
  assert.deepEqual(Object.keys(plugin), ['default']);
  assert.equal(plugin.default.id, 'genie-dedup');
  assert.equal(typeof plugin.default.server, 'function');
  assert.equal(plugin.default.setup, undefined);
});

test('a repeated call keeps only its newest output; key order in args does not matter', () => {
  const m = [
    msg('user', { type: 'text', text: 'fix it' }),
    msg('assistant', { type: 'text', text: 'reading' }, tool('read', { filePath: 'a.ts', limit: 9 }, big('1'))),
    msg('assistant', tool('read', { filePath: 'b.ts' }, big('2'))),
    msg('assistant', tool('read', { limit: 9, filePath: 'a.ts' }, big('3'))),
  ];
  const r = dedupParts(m);
  assert.equal(r.deduped, 5000);
  assert.match(m[1].parts[1].state.output, /^\[genie-dedup: 5000 chars dropped; the same read call/);
  assert.equal(m[1].parts[0].text, 'reading');
  assert.equal(m[2].parts[0].state.output, big('2'));
  assert.equal(m[3].parts[0].state.output, big('3'));
});

test('idempotent, and small or different-argument outputs are left alone', () => {
  const m = [
    msg('assistant', tool('bash', { command: 'ls' }, 'a\nb')),
    msg('assistant', tool('bash', { command: 'ls' }, 'a\nb')),
    msg('assistant', tool('bash', { command: 'ls -la' }, big('x'))),
  ];
  assert.deepEqual(dedupParts(m), { deduped: 0, purged: 0 });
  const twice = [msg('assistant', tool('grep', { pattern: 'x' }, big('g'))), msg('assistant', tool('grep', { pattern: 'x' }, big('h')))];
  dedupParts(twice);
  const snapshot = JSON.stringify(twice);
  assert.deepEqual(dedupParts(twice), { deduped: 0, purged: 0 });
  assert.equal(JSON.stringify(twice), snapshot);
});

test('a failed call loses its big input only after errorTurns user turns, error kept', () => {
  const failed = tool('write', { filePath: 'x.ts', content: big('c') }, null, 'error');
  const m = [msg('assistant', failed), msg('user', { type: 'text', text: '1' }), msg('user', { type: 'text', text: '2' }), msg('user', { type: 'text', text: '3' })];
  assert.equal(dedupParts(m).purged, 0);
  m.push(msg('user', { type: 'text', text: '4' }));
  assert.equal(dedupParts(m).purged, 5000);
  const s = m[0].parts[0].state;
  assert.equal(s.input.filePath, 'x.ts');
  assert.match(s.input.content, /^\[genie-dedup: 5000 chars of a failed call/);
  assert.equal(s.error, 'boom');
  assert.equal(failed.state.input.content.length, 5000); // original part not mutated
});

test('messages.transform hook fail-opens on junk and can be switched off', async () => {
  const hooks = await plugin.default.server({});
  const transform = (messages) => hooks['experimental.chat.messages.transform']({}, { messages });
  await transform([null, { parts: [null] }]);
  const m = [msg('assistant', tool('read', { f: 1 }, big('a'))), msg('assistant', tool('read', { f: 1 }, big('b')))];
  process.env.GENIE_DEDUP_ENABLED = '0';
  try {
    await transform(m);
    assert.equal(m[0].parts[0].state.output, big('a'));
  } finally {
    delete process.env.GENIE_DEDUP_ENABLED;
  }
  await transform(m);
  assert.match(m[0].parts[0].state.output, /^\[genie-dedup/);
});

test('Genie Harness server() returns the 1.19 hooks', async () => {
  assert.equal(genieHarness.id, 'genie-harness');
  assert.equal(genieHarness.setup, undefined);
  const hooks = await genieHarness.server({ directory: process.cwd() });
  assert.deepEqual(Object.keys(hooks).sort(), ['chat.message', 'experimental.chat.system.transform', 'tool.execute.before']);
  const out = { system: [] };
  await hooks['experimental.chat.system.transform']({ sessionID: 'none' }, out);
  assert.deepEqual(out.system, []);
  await hooks['tool.execute.before']({ tool: 'read' }, { args: {} });
});
