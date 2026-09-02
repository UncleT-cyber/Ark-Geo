"""Live Phase E verification — real qwen2.5-coder:3b drives planning + propose_next.

A conflicting location node is injected pre-approve so the mid-run correlator
raises an OPEN_CONTRADICTION gap and the model must propose a delta tool order.
Geocoder is stubbed (external service); everything else is real.
"""
import asyncio
import json
import sys

from app.agent import schemas as S
from app.agent import evidence_graph as eg
from app.agent.orchestrator import orchestrator
from app.agent.tool_registry import reverse_geocode as _real_reverse_geocode
from app.agent.tool_registry import registry
from tests.test_phase_e_adaptive import (
    FAKE_ADDRESS, _inject_location_node, _make_image_with_gps, _make_objective,
)


def _stub_geocoder():
    registry._tools["reverse_geocode"].handler = (
        lambda lat, lon: type("Addr", (), {"model_dump": lambda s: FAKE_ADDRESS})()
    )


async def main():
    _stub_geocoder()
    session = await orchestrator.start(
        _make_objective(), image_bytes=_make_image_with_gps())
    initial_rev = session.plan.revision_id
    # Conflict: Tokyo vs Lagos claims, both strong → OPEN_CONTRADICTION gap.
    _inject_location_node(session.graph, session.case_id, 35.6762, 139.6503)
    _inject_location_node(session.graph, session.case_id, 6.5244, 3.3792)

    done = await orchestrator.approve(session.investigation_id)

    print("=" * 70)
    print("STATUS          :", done.status)
    print("PAUSE_REASON    :", done.pause_reason)
    print("ITERATIONS      :", done.iterations)
    print("BUDGET_USAGE    :", done.budget_usage["steps"],
          "/", done.budget_usage["budget"]["max_steps"])
    print("REVISION CHAIN  :", initial_rev, "->", done.plan.revision_id,
          f"(parent={done.plan.parent_revision_id}, reason={done.plan.delta_reason!r})")
    print("PLAN STEPS      :")
    for s in done.plan.steps:
        print("   ", s.step_id, s.tool_id)
    print("-" * 70)
    print("GAPS:")
    for g in done.gaps:
        print(f"   [{g.severity.value}] {g.gap_type.value} {g.gap_id} acted={g.gap_id in done.acted_gap_ids} :: {g.rationale[:80]}")
    print("-" * 70)
    print("CONTRADICTION EDGES:", sum(
        1 for e in done.graph.edges
        if e.relation == S.EdgeRelation.CONTRADICTS))
    print("CONTRADICTION GAP  :", any(
        g.gap_type == S.GapType.OPEN_CONTRADICTION for g in done.gaps))
    acted_contradiction = any(
        g.gap_id in done.acted_gap_ids
        and g.gap_type == S.GapType.OPEN_CONTRADICTION for g in done.gaps)
    print("CONTRADICTION ACTED:", acted_contradiction)
    print("LOCATION NODES     :", [
        (n.node_id[-4:], round(n.value.get("lat", 0), 4))
        for n in done.graph.nodes.values() if n.claim_type == S.ClaimType.LOCATION])
    print("=" * 70)
    assert done.status == "done", "exit gate failed to terminate"
    assert done.iterations >= 2, "no adaptive re-plan happened"
    assert done.plan.revision_id != initial_rev, "plan did not change"
    assert acted_contradiction, "model never addressed the contradiction gap"
    print("LIVE ADAPTIVE LOOP: PASS")


if __name__ == "__main__":
    asyncio.run(main())
