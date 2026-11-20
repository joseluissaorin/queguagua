"""Alsa Plus login over ALSA's own login resources.

    POST loginPasswordResource {"identifier", "password"}
      -> {"status": "success"} | {"status": "requires2fa", destination, verificationChannel, ...}
         | {"status": "error", "errorMessage": "Contraseña incorrecta."}
    POST checkLoginTwoStepVerificationCodeResource {"userVerificationCode", "verificationChannel"}
    POST sendLoginTwoStepVerificationCodeResource {"verificationChannel"}       (resend)

The login lives in the server session (cookies), which the client keeps in the cache dir. A session ALSA
has dropped is noticed by `current_user()` returning None, and `ensure_login()` signs in again with the
stored credentials. Google sign-in can't be done from a terminal: set a password on ALSA ("Olvidé mi
contraseña") and use that.
"""

import time
from typing import Any

from . import cachefile, config, pageparams, secrets
from .client import AlsaClient
from .errors import ApiShapeError, AuthError, UsageError

_PENDING = "login-pending.json"


def _login_urls(client: AlsaClient) -> dict[str, str]:
    r = client.page("/", what="home page")
    auth = pageparams.parse(r.text).get("alsaplusAuth", {})
    if not auth.get("loginPasswordResourceURL"):
        raise ApiShapeError("no login endpoint on ALSA's home page")
    return auth


def _post(client: AlsaClient, url: str, body: dict, what: str) -> dict:
    r = client.resource("/", "", what, url=url, json_body=body, retry=False)
    try:
        payload = r.json()
    except ValueError:
        raise ApiShapeError(f"{what} didn't return JSON", status=r.status_code) from None
    if not isinstance(payload, dict):
        raise ApiShapeError(f"{what} changed shape")
    return payload


def user_from_page(params: dict) -> dict | None:
    for ns in ("alsaplusAuth", "journeySearch", "purchase", "alsaplusLoyalty"):
        u = params.get(ns, {}).get("jsonBusplusUser")
        if isinstance(u, dict) and u:
            return u
    return None


def current_user(client: AlsaClient) -> dict | None:
    r = client.page("/", what="home page")
    return user_from_page(pageparams.parse(r.text))


def public_user(u: dict, *, purse: float | None = None) -> dict:
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    out: dict[str, Any] = {
        "logged_in": True,
        "name": " ".join(x for x in [u.get("name"), u.get("surnames")] if x) or None,
        "email": u.get("email") or None,
        "document": u.get("documentNumber") or None,
        "document_type": u.get("documentType") or None,
        "level": u.get("alsaplusLevelName") or None,
        "points": u.get("points"),
        "points_value_eur": num(u.get("cashPoints")),
        "ecokms": u.get("ecokms"),
        "two_factor": {"sms": bool(u.get("smsDoubleFactor")), "email": bool(u.get("emailDoubleFactor"))},
        "large_family_card": bool(u.get("familyCardNumber")),
        "employee": bool(u.get("actsAsEmployee")),
    }
    if purse is not None:
        out["purse_eur"] = purse
    return out


def login(client: AlsaClient, user: str, password: str) -> dict:
    urls = _login_urls(client)
    payload = _post(client, urls["loginPasswordResourceURL"], {"identifier": user, "password": password},
                    "loginPasswordResource")
    status = payload.get("status")
    if status == "success":
        cachefile.remove(config.cache_dir() / _PENDING)
        return {"status": "logged_in"}
    if status == "requires2fa":
        channel = payload.get("verificationChannel") or payload.get("defaultChannel") or "email"
        cachefile.write_json(config.cache_dir() / _PENDING, {
            "at": time.time(), "channel": channel,
            "check_url": urls.get("checkLoginTwoStepVerificationCodeResourceURL"),
            "resend_url": urls.get("sendLoginTwoStepVerificationCodeResourceURL"),
        })
        return {"status": "code_required", "channel": channel,
                "sent_to": payload.get("destination") or payload.get("maskedDestination"),
                "next": "Run `alsa login --code NNNNNN` with the code ALSA just sent."}
    raise AuthError("ALSA refused the login", alsa_message=payload.get("errorMessage"))


def submit_code(client: AlsaClient, code: str) -> dict:
    pending = cachefile.read_json(config.cache_dir() / _PENDING)
    if not isinstance(pending, dict) or not pending.get("check_url"):
        raise UsageError("no login is waiting for a code; run `alsa login` first")
    payload = _post(client, pending["check_url"], {"userVerificationCode": code.strip(),
                                                   "verificationChannel": pending.get("channel", "email")},
                    "checkLoginTwoStepVerificationCodeResource")
    if payload.get("verificationCodeVerified") and payload.get("loginCompleted", True):
        cachefile.remove(config.cache_dir() / _PENDING)
        return {"status": "logged_in"}
    if payload.get("attemptsExhausted"):
        cachefile.remove(config.cache_dir() / _PENDING)
        raise AuthError("too many wrong codes; run `alsa login` again")
    raise AuthError("ALSA didn't accept that code", details={"remaining_attempts": payload.get("remainingAttempts")})


def logout(client: AlsaClient) -> dict:
    client.forget_session()
    return {"status": "logged_out"}


def ensure_login(client: AlsaClient, *, required: bool = True) -> dict | None:
    """The logged-in user, signing in again with the stored credentials if ALSA dropped the session."""
    u = current_user(client)
    if u:
        return u
    user, password, _src = secrets.credentials()
    if not (user and password):
        if required:
            raise AuthError("this needs an Alsa Plus login: run `alsa login` (or set ALSA_USER/ALSA_PASSWORD)")
        return None
    res = login(client, user, password)
    if res["status"] != "logged_in":
        raise AuthError("ALSA asks for a verification code: run `alsa login` and then `alsa login --code`",
                        details=res)
    u = current_user(client)
    if not u and required:
        raise AuthError("logged in, but ALSA's pages don't show the account; try `alsa login` again")
    return u
