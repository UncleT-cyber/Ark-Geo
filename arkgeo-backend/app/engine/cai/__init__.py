"""THE ARK — Embedded CAI Engine.

This package embeds the CAI (Cybersecurity AI) multi-agent runtime as THE ARK's
unified intelligence core. The upstream CAI source lives under ``./cai`` (a copy of
``arkgeo-backend/cai/src/cai``) and is imported as the top-level ``cai`` package by
injecting this directory onto ``sys.path``.

Design notes
------------
* Importing ``app.engine.cai`` is **side-effect free** with respect to CAI's heavy
  runtime dependencies (litellm, openai, textual, ...). We only register the path
  here; the actual ``import cai`` happens lazily inside :mod:`app.engine.agent_bridge`
  so THE ARK backend still boots when those optional deps are absent.
* ``CAI_LICENSE_OFF`` is forced on so CAI integrates seamlessly with local (Ollama)
  and cloud model providers without the upstream license gate.
"""
from __future__ import annotations

import os
import sys

# THE ARK runs the CAI ORIGINAL in-place. The upstream CAI source lives at
# ``arkgeo-backend/cai/src`` (the complete copy the operator placed in the
# project). We inject that directory onto sys.path so ``import cai`` resolves
# to the real CAI runtime. The embedded snapshot under ``./cai`` is kept only
# as a fallback if the original is absent.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_ORIGINAL_CAI_SRC = os.path.join(_BACKEND_ROOT, "cai", "src")
_EMBEDDED_CAI = os.path.join(_HERE, "cai")

for _p in (_ORIGINAL_CAI_SRC, _EMBEDDED_CAI):
    if os.path.isdir(os.path.join(_p, "cai")) and _p not in sys.path:
        sys.path.insert(0, _p)

CAI_PACKAGE_DIR = _ORIGINAL_CAI_SRC if os.path.isdir(os.path.join(_ORIGINAL_CAI_SRC, "cai")) else _EMBEDDED_CAI

# Seamless integration: bypass upstream license gate so Ollama / cloud models work.
os.environ.setdefault("CAI_LICENSE_OFF", "true")


def load_cai():
    """Lazily import and return the embedded ``cai`` package.

    Raises a clear, actionable error if the optional CAI runtime dependencies are
    not installed in the active interpreter.
    """
    try:
        import cai  # noqa: F401  (resolved from CAI_PACKAGE_DIR)
    except Exception as exc:  # pragma: no cover - depends on environment
        raise ImportError(
            "The embedded CAI engine could not be imported. Install its runtime "
            "dependencies (openai, litellm, rich, prompt_toolkit, questionary, "
            "PyYAML, tiktoken, mako, griffe, wasabi) into THE ARK backend venv."
        ) from exc
    return cai


def load_sdk_agents():
    """Lazily import ``cai.sdk.agents`` (Agent, Runner, function_tool, ...)."""
    cai = load_cai()
    from cai.sdk.agents import (  # noqa: F401
        Agent,
        Runner,
        RunContextWrapper,
        function_tool,
    )

    return {
        "cai": cai,
        "Agent": Agent,
        "Runner": Runner,
        "RunContextWrapper": RunContextWrapper,
        "function_tool": function_tool,
    }


__all__ = ["CAI_PACKAGE_DIR", "load_cai", "load_sdk_agents"]
