"""JSON Function Schemas + typed execution — the native tool-calling adapter.

Converts the ARK Tool Registry (``app.agent.tool_registry``) into OpenAI-format
JSON Function Schemas so the ReAct loop can present the full capability surface
to a tool-calling model, then coerces the model's JSON arguments to the
handler's declared types and executes through the registry + policy guard.

Everything here is derived from the registry at runtime — adding a tool to the
catalog automatically adds its function schema. There is no hardcoded tool
count and no per-tool special case: the surface is whatever ``registry.list()``
registers. Tools whose call cannot be satisfied from a text prompt (e.g. a
required binary ``image_bytes`` payload) are hidden rather than advertised.

The loop owns policy: every call is authorized through the Policy Guard before
it executes; this module never bypasses ``registry.acall``.
"""
from __future__ import annotations

import inspect
import json
import logging
import re
import typing
from typing import Any, Optional

from app.agent.unified_registry import UnifiedTool as Tool, registry

logger = logging.getLogger(__name__)

# Clip tool results before they re-enter model context, so a huge inspector
# result cannot blow the context window or the terminal stream.
_MAX_RESULT_CHARS = 8000


# --------------------------------------------------------------------------- #
# Handler-parameter introspection — JSON-compatible params only.
# --------------------------------------------------------------------------- #
def _annotation_json_type(annotation: Any) -> Optional[str]:
    """Map a handler type annotation to a JSON Schema type, or None."""
    if annotation is inspect.Parameter.empty or annotation is None:
        return None
    try:
        origin = typing.get_origin(annotation)
    except Exception:  # noqa: BLE001 — exotic annotations degrade to None
        origin = None
    if origin is not None:
        if origin is typing.Union:
            args = tuple(
                a for a in typing.get_args(annotation) if a is not type(None)
            )
            if len(args) == 1:
                return _annotation_json_type(args[0])
            return None
        if origin in (list, tuple, typing.List):
            return "array"
        if origin in (dict, typing.Dict):
            return "object"
        return None
    if annotation in (str,):
        return "string"
    if annotation in (int,):
        return "integer"
    if annotation in (float,):
        return "number"
    if annotation in (bool,):
        return "boolean"
    # bytes / bytearray / anything else → not JSON-passable from a prompt.
    return None


def _is_binary_annotation(annotation: Any) -> bool:
    if annotation is inspect.Parameter.empty:
        return False
    try:
        origin = typing.get_origin(annotation)
    except Exception:  # noqa: BLE001
        origin = None
    if origin is typing.Union:
        return any(_is_binary_annotation(a) for a in typing.get_args(annotation)
                   if a is not type(None))
    return annotation in (bytes, bytearray)


def _string_annotation_type(s: str) -> Optional[str]:
    """Best-effort JSON type for a PEP-563 string annotation."""
    text = (s or "").strip()
    m = re.match(r"^(?:Optional|Union)\[(.+)\]$", text)
    if m:
        return _string_annotation_type(m.group(1))
    if text in ("bytes", "bytearray"):
        return None
    if text == "str":
        return "string"
    if text == "int":
        return "integer"
    if text == "float":
        return "number"
    if text == "bool":
        return "boolean"
    if text == "list" or text.startswith("list["):
        return "array"
    if text == "dict" or text.startswith("dict["):
        return "object"
    return None


def _string_annotation_binary(s: str) -> bool:
    text = (s or "").strip()
    m = re.match(r"^(?:Optional|Union)\[(.+)\]$", text)
    if m:
        return _string_annotation_binary(m.group(1))
    return text in ("bytes", "bytearray")


def _resolved_annotations(func) -> dict[str, Any]:
    """Resolve PEP-563 string annotations when the module can, else empty."""
    try:
        return typing.get_type_hints(func)
    except Exception:  # noqa: BLE001 — unresolvable hints fall back to raw
        return {}


