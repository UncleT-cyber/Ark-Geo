"""ARK AI Orchestration substrate — Phase A.

This package defines the contracts the AI orchestrator (Phase B+) will consume:

  * :mod:`schemas`        — ToolSpec, EvidenceGraph, Policy, Objective, Plan
  * :mod:`tool_registry`  — registered wrappers over the existing deterministic
                            tools (zero behavior change)
  * :mod:`evidence_graph` — pure, audited graph operations

Phase A contains **no AI**. It is pure enabling scaffolding: every existing
deterministic capability gains a registry entry and an evidence-graph write
path, but the :class:`BrainPipeline` and ``/analyze`` endpoint are untouched.

See ``docs/ARK_AI_ORCHESTRATION_SPEC.md`` for the full design.
"""
