"""THE ARK — Unified Slash Command Registry.

A single autocomplete surface that blends CAI engine-control commands with ARK
workspace/case commands. The Terminal UI calls :func:`complete` on every keystroke
after a leading ``/`` and :func:`parse` to dispatch. Commands are declarative so
both the backend (dispatch) and the frontend (autocomplete menu) share one source
of truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class SlashCommand:
    name: str  # without leading slash
    group: str  # "engine" | "ark"
    description: str
    usage: str
    # HITL hint: how the Terminal should capture the argument. "text" | "choice" | "none"
    arg_mode: str = "none"
    choices: List[str] = None  # for arg_mode == "choice"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "group": self.group,
            "description": self.description,
            "usage": self.usage,
            "arg_mode": self.arg_mode,
            "choices": self.choices or [],
        }


def _agent_choices() -> list[str]:
    """Dynamic list of all loadable CAI + ARK agent roles for ``/agent``."""
    try:
        from app.engine.cai.registry import get_agent_roles

        roles = [r["id"] for r in get_agent_roles()]
        if roles:
            return roles
    except Exception:
        pass
    return ["generalist"]


_COMMANDS: List[SlashCommand] = [
    # --- Engine control (CAI) ---
    SlashCommand("agent", "engine", "Select the CAI specialist role for the session", "/agent <role>", arg_mode="choice", choices=_agent_choices()),
    SlashCommand("model", "engine", "Switch the model backend (Ollama / OpenAI / Claude / Gemini)", "/model <provider:model>", arg_mode="text"),
    SlashCommand("sessions", "engine", "Show session history and turn counts", "/sessions", arg_mode="none"),
    SlashCommand("env", "engine", "Show or set engine environment / settings", "/env [key=value]", arg_mode="text"),
    SlashCommand("tools", "engine", "List all registered ARK tools by domain", "/tools [domain]", arg_mode="text"),
    # --- ARK workspace ---
    SlashCommand("case", "ark", "Attach a case vault folder to the session", "/case <case_id>", arg_mode="text"),
    SlashCommand("evidence", "ark", "Inspect chain-of-custody for an evidence item", "/evidence <evidence_id>", arg_mode="text"),
    SlashCommand("clear", "ark", "Reset the terminal / clear session transcript", "/clear", arg_mode="none"),
    SlashCommand("help", "ark", "Show this command reference", "/help", arg_mode="none"),
]


_COMMAND_INDEX = {f"/{c.name}": c for c in _COMMANDS}


def all_commands() -> List[dict]:
    return [c.to_dict() for c in _COMMANDS]


def complete(prefix: str) -> List[dict]:
    """Return commands whose name starts with ``prefix`` (prefix includes '/'?)."""
    p = prefix if prefix.startswith("/") else "/" + prefix
    p = p.lower()
    if p == "/":
        return all_commands()
    return [c.to_dict() for c in _COMMANDS if f"/{c.name}".lower().startswith(p)]


def parse(text: str):
    """Parse a ``/command arg...`` string into (command, args_str)."""
    if not text.startswith("/"):
        return None, ""
    parts = text[1:].split(maxsplit=1)
    name = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    return name, args


def get_command(name: str) -> SlashCommand | None:
    return _COMMAND_INDEX.get("/" + name)


__all__ = ["SlashCommand", "all_commands", "complete", "parse", "get_command"]
