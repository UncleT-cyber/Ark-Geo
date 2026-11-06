"""Request-scoped function names and validation at the model boundary."""
from copy import deepcopy
import hashlib
import re

from jsonschema import Draft202012Validator, ValidationError
from jsonschema.exceptions import SchemaError


_VALID_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")


class InvalidToolSchema(ValueError):
    pass


def valid_provider_name(name: object) -> bool:
    return isinstance(name, str) and _VALID_NAME.fullmatch(name) is not None


def provider_name(tool_id: str) -> str:
    if valid_provider_name(tool_id):
        return tool_id
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", tool_id)[:43]
    digest = hashlib.sha256(tool_id.encode()).hexdigest()[:16]
    return f"ark_{stem}_{digest}"


class ProviderTools:
    def __init__(self, definitions: list[dict]):
        self.schemas: list[dict] = []
        self._tools: dict[str, tuple[str, Draft202012Validator]] = {}
        for definition in definitions:
            try:
                function = deepcopy(definition["function"])
                tool_id = function["name"]
                parameters = function["parameters"]
                if (
                    definition["type"] != "function"
                    or not isinstance(tool_id, str) or not tool_id
                    or not isinstance(parameters, dict) or parameters.get("type") != "object"
                    or not isinstance(parameters.get("properties", {}), dict)
                    or not set(parameters.get("required", ())) <= parameters.get("properties", {}).keys()
                    or not isinstance(function.get("description", ""), str)
                ):
                    raise ValueError("Expected a named function with object parameters")
                parameters.setdefault("additionalProperties", False)
                Draft202012Validator.check_schema(parameters)
            except (KeyError, TypeError, ValueError, SchemaError) as exc:
                raise InvalidToolSchema("Invalid registered function schema") from exc
            alias = provider_name(tool_id)
            if not valid_provider_name(alias) or alias in self._tools:
                raise InvalidToolSchema(f"Duplicate or invalid provider function name for {tool_id}")
            function["name"] = alias
            self._tools[alias] = (tool_id, Draft202012Validator(parameters))
            self.schemas.append({"type": "function", "function": function})

    def resolve(self, name: object, arguments: object) -> str | None:
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return None
        entry = self._tools.get(name)
        if entry is None:
            return None
        tool_id, validator = entry
        try:
            validator.validate(arguments)
        except (ValidationError, RecursionError):
            return None
        return tool_id
