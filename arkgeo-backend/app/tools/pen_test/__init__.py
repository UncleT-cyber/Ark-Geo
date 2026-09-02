"""Offensive-security / authorized pentest tool modules for the ARK orchestrator.

Each module exposes async ``*_tool`` functions that return honest, structured
dicts with a ``state`` field (``AVAILABLE`` / ``UNAVAILABLE`` / ``ERROR`` /
``TOOL_MISSING``). Active capabilities (scanning, credential testing, hash
cracking, privilege enumeration) are wrapped subprocess / HTTP callers that
refuse to run without explicit authorization, degrade honestly when a binary
or key is absent, and never fabricate results. The Policy Guard governs every
registered tool before the orchestrator may invoke it.

NOTE: ``web_shell_injector`` (payload upload + command-execution hook) is
intentionally NOT implemented. The module shipped here instead is a *defensive*
``webshell_detector`` (web-root scan for known shell signatures) so the
Exploit phase of the RE-ACT chain operates from a detection / DFIR posture.
"""
