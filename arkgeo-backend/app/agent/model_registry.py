"""Model Registry — the routable-model surface (Phase H, cognitive unit 09).

Mirrors :mod:`app.agent.tool_registry`: the tool registry is the capability
surface the *policy guard* authorizes; this registry is the model surface the
*model policy* routes over. Every model the orchestrator may use is described
once, as a :class:`~app.agent.schemas.ModelSpec` (id, capability, local/remote,
cost, offline-ok, pinned version).

Two arms ship by default:

* **Local planner** — Ollama (``qwen2.5-coder:3b`` by default), planning /
  routing / critic capabilities, ``local=True``, ``offline_ok=True``,
  ``zero_retention_safe=True``. The only model a sensitive case may use.
* **Cloud planner** — a remote OpenAI-compatible arm, planning / routing,
  ``local=False``, ``offline_ok=False``, ``zero_retention_safe=False``.

The local arm's model id and endpoint are read from the Admin Console gateway
config (same single source of truth the gateway uses), so a model swap in Admin
takes effect here too. The registry never performs I/O of its own and never
raises on a missing config — it degrades to the built-in defaults.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from . import schemas as S

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_MODEL = "qwen2.5-coder:3b"
DEFAULT_LOCAL_NAME = "Qwen 2.5 Coder 3B (local planner)"
DEFAULT_LOCAL_VISION_MODEL = "llama3.2-vision:latest"
CLOUD_PLANNER_MODEL = "cloud/planner"
CLOUD_VISION_MODEL = "cloud/vision"


class Model:
    """A registered model: spec + (optional) gateway factory.

    The factory is a zero-arg callable returning a
    :class:`~app.agent.model_gateway.ModelGateway`; it is resolved lazily so
    credentials read from the settings store at call time (an Admin key update
    is picked up without rebuilding the registry).
    """

    def __init__(
        self,
        spec: S.ModelSpec,
        factory: Optional[Callable[[], object]] = None,
    ) -> None:
        self.spec = spec
        self._factory = factory

    @property
    def model_id(self) -> str:
        return self.spec.model_id

    def gateway(self) -> Optional[object]:
        """Build the gateway for this model, or ``None`` when unconfigured."""
        if self._factory is None:
            return None
        try:
            return self._factory()
        except Exception:  # noqa: BLE001 — a missing key must never raise
            logger.warning("Model gateway factory failed for %s", self.model_id)
            return None


def _local_spec() -> S.ModelSpec:
    """The local planner spec, model id/endpoint read from Admin config."""
    model_id = DEFAULT_LOCAL_MODEL
    try:
        from ..services.admin_store import admin_store

        gw = admin_store.get_gateway()
        model_id = (gw.get("ollama_model") or "").strip() or DEFAULT_LOCAL_MODEL
    except Exception:  # noqa: BLE001 — registry must import without services
        pass
    return S.ModelSpec(
        model_id=model_id,
        name=DEFAULT_LOCAL_NAME,
        capabilities=[
            S.ModelCapability.PLANNING,
            S.ModelCapability.ROUTING,
            S.ModelCapability.CRITIC,
            S.ModelCapability.REASONING,
        ],
        provider=S.ModelProvider.OLLAMA,
        local=True,
        version="2.5",
        offline_ok=True,
        zero_retention_safe=True,
        cost_estimate=S.CostEstimate(model_tokens=0, api_calls=0, est_ms=0),
        endpoint=model_id,
    )


def _cloud_planner_spec() -> S.ModelSpec:
    return S.ModelSpec(
        model_id=CLOUD_PLANNER_MODEL,
        name="Cloud planner (OpenAI-compatible)",
        capabilities=[
            S.ModelCapability.PLANNING,
            S.ModelCapability.ROUTING,
            S.ModelCapability.REASONING,
        ],
        provider=S.ModelProvider.OTHER,
        local=False,
        offline_ok=False,
        zero_retention_safe=False,
        endpoint=None,
    )


def _local_vision_spec() -> S.ModelSpec:
    """Local vision arm (Ollama multimodal). The only vision model a
    zero-retention case may use.

    The model tag is read from the Admin Console's per-task rotator
    (``task_models.vision_imint``), falling back to the built-in default —
    the same precedence the runtime vision path uses.
    """
    model_id = DEFAULT_LOCAL_VISION_MODEL
    try:
        from ..services.admin_store import admin_store

        gw = admin_store.get_gateway()
        model_id = ((gw.get("task_models") or {}).get("vision_imint")
                    or "").strip() or DEFAULT_LOCAL_VISION_MODEL
    except Exception:  # noqa: BLE001
        pass
    return S.ModelSpec(
        model_id=model_id,
        name="Local vision model (Ollama)",
        capabilities=[
            S.ModelCapability.VISION,
            S.ModelCapability.OCR,
        ],
        provider=S.ModelProvider.OLLAMA,
        local=True,
        offline_ok=True,
        zero_retention_safe=True,
        endpoint=model_id,
    )


def _cloud_vision_spec() -> S.ModelSpec:
    return S.ModelSpec(
        model_id=CLOUD_VISION_MODEL,
        name="Cloud vision (OpenAI-compatible)",
        capabilities=[
            S.ModelCapability.VISION,
            S.ModelCapability.OCR,
        ],
        provider=S.ModelProvider.OTHER,
        local=False,
        offline_ok=False,
        zero_retention_safe=False,
        endpoint=None,
    )


def _local_factory() -> object:
    # Return the shared module-level singleton (not a fresh instance) so the
    # orchestrator and any test that monkeypatches ``model_gateway.gateway``
    # operate on the same object.
    from .model_gateway import gateway

    return gateway


def _cloud_factory() -> Optional[object]:
    from .model_gateway import resolve_huggingface_gateway

    return resolve_huggingface_gateway()


class ModelRegistry:
    """Lookup table of registered models, keyed by ``model_id``."""

    def __init__(self, models: Optional[list[Model]] = None) -> None:
        self._models: dict[str, Model] = {
            m.model_id: m for m in (models if models is not None else _catalog())
        }

    # ------------------------------------------------------------------ #
    def get(self, model_id: str) -> Optional[Model]:
        return self._models.get(model_id)

    def list(self, capability: Optional[S.ModelCapability] = None) -> list[Model]:
        if capability is None:
            return list(self._models.values())
        return [m for m in self._models.values()
                if capability in m.spec.capabilities]

    def specs(self, capability: Optional[S.ModelCapability] = None) -> list[S.ModelSpec]:
        return [m.spec for m in self.list(capability)]

    # ------------------------------------------------------------------ #
    def local_for(self, capability: S.ModelCapability) -> Optional[Model]:
        """First local, zero-retention-safe model serving ``capability``."""
        for m in self.list(capability):
            if m.spec.local and m.spec.zero_retention_safe:
                return m
        return None

    def default_for(self, capability: S.ModelCapability) -> Optional[Model]:
        """Preferred model for a capability when policy says nothing.

        Local-first: the deterministic-planner invariant prefers the on-box
        arm, which is also the safe default for sensitive cases.
        """
        return self.local_for(capability) or next(
            iter(self.list(capability)), None)

    def register(self, model: Model) -> None:
        self._models[model.model_id] = model


def _catalog() -> list[Model]:
    return [
        Model(_local_spec(), _local_factory),
        Model(_cloud_planner_spec(), _cloud_factory),
        Model(_local_vision_spec(), None),
        Model(_cloud_vision_spec(), None),
    ]


registry = ModelRegistry()
