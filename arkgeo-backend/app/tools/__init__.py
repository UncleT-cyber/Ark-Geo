"""Headless OSINT tool modules for the ARK orchestrator.

Each module exposes async ``*_tool`` functions that return honest, structured
dicts.  A missing key or a failed provider degrades to ``UNAVAILABLE`` /
``ERROR`` — results are never fabricated.  The :mod:`app.agent.tool_registry`
wraps these as registered ``Tool`` capabilities (ToolSpec + handler).
"""
