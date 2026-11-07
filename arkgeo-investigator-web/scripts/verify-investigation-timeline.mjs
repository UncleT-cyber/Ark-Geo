#!/usr/bin/env node
/**
 * Deterministic fixture checks for the investigation-canvas timeline.
 *
 * The repo has no frontend test runner (package.json: dev/build/preview/lint),
 * so this script provides repeatable, network-free verification of the pure
 * derivation logic in `executionPresentation.ts`:
 *   - buildActivityTimeline (State B/C rows from real events)
 *   - summarizeRun (State C completion summary, honest outcomes)
 *   - initialExecutionState (the shared slice seed)
 *
 * Run: npm run test:timeline   (or: node scripts/verify-investigation-timeline.mjs)
 */
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const root = join(import.meta.dirname, '..');
const outfile = join(tmpdir(), `ark-ep-${process.pid}.cjs`);

const bundle = spawnSync(
  join(root, 'node_modules', '.bin', 'esbuild'),
  [
    join(root, 'src/components/workbench/executionPresentation.ts'),
    '--bundle', '--format=cjs', `--outfile=${outfile}`, '--log-level=error',
  ],
  { stdio: 'inherit' },
);
if (bundle.status !== 0) process.exit(bundle.status ?? 1);

const ep = require(outfile);
const assert = require('node:assert');
const base = ep.initialExecutionState();
let rows;

// 1. Empty state: idle investigation -> no rows.
assert.strictEqual(ep.buildActivityTimeline(base, []).length, 0, 'idle -> no rows');

// 2. Running with no events yet -> one honest in-progress row (never fake steps).
rows = ep.buildActivityTimeline({ ...base, lifecycle_status: 'running' }, []);
assert.strictEqual(rows.length, 1);
assert.strictEqual(rows[0].status, 'running');
assert.strictEqual(rows[0].label, 'Run in progress');

// 3. Tool fold: tool_started opens the row, its `tool` result closes it -> ONE row.
rows = ep.buildActivityTimeline({
  ...base,
  lifecycle_status: 'running',
  events: [
    { event: 'run_created', run_id: 'r1', timestamp: '2026-11-07T10:00:00Z' },
    { event: 'scope_checked', allowed: true, reason: 'in scope', timestamp: '2026-11-07T10:00:01Z' },
    { event: 'tool_started', tool: 'net.dns_lookup', execution_id: 'e1', timestamp: '2026-11-07T10:00:02Z' },
    { event: 'tool', tool: 'net.dns_lookup', execution_id: 'e1', elapsed_ms: 42, verified: true, result: { status: 'ok' }, timestamp: '2026-11-07T10:00:03Z' },
  ],
  current_tool: null,
}, []);
assert.strictEqual(rows.length, 3, 'tool_started+tool fold into one row');
assert.strictEqual(rows[0].label, 'Run created');
assert.strictEqual(rows[1].status, 'completed');
assert.strictEqual(rows[2].label, 'DNS Lookup');
assert.strictEqual(rows[2].status, 'completed');

// 4. Failed tool: result.status error -> failed row carrying the error detail.
rows = ep.buildActivityTimeline({
  ...base,
  events: [{ event: 'tool', tool: 'net.nmap_scan', execution_id: 'e2', result: { status: 'error', error: 'timeout' }, verified: false }],
  current_tool: null,
  lifecycle_status: 'failed',
}, []);
assert.strictEqual(rows[0].status, 'failed');
assert.strictEqual(rows[0].error, 'timeout');

// 5. Live tool with no closing event -> exactly one running row (no duplicates).
rows = ep.buildActivityTimeline({
  ...base,
  events: [{ event: 'tool_started', tool: 'recon.web_search', execution_id: 'e3' }],
  current_tool: { id: 'recon.web_search', name: 'Web Search', status: 'running' },
  lifecycle_status: 'running',
}, []);
assert.strictEqual(rows.filter(r => r.status === 'running').length, 1, 'no duplicate running rows');

// 6. Queue: genuinely pending objectives appear; delivered ones never do.
rows = ep.buildActivityTimeline({ ...base, events: [], current_tool: null, lifecycle_status: 'idle' }, [
  { id: 'q1', session_id: 's', conversation_id: 'c', prompt: 'scan the host', status: 'pending', created_at: '2026-11-07T10:01:00Z' },
  { id: 'q2', session_id: 's', conversation_id: 'c', prompt: 'done', status: 'delivered', created_at: '2026-11-07T10:02:00Z' },
]);
assert.strictEqual(rows.length, 1);
assert.strictEqual(rows[0].status, 'pending');

// 7. Approval and cancellation rows; status vocabulary.
rows = ep.buildActivityTimeline({
  ...base,
  events: [{ event: 'hitl', tool: 'net.nmap_scan' }, { event: 'run_cancelled', reason: 'operator stop' }],
  current_tool: null,
  lifecycle_status: 'stopped',
}, []);
assert.strictEqual(rows[0].status, 'approval');
assert.strictEqual(rows[1].status, 'cancelled');
assert.strictEqual(ep.timelineStatusLabel('approval'), 'Awaiting approval');

// 8. Completion summary: paired failure fields (real app shape).
let s = ep.summarizeRun({ ...base, lifecycle_status: 'failed', objective_outcome: 'failed', events: [{ event: 'run_failed', reason: 'provider outage' }] });
assert.strictEqual(s.outcome, 'failed');
assert.strictEqual(s.failureReason, 'provider outage');

// 9. Completion summary: lifecycle-only failure must not read as 'pending'.
s = ep.summarizeRun({ ...base, lifecycle_status: 'failed', events: [] });
assert.strictEqual(s.outcome, 'failed', 'lifecycle failed -> failed');

// 10. Scope denial -> failed row with the honest label.
rows = ep.buildActivityTimeline({
  ...base,
  events: [{ event: 'scope_checked', allowed: false, reason: 'out of scope' }],
  current_tool: null,
  lifecycle_status: 'failed',
}, []);
assert.strictEqual(rows[0].status, 'failed');
assert.strictEqual(rows[0].label, 'Scope denied');

console.log('ALL 10 FIXTURE CHECKS PASSED');
