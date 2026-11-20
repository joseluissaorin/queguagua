"""Read what ALSA's Liferay pages embed for their scripts.

Every page carries its state and its endpoints as JavaScript assignments such as

    params.purchase["jsonCart"] = '{"outwardJourney": ...}';
    params.journeySearch["getOriginsURL"] = 'https://www.alsa.es/home?p_p_id=...';
    params["tabUUID"] = "6972ea9c-...";

`parse()` returns them as {namespace: {key: value}} (top-level ones under ""), with JSON strings decoded.
"""

import json
import re
from typing import Any

_ASSIGN = re.compile(
    r"""params(?:\.(\w+))?\[\s*["'](\w+)["']\s*\]\s*=\s*(?:'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)")""",
    re.S,
)
_AUTH_TOKEN = re.compile(r"Liferay\.authToken\s*=\s*'([A-Za-z0-9]{4,32})'")
_P_AUTH = re.compile(r"[?&]p_auth=([A-Za-z0-9]{4,32})")
_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def js_unescape(s: str) -> str:
    """Undo JavaScript string-literal escapes (\\', \\", \\\\, \\n, \\xHH, \\uHHHH)."""
    if "\\" not in s:
        return s
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch != "\\" or i + 1 >= n:
            out.append(ch)
            i += 1
            continue
        nxt = s[i + 1]
        if nxt == "x" and i + 3 < n + 1:
            try:
                out.append(chr(int(s[i + 2:i + 4], 16)))
                i += 4
                continue
            except ValueError:
                pass
        if nxt == "u":
            try:
                out.append(chr(int(s[i + 2:i + 6], 16)))
                i += 6
                continue
            except ValueError:
                pass
        out.append(_SIMPLE_ESCAPES.get(nxt, nxt))
        i += 2
    return "".join(out)


def _decode(raw: str) -> Any:
    text = js_unescape(raw)
    stripped = text.strip()
    if stripped[:1] in ("{", "[") or stripped in ("null", "true", "false"):
        try:
            return json.loads(stripped)
        except ValueError:
            return text
    return text


def parse(html: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for m in _ASSIGN.finditer(html):
        ns, key, single, double = m.groups()
        raw = single if single is not None else double
        out.setdefault(ns or "", {})[key] = _decode(raw or "")
    return out


def auth_token(html: str) -> str | None:
    """Liferay's CSRF token (`p_auth`), which every portlet action needs."""
    m = _AUTH_TOKEN.search(html) or _P_AUTH.search(html)
    return m.group(1) if m else None


def get(params: dict, ns: str, key: str, default: Any = None) -> Any:
    return params.get(ns, {}).get(key, default)