def _handler_params(tool: Tool) -> dict[str, dict]:
    """Introspect the handler signature into param metadata.

    Returns ``{name: {"required": bool, "json_type": Optional[str],
    "is_binary": bool}}``. Handlers declare ``from __future__ import
    annotations``, so string annotations are resolved (or parsed) before being
    mapped to a JSON Schema type.
    """
    out: dict[str, dict] = {}
    try:
        sig = inspect.signature(tool.handler)
    except (TypeError, ValueError):
        return out
    hints = _resolved_annotations(tool.handler)
    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        if param.kind not in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY):
            continue
        annotation = hints.get(name, param.annotation)
        json_type = _annotation_json_type(annotation)
        is_binary = _is_binary_annotation(annotation)
        if isinstance(annotation, str):
            if json_type is None:
                json_type = _string_annotation_type(annotation)
            if not is_binary:
                is_binary = _string_annotation_binary(annotation)
        required = param.default is inspect.Parameter.empty
        out[name] = {
            "required": required,
            "json_type": json_type,
            "is_binary": is_binary,
        }
    return out


def _prop_from_field(name: str, field: dict) -> dict:
    """Convert one ToolSpec ``input_schema`` field into a JSON Schema property."""
    prop: dict[str, Any] = {"type": field.get("type", "string")}
    if field.get("description"):
        prop["description"] = field["description"]
    if field.get("enum"):
        prop["enum"] = field["enum"]
    items = field.get("items")
    if items:
        prop["items"] = items
    if prop["type"] in ("array", "object") and "items" not in prop:
        prop.pop("items", None)
    return prop


# --------------------------------------------------------------------------- #
# Schema emission
# --------------------------------------------------------------------------- #
def schema_for_tool(tool: Tool) -> Optional[dict]:
    """Build one OpenAI-format function schema for a registered tool.

    Returns ``None`` for tools the model cannot call from a text prompt (a
    required binary payload such as ``image_bytes``) — they are hidden, not
    advertised. Function ``name`` is the registry ``tool_id`` so execution maps
    straight back through ``registry.acall(tool_id, **arguments)``.
    """
    spec = tool.spec
    raw_schema = spec.input_schema or {}
    handler_params = _handler_params(tool)

    # A tool whose call can't be satisfied from a text prompt is hidden.
    for pinfo in handler_params.values():
        if pinfo["required"] and (pinfo["is_binary"] or pinfo["json_type"] is None):
            return None

    # Normalize input_schema: handle both flat {field: {type, desc}} and
    # full JSON Schema {type: "object", properties: {...}, required: [...]}
    props: dict[str, dict] = {}
    required: list[str] = []

    if "properties" in raw_schema:
        # Full JSON Schema format
        props = raw_schema["properties"]
        required = raw_schema.get("required", [])
    else:
        # Legacy flat format: {field_name: {type, description, required, ...}}
        for name, field in raw_schema.items():
            if not isinstance(field, dict):
                continue
            props[name] = _prop_from_field(name, field)
            if field.get("required"):
                required.append(name)

    for name, pinfo in handler_params.items():
        if name in props:
            if pinfo["required"] and name not in required:
                required.append(name)
            continue
        if pinfo["is_binary"] or pinfo["json_type"] is None:
            continue
        props[name] = {
            "type": pinfo["json_type"],
            "description": f"{name} argument for {spec.name}.",
        }
        if pinfo["required"]:
            required.append(name)

    if not props:
        return None

    function: dict[str, Any] = {
        "name": spec.tool_id,
        "description": spec.description,
        "parameters": {
            "type": "object",
            "properties": props,
        },
    }
    if required:
        function["parameters"]["required"] = required
    return {"type": "function", "function": function}


