# ARK unified execution interface — Stop / Steer / Mode control plane

Refactor making the operator control plane **real end-to-end** (backend-owned,
not frontend-only): Stop, Steer, and execution mode (auto | manual), plus the
queue, run-status and event contract the UI depends on. The conversation canvas
is now the primary surface; execution detail moves into one compact, collapsible
inline card.

## Why this was needed

The UI previously *simulated* control. `POST /cai/stop` set an in-memory dict
(`_ACTIVE_RUNS`) and returned `{"status": "stopped"}` while the orchestrator
loop kept running. `POST /cai/steer` appended to a store nobody read. Execution
mode was a React `useState` in `ArkControl.tsx` that the backend never saw. A
stop could therefore be "confirmed" while tools continued to execute — the exact
failure mode an operator control plane must never have.

## What is now true

| Control | Before | Now |
| --- | --- | --- |
| Stop | In-memory flag; loop ignored it | `RunControl.request_stop()` sets a flag; the orchestrator checks it at safe checkpoints, yields `run_cancelled`, and preserves completed tool output |
| Steer | Appended to an unread store | Delivered to the orchestrator at a checkpoint; acknowledged `accepted` / `deferred` / `rejected` via a streamed `steer_ack` event |
| Mode | React-only `useState` | Backend-owned (`SessionState.execution_mode` + `RunControl.mode`), enforced at the dispatch gate; changeable mid-run |
| Queue | Write-only store | Drained after a run completes and delivered as the next objective (`queue_delivered`) |
| Run status | None | `GET /cai/run` reports `running` / `stopping` / `cancelled` / `idle` plus mode, stop state and pending steering |

## Backend

### `app/engine/run_control.py` (new)

A process-local registry of `RunControl` objects — one per active run — that the
HTTP layer and the orchestrator share:

- `register(run_id, session_id, mode)` / `unregister(run_id)` /
  `get` / `get_for_session` / `resolve(session_id, run_id)`.
- `request_stop(stop_type, reason)` — sets `stop_requested`; status becomes
  `stopping`, **never** `cancelled`, until the loop confirms.
- `submit_steer(message, instruction_type)` / `drain_steering()` — pending
  instructions returned to the loop at a checkpoint.
- `steering_snapshot()` — read-only view for `GET /cai/run`.
- `MODES = {"auto", "manual"}`, `MODE_AUTO`, `MODE_MANUAL`.

Honest-state invariant: a stop *request* and a completed *stop* are distinct
states. The API and UI can always tell them apart.

### `app/engine/orchestrator.py`

- `SessionState` gains `execution_mode` (default `auto`).
- `run()` creates a `RunControl` for the run, tears it down on exit, and maps
  cancellation to run status.
- `_run()` checks for a stop at two safe checkpoints: the top of each loop turn,
  and immediately after a tool returns. A tool already executing is never
  interrupted mid-syscall; the stop is honoured the moment it returns.
- `_drain_steering()` delivers queued instructions. A plain instruction is
  injected as an operator turn (`accepted`); an instruction that would widen
  authority is `deferred` for explicit confirmation. Scope is revalidated at
  dispatch regardless of mode, so steering cannot escalate privilege.
- The approval gate consults `execution_mode`: `manual` requires operator
  confirmation at a target-directed dispatch; `auto` does not. Neither bypasses
  the engagement scope or the policy guard.
- Emits `execution_mode` on run start so the UI reflects the mode the backend
  actually applied rather than the one it hoped for.

### `app/api/v1/endpoints/cai.py`

Rewired to the registry:

- `POST /cai/stop` — `stop` / `cancel_pending` / `cancel_tool` / `stop_all`;
  returns `stop_requested` (never a fabricated `stopped`).
- `POST /cai/steer` — 400-equivalent honest rejection when there is no active
  run; otherwise submits and returns the steering id.
- `POST /cai/mode` — validates against `run_control.MODES`, persists to the
  session, and applies live to an active run.
- `GET /cai/run` — the live control state.
- `POST /cai/queue` and `GET /cai/queue/{session_id}` — durable queue.
- `execution_mode` accepted on `/stream`, `/terminal/stream`, and
  `/workspace/{workspace}/run`; applied to the session before the run starts.

### `app/services/session_store.py`

Adds `RUN_CANCELLED = "cancelled"` so a stopped run is recorded as cancelled,
distinct from failed or interrupted.

## Frontend

### Unified conversation canvas (`ArkControl.tsx`)

- **Removed the permanent upper execution region** (investigation header,
  execution timeline, tool details, findings, evidence panel — ~190 lines of
  always-visible chrome). The conversation is now the primary surface.
- **`ExecutionActivity`** (`ExecutionPanels.tsx`) — one compact, collapsible
  inline card: status dot, current tool + elapsed, step/tool counts, mode badge,
  inline Stop, and an expandable timeline. Collapsed by default; expanded by
  default in Console view.
- **`InvestigationReport`** — the structured final report, appended when a run
  reaches a terminal state. Built entirely from the run's own events, so it
  cannot claim a tool ran when the backend did not report it.
- **`executionPresentation.ts`** — shared labelling/summary logic so the card,
  the report and the console all read the same event list.
- **Console** is the raw monospace event log for the same run data. Per the
  interface directive it is **not** a header control: it renders as the console
  surface when invoked, and no Chat/Console switch is mounted in the ARK header
  or composer.
- **Composer redesign**: while a run is active, Send *queues* the message
  (runs after the current objective) and the Send button becomes the single Stop
  control; the mode toggle now persists to the backend and rolls back on failure.

## Verification

- **Backend**: `754 passed` (`pytest tests/ -q`), including 16 new tests in
  `tests/test_run_control.py` covering registry state honesty, stop at a safe
  checkpoint, steering delivery + non-escalation, manual-mode approval, auto-mode
  pass-through, manual mode *not* bypassing scope, and the HTTP surface.
- **Frontend**: `npx tsc --noEmit` clean; `npx vite build` clean.
- **Browser**: the ARK header carries no Chat/Console switch; the mode toggle drives
  `POST /cai/mode` and flips Automatic ↔ Manual; a run failing on an upstream
  rate limit degrades gracefully without fabricating success.

## Known limitations

- `RunControl` and `_QUEUE_STORE` are process-local. A restart drops in-flight
  control state. Durable task/run persistence remains future work (tracked in
  `ARK_UNIFIED_EXECUTION_AUDIT.md`).
- `cancel_tool` sets the stop flag; it cannot interrupt a tool mid-syscall by
  design. The tool's completed output is preserved and the run halts at the next
  checkpoint.
