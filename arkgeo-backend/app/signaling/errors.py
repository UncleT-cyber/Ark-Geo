"""Signaling-layer exceptions mapped to HTTP statuses by the endpoint layer."""


class SignalingError(Exception):
    """Base class for signaling failures."""

    status_code = 500
    code = "signaling_error"

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or self.code)
        self.detail = detail or self.code


class BackendNotProvisioned(SignalingError):
    """The requested backend exists but its testbed is not configured/connected."""

    status_code = 503
    code = "backend_not_provisioned"


class BackendUnavailable(SignalingError):
    """The configured testbed is unreachable or errored mid-operation."""

    status_code = 502
    code = "backend_unavailable"


class OperatorNotAuthorized(SignalingError):
    """Certified personnel have no valid operator-authorization token."""

    status_code = 403
    code = "operator_not_authorized"


class TargetValidationError(SignalingError):
    """The requested target failed validation (bad E.164, missing IMSI, ...)."""

    status_code = 422
    code = "target_validation_error"
