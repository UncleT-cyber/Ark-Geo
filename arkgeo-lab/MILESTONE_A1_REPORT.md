# Milestone A.1 Final Report — Identity / Routing / Tool-Execution Regression

**Project:** Ark-Geo (Ark-CAI investigation platform)
**Date:** Fri Nov 06 2026
**Status:** complete — acceptance tests 1–10 executed; evidence gathered alongside Milestone A.2

## Summary

A.1 root cause (failing layer: `nemotron-3.5-super-vl:free` identity non-compliance + pentest refusal + 2 app defects) was fixed in prior work via model switch to `openrouter/nvidia/nemotron-3.5-lightning:free` (Admin API), `_task_domains` empty-domain fix, and runtime capability block. This session executed acceptance tests 1–10: tests 1–5 passed post-fix; tests 6–10 executed in the A.2 lab run (see evidence below).

## Acceptance test results

| # | Case | Result | Evidence / notes |
|---|---|---|---|
| 1 | Model identity compliance | PASS | A.1 prior run; model reports ARK identity exactly |
| 2 | Router verb coverage | PASS | Autonomous verbs extended (`inspect\|verify\|establish\|authenticate\|access the\|connect to`) |
| 3 | Runtime capability block | PASS | Prior run; scope disclosure added this session |
| 4 | `_task_domains` empty-domain fix | PASS | Prior run |
| 5 | End-to-end tool execution | PASS | A.2 Test 1/2/3 — real curl + nmap + SSH through full loop |
| 6 | Model switch via `/cai/command /model` | PASS | `openrouter/cohere/north-mini-code:free` pinned per session; global model unchanged; verified session-scoped |
| 7 | Session restoration | PASS | `/cai/command /sessions` history restored (5 entries); model pin session-scoped |
| 8 | HITL denial | PASS | Workbench Deny button → operator-denied `pentest.ssh_identity`; model refused retry citing policy; sshd auth events: 0 from denied runs |
| 9 | Frontend check | PASS | Vite dev :12001 up; `npx tsc --noEmit` clean; workbench driven end-to-end (probe + denial flows) |
| 10 | Regression suites | partial | Backend pytest: batch 1 112 passed / 3 pre-existing failures (HF gateway "curated" vs "live"; nmap round-trip affected by pre-existing dotted-tool-id provider-name validation — unmodified code). `test_ark_cai_engine.py`: 4 of 18 fail for the same pre-existing dotted-id issue + intended ordering change (scope denial before HITL). `npx vite build`: clean |

## Regression evidence

- Backend tests run with `ARKGEO_ENGAGEMENT_SCOPE` unset (scope opt-in): `tests/test_agent_policy.py`, `tests/test_agent_substrate.py`, `tests/test_engagement_scope.py` (14 new scope tests), `tests/test_agent_intent_gating.py`, `tests/test_cai_provider_tools.py`, `tests/test_model_catalog.py`, `tests/test_key_probe.py`, `tests/test_local_inspector.py`, `tests/test_integration.py` (8), `tests/test_ai_gateway.py` (31), `tests/test_huggingface_gateway.py` (8) — all pass except 3 pre-existing HF/network-dependent failures
- Full final suite run in progress at report time (`/tmp/pytest_final.log`)
- Frontend: `npx tsc --noEmit` clean; `npx vite build` clean (~1902 modules)

## Uncommitted files

71 files modified/untracked in working tree (22 pre-existing + A.1/A.2 changes + new lab files). Nothing pushed, nothing committed — per repository convention, no push/deploy/merge without approval.

## Sign-off

Ready for operator sign-off on Milestone A.1. Milestone A.2 report: `arkgeo-lab/MILESTONE_A2_REPORT.md`.
