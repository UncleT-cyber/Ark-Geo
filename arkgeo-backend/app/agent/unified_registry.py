"""THE ARK — Unified Tool Registry.

ONE registry. ALL tools. Every domain, every provider, every capability.

This module is the single source of truth for every tool available to the
ARK agent orchestrator. It merges three previously separate tool universes:

1. ARK Agent Substrate — IMAGE/network/secops/pentest/osint/ros specialist
   tools registered in ``app.agent.tool_registry``.
2. ARK Forensic Catalogue — the forensic analysis tools registered in
   ``app.engine.tool_adapter`` (geocoding, vision, reverse search, etc.).
3. CAI Native Tools — the Cybersecurity AI toolkit (curl, nmap, netcat,
   shell execution, web recon, exploitation, etc.) registered in CAI's
   ``TOOL_REGISTRY``.

At startup, ``unified_registry.populate()`` pulls every tool from all three
sources into a single flat namespace. Deduplication happens at registration
time — the first tool to claim an ID wins; later arrivals with the same
normalized name are logged and skipped.

After population, the orchestrator calls only ``unified_registry.call()``
or ``unified_registry.acall()``. No more three-tier dispatch. No more
runtime merging. No more prefix-collision bugs.

Usage::

    from app.agent.unified_registry import unified_registry

    # At startup (once):
    unified_registry.populate()

    # Schema for the LLM:
    tools = unified_registry.openai_tools()

    # Dispatch:
    result = await unified_registry.acall("nmap_scan", host="10.0.0.1")
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("ark.unified_registry")


def _norm(s: str) -> str:
    """Normalize a tool ID for deduplication: lowercase, strip non-alphanum."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# --------------------------------------------------------------------------- #
# Unified tool wrapper — every tool, regardless of source, is wrapped in this.
# --------------------------------------------------------------------------- #
@dataclass
class UnifiedTool:
    """One tool from any source, with a unified interface."""
    tool_id: str
    name: str
    description: str
    domain: str
    category: str
    risk: str
    source: str  # "ark_substrate" | "ark_catalogue" | "cai_native"
    handler: Any  # callable(**kwargs) -> dict
    input_schema: dict = field(default_factory=dict)
    openai_schema: dict = field(default_factory=dict)
    deterministic: bool = True
    async_capable: bool = False
    permissions: list[str] = field(default_factory=list)
    cost: dict = field(default_factory=dict)

    @property
    def spec(self):
        """Backward-compatible shim for code that still does ``tool.spec``."""
        return _LegacySpec(self)


class _LegacySpec:
    """Shim that makes UnifiedTool look like the old Tool.spec for consumers
    like ``services/agent/tools.py`` that still do ``tool.spec.tool_id`` etc."""

    def __init__(self, tool: UnifiedTool) -> None:
        self._tool = tool

    @property
    def tool_id(self) -> str:
        return self._tool.tool_id

    @property
    def name(self) -> str:
        return self._tool.name

    @property
    def description(self) -> str:
        return self._tool.description

    @property
    def input_schema(self) -> dict:
        return self._tool.input_schema

    @property
    def risk(self):
        return self._tool.risk

    @property
    def deterministic(self) -> bool:
        return self._tool.deterministic

    @property
    def domain(self) -> str:
        return self._tool.domain


class _RegistryShim:
    """Backward-compatible shim so ``from app.agent.tool_registry import registry``
    consumers still work. Delegates to ``unified_registry``."""

    def __init__(self) -> None:
        self._unified = None

    def _ensure(self):
        if self._unified is None:
            from app.agent.unified_registry import unified_registry
            if not unified_registry._populated:
                unified_registry.populate()
            self._unified = unified_registry

    def get(self, tool_id: str):
        self._ensure()
        return self._unified.get(tool_id)

    def list(self, domain=None):
        self._ensure()
        return self._unified.specs(domain)

    def specs(self, domain=None):
        self._ensure()
        return self._unified.specs(domain)

    async def acall(self, tool_id: str, **kwargs):
        self._ensure()
        return await self._unified.acall(tool_id, **kwargs)


# Module-level singleton for backward compatibility
registry = _RegistryShim()


