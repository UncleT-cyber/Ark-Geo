"""Dynamic import + auto-registration of 100% of native CAI tools and sub-agent roles.

This module is the single synchronisation point between THE ARK and the
embedded CAI codebase:

* ``import_all_cai_tools`` walks every module under ``cai.tools`` and imports
  it. Each CAI tool calls ``TOOL_REGISTRY.register(...)`` on import, so the
  central CAI ``ToolRegistry`` ends up holding *every* native tool
  (recon, exploitation, privilege escalation, web, SIEM, OT/ROS, C2, ...).
* ``list_cai_tools`` returns CAI-native tools as OpenAI-style function schemas
  (generated with CAI's own ``function_schema``), ready for the orchestrator.
* ``discover_cai_roles`` enumerates every CAI sub-agent role via CAI's
  ``discover_agent_factories`` and returns id / name / description / category.

The results are merged with THE ARK forensic suite (see ``tool_adapter``) by
``app.engine.cai.registry.get_unified_registry``.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

logger = logging.getLogger("ark.cai.tools_importer")

_CAI_TOOLS_IMPORTED = False
_CAI_ROLES_DISCOVERED: list[dict] | None = None


def _ensure_cai_path() -> None:
    """Make sure the embedded CAI package is importable."""
    import os

    # CAI's config layer refuses to initialise without an API key; provide a
    # harmless dummy so tool/role discovery can run (we never call OpenAI — the
    # orchestrator uses Ollama via litellm). CAI_LICENSE_OFF bypasses the gate.
    os.environ.setdefault("OPENAI_API_KEY", "sk-noauth-ark-cai-discovery")
    os.environ.setdefault("CAI_LICENSE_OFF", "true")
    import app.engine.cai as cai_pkg  # noqa: F401  (side-effect: sys.path injection)


def import_all_cai_tools() -> int:
    """Import every ``cai.tools`` submodule to trigger auto-registration.

    CAI stores its tools in *namespace* sub-packages (``reconnaissance``,
    ``web``, ``exploitation``, ...) that intentionally omit ``__init__.py``, so
    ``pkgutil.walk_packages`` will not descend into them. We therefore walk the
    filesystem directly and import every ``.py`` module we find.

    Returns the number of modules imported.
    """
    global _CAI_TOOLS_IMPORTED
    _ensure_cai_path()
    import cai.tools  # noqa: F401
    import os

    tools_root = os.path.dirname(cai.tools.__file__)
    imported = 0
    for dirpath, _dirs, files in os.walk(tools_root):
        if "__pycache__" in dirpath:
            continue
        for fname in files:
            if not fname.endswith(".py") or fname == "__init__.py":
                continue
            rel = os.path.relpath(os.path.join(dirpath, fname), tools_root)
            mod = "cai.tools." + rel[: -len(".py")].replace(os.sep, ".")
            try:
                importlib.import_module(mod)
                imported += 1
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Skipping CAI tool module %s: %s", mod, exc)
    _CAI_TOOLS_IMPORTED = True
    return imported


def list_cai_tools() -> list[dict]:
    """Return all registered CAI-native tools as orchestrator-ready schemas."""
    _ensure_cai_path()
    from cai.tool_registry import TOOL_REGISTRY, TOOL_REQUIRES_KEY
    from cai.sdk.agents.function_schema import function_schema

    if not _CAI_TOOLS_IMPORTED:
        import_all_cai_tools()

    out: list[dict] = []
    for tool in TOOL_REGISTRY.all():
        tname = getattr(tool, "name", str(tool))
        desc = getattr(tool, "description", "") or ""
        # Build the OpenAI-style schema via CAI's own function_schema.
        parameters: dict[str, Any] = {"type": "object", "properties": {}}
        func = getattr(tool, "func", None)
        if func is not None:
            try:
                fs = function_schema(func)
                parameters = fs.params_json_schema
            except Exception as exc:  # pragma: no cover
                logger.debug("schema gen failed for %s: %s", tname, exc)
        cats = TOOL_REGISTRY._categories.get(tname, ["misc"])
        risk = "high" if tname in TOOL_REQUIRES_KEY else "low"
        out.append(
            {
                "id": tname,
                "name": tname,
                "domain": "cai",
                "category": cats[0] if cats else "misc",
                "categories": cats,
                "description": desc,
                "risk": risk,
                "source": "cai-native",
                "schema": {
                    "type": "function",
                    "function": {
                        "name": tname,
                        "description": desc,
                        "parameters": parameters,
                    },
                },
            }
        )
    return out


def discover_cai_roles() -> list[dict]:
    """Enumerate every CAI sub-agent role via CAI's factory discovery."""
    global _CAI_ROLES_DISCOVERED
    if _CAI_ROLES_DISCOVERED is not None:
        return _CAI_ROLES_DISCOVERED
    _ensure_cai_path()
    roles: list[dict] = []
    try:
        from cai.agents.factory import discover_agent_factories

        factories = discover_agent_factories()
        seen = set()
        for role_id, factory in sorted(factories.items()):
            if role_id in seen:
                continue
            seen.add(role_id)
            try:
                agent = factory()
                name = getattr(agent, "name", role_id)
                desc = getattr(agent, "description", "") or ""
                roles.append(
                    {
                        "id": role_id,
                        "name": name,
                        "description": desc,
                        "source": "cai-native",
                    }
                )
            except Exception as exc:  # pragma: no cover
                logger.debug("factory failed for %s: %s", role_id, exc)
                roles.append({"id": role_id, "name": role_id, "description": "", "source": "cai-native"})
    except Exception as exc:  # pragma: no cover
        logger.warning("CAI role discovery failed: %s", exc)
    _CAI_ROLES_DISCOVERED = roles
    return roles


def cai_tool_count() -> int:
    _ensure_cai_path()
    from cai.tool_registry import TOOL_REGISTRY

    if not _CAI_TOOLS_IMPORTED:
        import_all_cai_tools()
    return TOOL_REGISTRY.count


__all__ = [
    "import_all_cai_tools",
    "list_cai_tools",
    "discover_cai_roles",
    "cai_tool_count",
]
