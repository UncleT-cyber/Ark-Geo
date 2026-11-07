import { test } from 'node:test';
import assert from 'node:assert/strict';
import { deriveExecutionPhase, groupExecutionByObjective } from './executionPresentation.ts';

const run = (lifecycle_status: string, events: any[] = [], objective_outcome: any = 'pending') =>
  ({ lifecycle_status, events, objective_outcome });

test('idle derives PLANNING', () => {
  assert.equal(deriveExecutionPhase(run('idle')), 'PLANNING');
});

test('running before any tool is PLANNING, after a tool is RUNNING', () => {
  assert.equal(deriveExecutionPhase(run('running', [{ event: 'run_created' }])), 'PLANNING');
  assert.equal(deriveExecutionPhase(run('running', [{ event: 'agent_selected' }])), 'PLANNING');
  assert.equal(deriveExecutionPhase(run('running', [{ event: 'tool_call', tool: 'x' }])), 'RUNNING');
});

test('approval / stop / fail map to their phases', () => {
  assert.equal(deriveExecutionPhase(run('approval_pending')), 'AWAITING_APPROVAL');
  assert.equal(deriveExecutionPhase(run('stopped')), 'CANCELLED');
  assert.equal(deriveExecutionPhase(run('failed')), 'FAILED');
});

test('completed with all tools verified is COMPLETED', () => {
  const events = [
    { event: 'tool', tool: 'a', verified: true, result: { status: 'ok' } },
    { event: 'run_completed' },
  ];
  assert.equal(deriveExecutionPhase(run('completed', events, 'succeeded')), 'COMPLETED');
});

test('completed with a failed tool is PARTIAL, never silently COMPLETED', () => {
  const events = [{ event: 'tool', tool: 'a', verified: false, result: { status: 'error' } }];
  assert.equal(deriveExecutionPhase(run('completed', events, 'failed')), 'PARTIAL');
});

test('run_completed with pending outcome is REPORTING', () => {
  assert.equal(deriveExecutionPhase(run('completed', [{ event: 'run_completed' }], 'pending')), 'REPORTING');
});

test('grouping keeps only tools the backend reported', () => {
  const groups = groupExecutionByObjective({
    objective: 'Verify GPS', lifecycle_status: 'running', objective_outcome: 'pending',
    events: [
      { event: 'run_created' },
      { event: 'tool_call', tool: 'exif.extract' },
      { event: 'tool', tool: 'exif.extract', verified: true, elapsed_ms: 12, result: { status: 'ok' } },
    ],
  });
  assert.equal(groups.length, 1);
  assert.equal(groups[0].objective, 'Verify GPS');
  assert.equal(groups[0].stages.length, 1);
  assert.equal(groups[0].stages[0].status, 'completed');
  assert.equal(groups[0].stages[0].verified, true);
  assert.equal(groups[0].durationMs, 12);
});

test('a failed stage is marked failed with its error, not verified', () => {
  const [g] = groupExecutionByObjective({
    objective: null, lifecycle_status: 'completed', objective_outcome: 'failed',
    events: [{ event: 'tool', tool: 'nmap', verified: false, elapsed_ms: 5, result: { status: 'error', error: 'boom' } }],
  });
  assert.equal(g.stages[0].status, 'failed');
  assert.equal(g.stages[0].verified, false);
  assert.equal(g.stages[0].error, 'boom');
  assert.equal(g.objective, 'Untitled objective');
});

test('no tool events yields an objective group with no stages', () => {
  const [g] = groupExecutionByObjective({ objective: 'x', lifecycle_status: 'idle', events: [] });
  assert.deepEqual(g.stages, []);
  assert.equal(g.durationMs, 0);
});
