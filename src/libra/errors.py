from __future__ import annotations

class ProviderError(RuntimeError):
    """A provider call failed — network, timeout, or a malformed response
    the provider itself returned. Distinct from IntentValidationError,
    which means the provider answered fine but the answer doesn't
    validate as an Intent."""


