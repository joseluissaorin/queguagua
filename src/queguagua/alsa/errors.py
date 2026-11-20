"""Typed errors. Each carries the CLI exit code it maps to.

Messages never contain cookies, passwords, card data or request bodies. When ALSA explains a refusal in
its own words (e.g. "Contraseña incorrecta.") that short text is passed on as `alsa_message`.
"""

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_PAYMENT = 4
EXIT_BLOCKED = 5
EXIT_SHAPE = 7


class AlsaError(Exception):
    exit_code = 1
    kind = "internal"

    def __init__(self, message: str, *, status: int | None = None, alsa_message: str | None = None,
                 transient: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.alsa_message = alsa_message
        self.transient = transient  # what failed, when another try may work; not in the output
        self.details = details or {}
        self.retries: list[dict] = []

    def to_dict(self) -> dict:
        out: dict = {"type": self.kind, "message": self.message, "exit_code": self.exit_code}
        if self.status is not None:
            out["http_status"] = self.status
        if self.alsa_message:
            out["alsa_message"] = self.alsa_message
        if self.details:
            out.update(self.details)
        if self.retries:
            out["retries"] = self.retries
        return out


class UsageError(AlsaError):
    """Bad input: an unknown stop, a malformed date, a journey or seat that doesn't exist, or a request ALSA
    rejected as invalid (a promo code it doesn't accept, a wrong Abono Único security code...)."""

    exit_code = EXIT_USAGE
    kind = "usage"


class AuthError(AlsaError):
    """Login failed or is needed: wrong password, no stored credentials, an expired Alsa Plus session."""

    exit_code = EXIT_AUTH
    kind = "auth"


class PaymentError(AlsaError):
    """The payment didn't go through, was cancelled, or its outcome is unknown."""

    exit_code = EXIT_PAYMENT
    kind = "payment"


class BlockedError(AlsaError):
    """403/429, an Incapsula challenge, a reCAPTCHA or a queue-it waiting room: stop, never retried."""

    exit_code = EXIT_BLOCKED
    kind = "blocked"


class UpstreamError(BlockedError):
    """ALSA 5xx, timeout or dropped connection after retries."""

    kind = "upstream_unavailable"


class ApiShapeError(AlsaError):
    """Unexpected status or page shape: ALSA's website probably changed."""

    exit_code = EXIT_SHAPE
    kind = "api_changed"

    def to_dict(self) -> dict:
        out = super().to_dict()
        out["hint"] = "ALSA's website may have changed; re-capture the request and update the CLI."
        return out
