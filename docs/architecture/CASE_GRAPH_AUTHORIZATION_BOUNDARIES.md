# Case-Graph Authorization Boundaries (Phase B security note)

> Status: **analysis + proposal. No authorization code changed yet** (per the
> directive: document boundaries before modifying; approval required for
> security-policy changes). Branch `main`.
> Scope: `case_id`, the evidence graph, investigation sessions, and evidence
> access paths.

---

## 1. Current data relationships

```
Principal (X-ARK-Principal header, dev stand-in)
   │  subject, namespace()
   ▼
CAI Session (session_store, SQLite)        ── principal-scoped ──  ✓
   │  principal_subject column; _session_visible_to() enforced
   │
   ├── run records (per session)           ── reached only via the session ── ✓
   └── evidence_refs (per run)
                    ▲
                    │  references (by id, not by ownership)
                    │
case_id (free-form string)                  ── NOT principal-scoped ──  ✗
   │
   ├── EvidenceGraph (in-memory, per investigation)  keyed by case_id only
   │       └── EvidenceNode / EvidenceEdge / Finding / audit nodes
   │
   └── InvestigationSession (orchestrator.InvestigationStore, in-memory)
           fields: investigation_id, case_id, objective, plan, graph, status …
           **no principal / owner field**
```

### Facts (read from source)

1. **CAI sessions are isolated.** `cai.py:_session_visible_to` (line 750) is an
   owner check; the stored owner is `principal_subject` (default
   `ANONYMOUS.subject`). A cross-principal read is reported as "unknown session"
   so the endpoint is not an existence oracle. Transcripts, evidence refs and
   run history inherit that protection.

2. **Investigation sessions are NOT isolated.** `app/api/v1/endpoints/investigate.py`
   declares no auth dependency and never resolves a principal.
   `orchestrator.InvestigationStore.get(id)` returns *any* session by id, and
   `InvestigationSession` has no owner field. So
   `POST /investigate/{id}/approve`, `/resume`, and `GET /investigate/{id}`
   act on an investigation **without any caller check** — a caller who knows or
   enumerates an id can read the graph, the objective and the plan, and can
   approve/resume someone else's run. This is the "unscoped case graph"
   finding, made concrete.

3. **The graph itself is keyed only by `case_id`.** `node_hash(case_id, payload)`
   and `EvidenceGraph.case_id` carry no principal. Two sessions that pass the
   same `case_id` share a namespace with no enforced link, and nothing prevents
   principal B from constructing a session whose `case_id` equals principal A's.

4. **`case_id` is free-form.** It is supplied by the caller and threaded through
   sessions; there is no case table, no uniqueness constraint, and no
   case→owner record.

5. **Principal resolution is a development stand-in.** `principal_from_request`
   reads the `X-ARK-Principal` header (sanitized, bounded, self-only). Its own
   docstring states it "is deliberately a development stand-in, not an
   authentication boundary." Any authorization built on it is therefore
   *defence-in-depth*, not a production auth boundary — the real boundary is
   the deployment's authenticated session.

6. **Investigation state is in-memory.** `InvestigationStore` is a dict behind a
   lock. Restarting the process loses investigations. CAI sessions persist to
   SQLite.

---

## 2. Authorization boundaries — target model

| Object | Owner | Read rule | Write rule |
|---|---|---|---|
| CAI session | `principal_subject` | owner only | owner only |
| Investigation session | **owner (to add)** | owner only | owner only |
| Evidence graph | **via its investigation (to add)** | owner only | owner only |
| Evidence node | inherits graph owner | owner only | owner only |
| `case_id` | **bound to an owner at creation (to add)** | owner only | owner only |

Principle: **ownership is established at creation and enforced on every read
and write.** A cross-owner request is reported exactly like an unknown id, so
no endpoint becomes an existence oracle (mirroring `_session_visible_to`).

---

## 3. Proposed change (minimal, additive, non-breaking)

1. `InvestigationSession` gains `principal_subject: str = ANONYMOUS.subject`.
   Default keeps every existing construction valid.
2. `orchestrator.start()` records the caller's principal subject on the session.
3. A `_visible_to(session, principal)` helper mirrors `_session_visible_to`.
4. `investigate.py` resolves the principal (`principal_from_request`) and:
   - `GET /investigate/{id}`, `/approve`, `/resume`, `amend` → return **404**
     for a non-owner (same shape as unknown id).
   - `POST /investigate` → binds the creating principal.
5. `orchestrator.list()` (if surfaced) filters by owner.

**Migration implications:** none for storage — investigations are in-memory and
not persisted, so there is no schema/DB migration and no historical row to
backfill. A restart already clears them. (If investigations are later persisted,
the owner column is the only addition and legacy rows default to
`ANONYMOUS.subject`, exactly as CAI legacy rows do.)

**Backward compatibility:** existing single-user / anonymous deployments keep
working (anonymous sees anonymous-created investigations). Multi-principal
deployments gain isolation. No existing investigation is broken because none
persist across restart and the default owner is anonymous.

**What this does NOT do:** it does not add a case table, does not scope the
graph independently of its session, and does not replace the dev principal
header with real auth. Those are larger (and, for auth, deployment-level)
changes that need their own approval.

---

## 4. Residual risk after the proposed change

- A determined caller could still forge `X-ARK-Principal`. That is inherent to
  the dev stand-in and is documented; the production boundary is the real
  session. Making the header an auth boundary is out of scope and needs
  approval.
- `case_id` remains free-form; two principals can still choose the same string.
  The proposal prevents cross-owner *access*, but not string collisions. A
  case registry (unique, owner-bound) is the follow-up.
- In-memory investigations are lost on restart (availability, not
  confidentiality).

---

## 5. Recommendation

Implement §3 (small, testable, no migration) as the next security milestone,
then consider a case registry (owner-bound, unique `case_id`) as a separate,
explicitly-approved step. Both require approval because they change
authorization policy.
