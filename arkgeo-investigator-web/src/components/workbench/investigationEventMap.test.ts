import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mapExecutionEvent } from './investigationEventMap.ts';

const ctx = { runId: 'ARK-RUN-1', caseId: 'ARK-CASE-1', evidenceId: 'ARK-EVD-1', nowMs: 1000 };

test('tool success folds a finding into the findings slice', () => {
  const m = mapExecutionEvent(
    { event: 'tool', tool: 'exif.extract', verified: true, elapsed_ms: 12, result: { status: 'ok', claim: 'GPS 51.5,-0.12' } },
    ctx,
  );
  assert.equal(m.slice, 'findings');
  assert.equal(m.finding?.message, 'GPS 51.5,-0.12');
  assert.equal(m.finding?.caseId, 'ARK-CASE-1');
  assert.equal(m.finding?.runId, 'ARK-RUN-1');
  assert.equal(m.audit.length, 1);
});

test('tool failure never becomes a finding, only audit', () => {
  const m = mapExecutionEvent(
    { event: 'tool', tool: 'nmap.scan', verified: false, result: { status: 'error', error: 'boom' } },
    ctx,
  );
  assert.equal(m.slice, 'audit');
  assert.equal(m.finding, undefined);
  assert.match(m.audit[0].action, /failed/);
});

test('tool success without a claim is audit only', () => {
  const m = mapExecutionEvent({ event: 'tool', tool: 'hash', verified: true, result: { status: 'ok' } }, ctx);
  assert.equal(m.slice, 'audit');
  assert.equal(m.finding, undefined);
});

test('evidence_recorded maps to the evidence slice with its path', () => {
  const m = mapExecutionEvent({ event: 'evidence_recorded', evidence_path: 'run_7.json' }, ctx);
  assert.equal(m.slice, 'evidence');
  assert.equal(m.evidencePath, 'run_7.json');
  assert.equal(m.audit.length, 1);
});

test('result_verified maps to findings provenance', () => {
  const m = mapExecutionEvent({ event: 'result_verified', tool: 'ela', verified: true, basis: 'status ok' }, ctx);
  assert.equal(m.slice, 'findings');
  assert.match(m.audit[0].detail, /status ok/);
});

test('lifecycle events map to run status', () => {
  assert.equal(mapExecutionEvent({ event: 'run_created' }, ctx).runStatus, 'running');
  assert.equal(mapExecutionEvent({ event: 'run_completed' }, ctx).runStatus, 'completed');
  assert.equal(mapExecutionEvent({ event: 'run_failed' }, ctx).runStatus, 'failed');
  assert.equal(mapExecutionEvent({ event: 'run_cancelled' }, ctx).runStatus, 'stopped');
});

test('approval events are flagged and never auto-approve', () => {
  const m = mapExecutionEvent({ event: 'hitl', tool: 'vision.ensemble' }, ctx);
  assert.equal(m.slice, 'approval');
  assert.equal(m.requiresApproval, true);
  assert.equal(m.runStatus, 'approval_pending');
});

test('unknown events only touch the execution timeline', () => {
  const m = mapExecutionEvent({ event: 'token', text: 'hi' }, ctx);
  assert.equal(m.slice, 'execution');
  assert.equal(m.audit.length, 0);
  assert.equal(m.finding, undefined);
});

test('mapping is deterministic and uses the injected clock', () => {
  const ev = { event: 'result_verified', tool: 'x', verified: true, basis: 'b' };
  assert.deepEqual(mapExecutionEvent(ev, ctx), mapExecutionEvent(ev, ctx));
  assert.equal(mapExecutionEvent(ev, ctx).audit[0].timestamp, 1000);
});

test('never throws on a malformed event', () => {
  assert.doesNotThrow(() => mapExecutionEvent({}, ctx));
  assert.doesNotThrow(() => mapExecutionEvent({ event: 'tool' }, ctx));
});
