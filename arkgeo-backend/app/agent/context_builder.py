"""Context builder — composes the ARK cognitive layer (identity contract).

The ARK Identity Contract is **composed at runtime**, never written as one
monolithic prompt. A system prompt is always:

    ARK CORE IDENTITY     (00_identity.prompt)
    + ARK GOVERNANCE      (01_governance.prompt)
    + ARK TOOL CONTRACT   (02_tool_contract.prompt)
    + ARK EVIDENCE CONTRACT (03_evidence_contract.prompt)
    + ARK REASONING POLICY  (04_reasoning_policy.prompt)
    + ARK REPORTING CONTRACT (05_reporting_contract.prompt)
    + <DOMAIN> SPECIALIST (domains/<domain>/{identity,reasoning,tools}.prompt)
    + AVAILABLE TOOLS     (dynamic, from the tool registry)

…and the *user* message carries the case context (objective + evidence
window + claims). Same ARK brain, different domain context.

The prompt files are data, not code. Missing files degrade gracefully to
the sections that do exist — the model gateway is never a hard dependency
of the deterministic pipeline, and neither are the prompt files.

See ``docs/ARK_INTEGRATED_SECURITY_ENVIRONMENT.md`` §6 (identity contract).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import schemas as S

_PKG = Path(__file__).resolve().parent
COGNITIVE_DIR = _PKG / "cognitive"
DOMAINS_DIR = _PKG / "domains"

_CORE_FILES: list[tuple[str, str]] = [
    ("ARK CORE IDENTITY", "00_identity.prompt"),
    ("ARK GOVERNANCE", "01_governance.prompt"),
    ("ARK TOOL CONTRACT", "02_tool_contract.prompt"),
    ("ARK EVIDENCE CONTRACT", "03_evidence_contract.prompt"),
    ("ARK REASONING POLICY", "04_reasoning_policy.prompt"),
    ("ARK REPORTING CONTRACT", "05_reporting_contract.prompt"),
]

_DOMAIN_FILES: tuple[str, ...] = ("identity.prompt", "reasoning.prompt", "tools.prompt")

# Domains that declare an identity contract even where tool engines are not
# yet registered (architectural placeholders, per the master plan §6).
DECLARED_DOMAINS: tuple[str, ...] = (
    "image", "network", "secops", "osint", "web", "cases", "pentest", "ros",
)


def _fmt_tool(t: S.ToolSpec) -> str:
    risk = getattr(t.risk, "value", t.risk)
    cat = getattr(t.category, "value", t.category)
    return f"- {t.tool_id}: {t.name} — {t.description} [risk={risk}, category={cat}]"


class ContextBuilder:
    """Loads the prompt files and composes per-domain system prompts."""

    def __init__(
        self,
        cognitive_dir: Optional[Path] = None,
        domains_dir: Optional[Path] = None,
    ) -> None:
        self.cognitive_dir = cognitive_dir or COGNITIVE_DIR
        self.domains_dir = domains_dir or DOMAINS_DIR

    # ------------------------------------------------------------------ #
    def read(self, path: Path) -> Optional[str]:
        try:
            text = path.read_text(encoding="utf-8").strip()
            return text or None
        except (FileNotFoundError, OSError):
            return None

    def core_blocks(self) -> list[tuple[str, str]]:
        blocks: list[tuple[str, str]] = []
        for title, fname in _CORE_FILES:
            content = self.read(self.cognitive_dir / fname)
            if content:
                blocks.append((title, content))
        return blocks

    def domain_blocks(self, domain: str) -> list[str]:
        blocks: list[str] = []
        for fname in _DOMAIN_FILES:
            content = self.read(self.domains_dir / domain / fname)
            if content:
                blocks.append(content)
        return blocks

    def tools_block(self, tool_specs: list[S.ToolSpec]) -> str:
        if not tool_specs:
            return "AVAILABLE TOOLS (none registered for this domain)"
        body = "\n".join(_fmt_tool(t) for t in tool_specs)
        return (
            "AVAILABLE TOOLS (registered for this domain — only these "
            "tool_ids may be chosen):\n" + body
        )

    # ------------------------------------------------------------------ #
    def build_system_prompt(
        self,
        domain: str,
        tool_specs: list[S.ToolSpec],
    ) -> str:
        """Compose the full system prompt for one domain.

        Section order: ARK core → domain specialist → available tools.
        Any section whose prompt file is missing is skipped.
        """
        parts: list[str] = []
        for title, content in self.core_blocks():
            parts.append(f"===== {title} =====\n{content}")
        domain_blocks = self.domain_blocks(domain)
        if domain_blocks:
            parts.append(
                f"===== DOMAIN — {domain.upper()} =====\n"
                + "\n\n".join(domain_blocks)
            )
        parts.append(self.tools_block(tool_specs))
        return "\n\n".join(parts)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _claims_line(objective: S.InvestigationObjective) -> str:
        return (
            ", ".join(f"{c.field}={c.value}" for c in objective.claims_to_verify)
            or "n/a"
        )

    def build_plan_prompt(
        self,
        objective: S.InvestigationObjective,
        tool_specs: list[S.ToolSpec],
    ) -> tuple[str, str]:
        """System + user messages for the initial plan proposal."""
        system = self.build_system_prompt(objective.domain, tool_specs)
        user = (
            "USER OBJECTIVE — construct an ordered investigation plan.\n"
            f"Goal: {objective.goal.value}\n"
            f"Domain: {objective.domain}\n"
            f"Subject / authorized scope: {objective.subject or 'n/a'}\n"
            f"Natural language: {objective.natural_language or 'n/a'}\n"
            f"Claims to verify: {self._claims_line(objective)}\n\n"
            "Return JSON only, shape: "
            '{"steps": [{"tool_id": "...", "rationale": "..."}]}. '
            "Choose only tool_ids listed under AVAILABLE TOOLS. Prefer "
            "deterministic read/analysis tools first; external or "
            "cost-bearing tools only where they add corroboration."
        )
        return system, user

    def build_next_prompt(
        self,
        objective: S.InvestigationObjective,
        gap: dict,
        tool_specs: list[S.ToolSpec],
        budget_summary: str,
    ) -> tuple[str, str]:
        """System + user messages for adaptive gap closure (propose_next)."""
        system = self.build_system_prompt(objective.domain, tool_specs)
        user = (
            "USER OBJECTIVE — the evidence graph has a gap that needs closing. "
            "Choose which registered tools should run next, in priority order, "
            "or return an empty steps list to terminate the investigation "
            "(converged / not worth the cost).\n"
            f"Objective: {objective.natural_language or objective.subject}\n"
            f"Gap: {gap.get('rationale', '')} (type: "
            f"{gap.get('gap_type', '')})\n"
            f"Budget state: {budget_summary}\n"
            "Return JSON only, shape: "
            '{"steps": [{"tool_id": "...", "rationale": "..."}]}. '
            "Empty steps means stop. Choose only tool_ids listed under "
            "AVAILABLE TOOLS; run the most information-gain tool first."
        )
        return system, user


context_builder = ContextBuilder()
