"""Registry collision introspection (Phase B.3).

Two distinct tool ids can normalize to the same alias (e.g. ``web.fetch`` vs
``webfetch``). The first wins the normalized lookup; the clash must be
recorded and auditable rather than silently shadowing a capability. Both ids
remain independently addressable by exact id.
"""
from app.agent.unified_registry import unified_registry


def test_collisions_are_recorded_and_known():
    unified_registry.populate()
    collisions = unified_registry.collisions()
    aliases = {c["alias"] for c in collisions}
    # The two known clashes from the audit. If a future change resolves them,
    # this assertion should be updated deliberately — not silently.
    assert {"webfetch", "siemquery"} <= aliases, f"unexpected collisions: {collisions}"
    for c in collisions:
        assert c["winner"] and c["shadowed"]
        assert c["winner"] != c["shadowed"]
        # Both ids are still separately addressable.
        assert unified_registry.get(c["winner"]) is not None
        assert unified_registry.get(c["shadowed"]) is not None


def test_no_image_capability_is_shadowed():
    """Image Intelligence ids must never collide (they are the primary domain)."""
    unified_registry.populate()
    for c in unified_registry.collisions():
        assert not c["winner"].startswith("imint.") or not c["shadowed"].startswith("imint."), c
        assert not (c["winner"].startswith("image") and c["shadowed"].startswith("image")), c