def function_schemas(
    *,
    tool_ids: Optional[list[str]] = None,
    domain: Optional[str] = None,
) -> list[dict]:
    """Emit the full JSON Function Schema surface for the ReAct loop.

    By default every registered tool that can be called from a text prompt is
    exposed. ``tool_ids`` / ``domain`` narrow the surface when a caller wants
    to restrict what the model may choose (the policy guard still authorizes
    each call regardless).
    """
    tools = registry.list(domain)
    if tool_ids is not None:
        allowed = set(tool_ids)
        tools = [t for t in tools if t.tool_id in allowed]
    schemas: list[dict] = []
    for tool in tools:
        schema = schema_for_tool(tool)
        if schema:
            schemas.append(schema)
    return schemas


def callable_tool_ids() -> list[str]:
    """The tool_ids that are exposed to a tool-calling model."""
    return [
        tool.tool_id for tool in registry.list()
        if schema_for_tool(tool) is not None
    ]


# --------------------------------------------------------------------------- #
# Argument coercion — the model returns strings; handlers want real types.
# --------------------------------------------------------------------------- #
def _coerce(value: Any, field: Optional[dict]) -> Any:
    if field is None:
        return value
    t = field.get("type")
    if t == "integer":
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return value
    if t == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if t == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "y", "on")
        return bool(value)
    if t == "array":
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else [parsed]
            except (TypeError, ValueError):
                return [value]
        if isinstance(value, list):
            items = field.get("items") or {}
            return [_coerce(v, items) for v in value]
        return value
    return value


def coerce_arguments(tool_id: str, arguments: Optional[dict]) -> dict:
    """Coerce the model's JSON arguments to the tool's declared types."""
    tool = registry.get(tool_id)
    if tool is None:
        return dict(arguments or {})
    raw_schema = tool.spec.input_schema or {}
    # Normalize: extract field-level schemas from either format
    if "properties" in raw_schema:
        fields = raw_schema["properties"]
    else:
        fields = raw_schema
    coerced: dict[str, Any] = {}
    for key, value in (arguments or {}).items():
        field = fields.get(key)
        coerced[key] = _coerce(value, field if isinstance(field, dict) else None)
    return coerced


# --------------------------------------------------------------------------- #
# Result normalization — JSON-safe, context-clipped.
# --------------------------------------------------------------------------- #
def _clip(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= _MAX_RESULT_CHARS \
            else value[:_MAX_RESULT_CHARS] + "…"
    return value


def _clip_deep(value: Any, budget: int = _MAX_RESULT_CHARS) -> Any:
    if isinstance(value, str):
        return _clip(value)
    if isinstance(value, list):
        return [_clip_deep(v, budget) for v in value[:100]]
    if isinstance(value, dict):
        return {k: _clip_deep(v, budget) for k, v in list(value.items())[:200]}
    return value


def normalize_result(result: Any) -> dict:
    """Serialize a tool result into the ``{ok, result}`` shape for role:tool."""
    if result is None:
        return {"ok": True, "result": None}
    if isinstance(result, str):
        return {"ok": True, "result": _clip(result)}
    try:
        payload = json.loads(json.dumps(result, default=str))
    except (TypeError, ValueError):
        payload = {"value": _clip(str(result))}
    return {"ok": True, "result": _clip_deep(payload)}


async def execute_tool(tool_id: str, arguments: Optional[dict]) -> dict:
    """Run a registered tool with coerced arguments. Never raises.

    Returns ``{"ok": True, "result": ...}`` on success or
    ``{"ok": False, "error": ...}`` on failure / unknown tool. This is the only
    path that touches the registry from the ReAct loop; policy authorization is
    the loop's responsibility and happens before this is called.
    """
    tool = registry.get(tool_id)
    if tool is None:
        return {"ok": False, "error": f"tool {tool_id} is not registered"}
    try:
        args = coerce_arguments(tool_id, arguments)
        result = await registry.acall(tool_id, **args)
    except Exception as exc:  # noqa: BLE001 — a tool failure is not fatal
        logger.warning("Tool %s failed: %s", tool_id, exc)
        return {"ok": False, "error": str(exc)}
    normalized = normalize_result(result)
    return normalized
