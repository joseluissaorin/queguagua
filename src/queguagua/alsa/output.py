"""JSON rendering for the CLI's output and error payloads (strict JSON: no NaN/Infinity)."""

import json
import math
from typing import Any

from .errors import AlsaError


def _clean(value: Any) -> Any:
    """ALSA sometimes sends NaN (e.g. localDistributionAmount); strict JSON can't carry it."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def render(payload: Any) -> str:
    return json.dumps(_clean(payload), ensure_ascii=False, indent=2, allow_nan=False)


def render_line(payload: Any) -> str:
    return json.dumps(_clean(payload), ensure_ascii=False, allow_nan=False)


def render_error(err: AlsaError) -> str:
    return json.dumps({"error": _clean(err.to_dict())}, ensure_ascii=False, allow_nan=False)