# --------------------------------------------------------------------------- #
# The Unified Registry
# --------------------------------------------------------------------------- #
class UnifiedToolRegistry:
    """Single source of truth for ALL ARK + CAI tools.

    After ``populate()``, every tool is accessible via:
    - ``get(tool_id)`` → UnifiedTool or None
    - ``call(tool_id, **kwargs)`` → dict (sync)
    - ``acall(tool_id, **kwargs)`` → dict (async)
    - ``openai_tools(domain)`` → list[dict] (OpenAI function schemas)
    - ``specs(domain)`` → list[UnifiedTool]
    """

    def __init__(self) -> None:
        self._tools: dict[str, UnifiedTool] = {}
        self._by_norm: dict[str, str] = {}  # normalized name → tool_id
        self._populated = False

    # ------------------------------------------------------------------ #
    # Population — pull all tools from all three sources
    # ------------------------------------------------------------------ #
    def populate(self) -> int:
        """Import and register every tool from all three registries.

        Returns the total number of tools registered.
        """
        if self._populated:
            return len(self._tools)

        count = 0
        count += self._register_ark_substrate()
        count += self._register_ark_catalogue()
        count += self._register_cai_native()

        self._populated = True
        logger.info(
            "[Unified Registry] Populated: %d tools total "
            "(%d after dedup)", count, len(self._tools)
        )
        return len(self._tools)

    def _register_ark_substrate(self) -> int:
        """Pull tools from app.agent.tool_registry (the specialist substrate)."""
        try:
            from app.agent.tool_registry import registry as substrate
            from app.agent.schemas import RiskLevel, ToolCategory, Availability

            count = 0
            for tool in substrate._tools.values():
                spec = tool.spec
                handler = tool.handler

                # Determine risk level as string
                risk = spec.risk.value if hasattr(spec.risk, 'value') else str(spec.risk)

                # Determine category as string
                category = spec.category.value if hasattr(spec.category, 'value') else str(spec.category)

                # Determine if handler is async
                is_async = asyncio.iscoroutinefunction(handler)

                ut = UnifiedTool(
                    tool_id=spec.tool_id,
                    name=spec.name,
                    description=spec.description or "",
                    domain=spec.domain or "general",
                    category=category,
                    risk=risk,
                    source="ark_substrate",
                    handler=handler,
                    input_schema=getattr(spec, 'input_schema', None) or {},
                    deterministic=spec.deterministic if hasattr(spec, 'deterministic') else True,
                    async_capable=is_async,
                    permissions=[p.value if hasattr(p, 'value') else str(p)
                                 for p in (spec.permissions or [])],
                    cost=spec.cost_estimate.model_dump() if hasattr(spec, 'cost_estimate') and spec.cost_estimate else {},
                )
                self._add(ut)
                count += 1

            logger.info("[Unified Registry] ARK substrate: %d tools", count)
            return count
        except Exception as exc:
            logger.warning("[Unified Registry] ARK substrate import failed: %s", exc)
            return 0

    def _register_ark_catalogue(self) -> int:
        """Pull tools from app.engine.tool_adapter (the forensic catalogue)."""
        try:
            from app.engine import tool_adapter

            count = 0
            for ark_tool in tool_adapter._CATALOGUE:
                # Skip if already registered from substrate
                if self._find(ark_tool.id):
                    continue

                handler = ark_tool.func
                is_async = asyncio.iscoroutinefunction(handler)

                # Generate OpenAI schema from function signature
                openai_schema = {}
                try:
                    from cai.sdk.agents.function_schema import function_schema
                    fs = function_schema(handler)
                    openai_schema = {
                        "type": "function",
                        "function": {
                            "name": ark_tool.id,
                            "description": ark_tool.description or "",
                            "parameters": fs.params_json_schema,
                        },
                    }
                except Exception:
                    openai_schema = {
                        "type": "function",
                        "function": {
                            "name": ark_tool.id,
                            "description": ark_tool.description or "",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }

                ut = UnifiedTool(
                    tool_id=ark_tool.id,
                    name=ark_tool.name,
                    description=ark_tool.description or "",
                    domain=ark_tool.domain or "general",
                    category=ark_tool.domain or "general",
                    risk=getattr(ark_tool, 'risk', 'low'),
                    source="ark_catalogue",
                    handler=handler,
                    input_schema=ark_tool.schema or {},
                    openai_schema=openai_schema,
                    deterministic=ark_tool.simulated if hasattr(ark_tool, 'simulated') else True,
                    async_capable=is_async,
                )
                self._add(ut)
                count += 1

            logger.info("[Unified Registry] ARK catalogue: %d tools", count)
            return count
        except Exception as exc:
            logger.warning("[Unified Registry] ARK catalogue import failed: %s", exc)
            return 0

    def _register_cai_native(self) -> int:
        """Pull tools from CAI's TOOL_REGISTRY (the cybersecurity toolkit)."""
        try:
            from app.engine.cai.tools_importer import _ensure_cai_path, import_all_cai_tools
            _ensure_cai_path()
            import_all_cai_tools()
            from cai.tool_registry import TOOL_REGISTRY

            count = 0
            for tool in TOOL_REGISTRY.all():
                tname = getattr(tool, "name", str(tool))
                desc = getattr(tool, "description", "") or ""

                # Skip if already registered
                if self._find(tname):
                    continue

                func = getattr(tool, "func", None)
                if func is None:
                    continue

                is_async = asyncio.iscoroutinefunction(func)

                # Generate OpenAI schema
                openai_schema = {}
                try:
                    from cai.sdk.agents.function_schema import function_schema
                    fs = function_schema(func)
                    openai_schema = {
                        "type": "function",
                        "function": {
                            "name": tname,
                            "description": desc,
                            "parameters": fs.params_json_schema,
                        },
                    }
                except Exception:
                    openai_schema = {
                        "type": "function",
                        "function": {
                            "name": tname,
                            "description": desc,
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }

                # Get categories
                cats = TOOL_REGISTRY._categories.get(tname, ["misc"])

                ut = UnifiedTool(
                    tool_id=tname,
                    name=tname,
                    description=desc,
                    domain="cai",
                    category=cats[0] if cats else "misc",
                    risk="low",
                    source="cai_native",
                    handler=func,
                    openai_schema=openai_schema,
                    async_capable=is_async,
                )
                self._add(ut)
                count += 1

            logger.info("[Unified Registry] CAI native: %d tools", count)
            return count
        except Exception as exc:
            logger.warning("[Unified Registry] CAI native import failed: %s", exc)
            return 0

    # ------------------------------------------------------------------ #
    # Internal registration
    # ------------------------------------------------------------------ #
    def _add(self, tool: UnifiedTool) -> bool:
        """Register a tool. Returns True if added, False if deduplicated."""
        tid = tool.tool_id
        ntid = _norm(tid)

        # Exact match — skip
        if tid in self._tools:
            logger.debug("[Unified Registry] Dedup (exact): %s from %s",
                         tid, tool.source)
            return False

        # Normalized match — skip
        if ntid in self._by_norm:
            existing = self._tools[self._by_norm[ntid]]
            logger.debug(
                "[Unified Registry] Dedup (norm): %s (%s) collides with %s (%s)",
                tid, tool.source, existing.tool_id, existing.source
            )
            return False

        self._tools[tid] = tool
        self._by_norm[ntid] = tid
        return True

    def _find(self, tool_id: str) -> Optional[UnifiedTool]:
        """Find a tool by exact ID or normalized match."""
        if tool_id in self._tools:
            return self._tools[tool_id]
        ntid = _norm(tool_id)
        if ntid in self._by_norm:
            return self._tools[self._by_norm[ntid]]
        return None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def get(self, tool_id: str) -> Optional[UnifiedTool]:
        """Get a tool by ID."""
        return self._find(tool_id)

    def list(self, domain: str | None = None) -> list[UnifiedTool]:
        """List all tools, optionally filtered by domain."""
        tools = list(self._tools.values())
        if domain:
            tools = [t for t in tools if t.domain == domain]
        return tools

    def specs(self, domain: str | None = None) -> list[UnifiedTool]:
        """Alias for list()."""
        return self.list(domain)

    def count(self) -> int:
        """Total number of registered tools."""
        return len(self._tools)

    def domains(self) -> list[str]:
        """List all registered domains."""
        return sorted(set(t.domain for t in self._tools.values()))

    # ------------------------------------------------------------------ #
    # Schema generation — what the LLM sees
    # ------------------------------------------------------------------ #
    def openai_tools(self, domain: str | None = None) -> list[dict]:
        """Return OpenAI function-call schemas for all tools."""
        tools = self.list(domain)
        schemas = []
        for t in tools:
            if t.openai_schema:
                schemas.append(t.openai_schema)
            else:
                schemas.append({
                    "type": "function",
                    "function": {
                        "name": t.tool_id,
                        "description": t.description,
                        "parameters": t.input_schema or {"type": "object", "properties": {}},
                    },
                })
        return schemas

    # ------------------------------------------------------------------ #
    # Execution — sync and async
    # ------------------------------------------------------------------ #
    def call(self, tool_id: str, **kwargs) -> dict:
        """Execute a tool synchronously. Returns raw handler result."""
        tool = self._find(tool_id)
        if tool is None:
            return {"status": "error", "tool": tool_id,
                    "error": f"unknown tool: {tool_id}"}
        return tool.handler(**kwargs)

    async def acall(self, tool_id: str, **kwargs) -> dict:
        """Execute a tool asynchronously. Returns raw handler result."""
        tool = self._find(tool_id)
        if tool is None:
            return {"status": "error", "tool": tool_id,
                    "error": f"unknown tool: {tool_id}"}
        if tool.async_capable:
            return await tool.handler(**kwargs)
        else:
            return await asyncio.to_thread(tool.handler, **kwargs)

    # ------------------------------------------------------------------ #
    # Legacy compatibility — maps to old interfaces
    # ------------------------------------------------------------------ #
    def get_tool(self, tool_id: str):
        """Legacy: return a tool-like object with .spec and .handler."""
        tool = self._find(tool_id)
        if tool is None:
            return None

        class _LegacyTool:
            def __init__(self, ut):
                self.tool_id = ut.tool_id
                self.name = ut.name
                self.description = ut.description
                self.domain = ut.domain
                self.handler = ut.handler
                self.spec = type('obj', (object,), {
                    'tool_id': ut.tool_id,
                    'name': ut.name,
                    'description': ut.description,
                    'domain': ut.domain,
                    'risk': ut.risk,
                    'category': ut.category,
                    'permissions': ut.permissions,
                    'deterministic': ut.deterministic,
                    'availability': 'available',
                    'input_schema': ut.input_schema,
                    'cost_estimate': type('obj', (object,), {
                        'model_dump': lambda self: ut.cost
                    })(),
                })()

        return _LegacyTool(tool)


# --------------------------------------------------------------------------- #
# Singleton
# --------------------------------------------------------------------------- #
unified_registry = UnifiedToolRegistry()
