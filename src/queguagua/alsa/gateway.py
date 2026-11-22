"""Finish a payment in a real browser, then read ALSA's confirmation.

ProcessPaymentAction answers with a page whose script submits a form (`id="envio"`) to the payment
platform:
- a new card, PayPal, Bizum...: Worldline's hosted checkout
  (https://payment.direct.worldline-solutions.com/hostedcheckout/Payment/Form/<id>);
- the saved card: no checkout page at all. ALSA charges the token and the form goes to EMV 3-D Secure
  (https://methodurl.psp-solutions.com/3ds-method-redirection/<id>/<brand>), which may finish on its own
  (frictionless) or ask the bank (a code, or approving it in the bank's app).
Card data, a CVC and the bank's 3-D Secure step all happen there, so they need a browser and you.

The browser carries on from ALSA's page, at the URL it came from, so the form is submitted as on alsa.es
(a GET form drops the query string of its action; a POST form carries its hidden fields). Opening the
form's action by hand is not the same request. Of that page we serve only the form: the whole page is
the portal (58 scripts, A/B testing and analytics among them) and submits on jQuery's document-ready, so
one slow script used to stall the payment before it started.

In the end the platform sends the browser back to ALSA (worldlineReturnAction, then a render that checks
the payment) under *our* session: the browser gets the CLI's cookies, and we read the confirmation or the
refusal from that page. Nothing about the card ever reaches the CLI.

Two things keep it from hanging (22 Nov 2026: it sat on a blank page with the user's seat held):
- the wait goes through Playwright (`wait_for_timeout`), never `time.sleep`: sync Playwright only handles
  events and routed requests inside its own calls, and the page was waiting on us;
- if the hand-over page hasn't moved after `_DEPART_S`, we stop and say the bank's check never started.

Needs the optional extra: `uv tool install 'queguagua[checkout]'` (Playwright drives your installed Chrome;
no browser download).
"""

import re
import sys
import time
from urllib.parse import unquote, urlsplit

from . import confirmation, pageparams
from .client import AlsaClient
from .errors import PaymentError, UsageError

_TIMEOUT_S = 15 * 60
_DEPART_S = 90  # the hand-over page must leave for the payment platform within this
_SETTLE_S = 120  # back on alsa.es: how long to wait for a locator or a refusal before reading the page as is
# ALSA's return page shows a refusal as «Atención: Transacción cancelada o rechazada».
_REFUSED = re.compile(r"Transacci[oó]n cancelada o rechazada")
_NOTICE = re.compile(r"Atenci[oó]n:\s*([^\n]{3,200})")
_CHECKING = ("worldlineReturnAction", "WorldlineReturnRender")
_FORM = re.compile(r'<form\b[^>]*\bid="envio"[^>]*>.*?</form>', re.S | re.I)


def _say(msg: str) -> None:
    print(f"alsa: {msg}", file=sys.stderr)


def _is_alsa(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    return host == "alsa.es" or host.endswith(".alsa.es")


def _same(a: str, b: str) -> bool:
    """The same URL, whether or not the browser re-encoded it."""
    return a == b or unquote(a) == unquote(b)


def _handover(html: str) -> str:
    """What ALSA's hand-over page does, and nothing else: its form, submitted at once."""
    m = _FORM.search(html)
    if not m:
        return html
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><title>ALSA</title></head><body>'
            f'{m.group(0)}<script>document.getElementById("envio").submit()</script></body></html>')


def _outcome(html: str, url: str, text: str) -> tuple[str, str | None]:
    """("done" | "refused" | "pending", ALSA's message) for a page of alsa.es after the payment platform."""
    if "RuntimeErrorRender" in url:
        return "refused", None
    params = pageparams.parse(html)
    pur = params.get("purchase", {})
    if confirmation.find_locator(pur):
        return "done", None  # a locator wins over any notice on the page
    err = params.get("", {}).get("errorMessageKey") or pur.get("errorMessageKey")
    if err:
        return "refused", str(err)
    m = _REFUSED.search(text)
    if m:
        return "refused", m.group(0)
    m = _NOTICE.search(text)
    if m and any(k in url for k in _CHECKING):
        return "refused", m.group(1).strip()
    return "pending", None


def _drive(b, client: AlsaClient, target: str, served: str | None) -> dict:
    """Open the payment, follow it back to alsa.es and read the answer there."""
    ctx = b.new_context(locale="es-ES")
    try:
        ctx.add_cookies(client.cookies_for_browser())
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        st = {"closed": False, "moved": False, "host": None}
        page.on("close", lambda *_: st.__setitem__("closed", True))

        def hop(frame) -> None:
            if frame != page.main_frame:
                return
            u = frame.url
            if urlsplit(u).scheme not in ("http", "https"):
                return
            host = urlsplit(u).hostname
            if host != st["host"]:
                st["host"] = host
                _say(f"payment page at {host}")  # hosts only: ALSA's paths carry the session token
            if not _same(u, target):
                st["moved"] = True  # the hand-over (or the checkout we opened) has been left

        page.on("framenavigated", hop)

        def match(u: str) -> bool:
            return _same(u, target)

        def serve(route) -> None:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=served)

        if served is not None:
            page.route(match, serve, times=1)
        try:
            page.goto(target, wait_until="commit")
        except Exception:
            pass  # the hand-over may already be leaving for the payment platform
        if served is not None:
            try:
                page.unroute(match, serve)
            except Exception:
                pass

        start = time.time()
        out = {"state": "pending", "refusal": None, "html": None, "url": None, "moved": False, "stalled": False}
        back_since = None  # when the browser came back to alsa.es from the payment platform
        while time.time() - start < _TIMEOUT_S and not st["closed"]:
            # Not time.sleep: sync Playwright only handles events and routed requests inside its own calls.
            try:
                page.wait_for_timeout(1000)
                cur = page.url
            except Exception:
                break
            if not st["moved"]:
                if _is_alsa(cur) and time.time() - start > _DEPART_S:
                    out["stalled"] = True
                    break
                continue
            if not _is_alsa(cur):
                back_since = None
                continue
            back_since = back_since or time.time()
            try:
                now_html, text = page.content(), page.inner_text("body")
            except Exception:
                continue  # navigating
            state, refusal = _outcome(now_html, cur, text)
            if state != "pending" or time.time() - back_since > _SETTLE_S:
                out.update(state=state, refusal=refusal, html=now_html, url=cur)
                break
        out["moved"] = st["moved"]
        return out
    finally:
        # Bring the browser's cookies back so later commands keep the same session.
        try:
            for c in ctx.cookies():
                if c["domain"].endswith("alsa.es"):
                    client.http.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
        except Exception:
            pass


def complete(client: AlsaClient, url: str, http_method: str, *, browser: str = "chrome", headless: bool = False,
             method: str = "card", html: str | None = None, page_url: str | None = None) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise UsageError(
            "paying in the browser needs the checkout extra: uv tool install 'queguagua[checkout]' "
            "(nothing was charged; your booking is held for a few minutes)",
            details={"gateway_url": url}) from None

    if method == "saved-card":
        what = "if your bank asks, confirm the payment there or in its app"
    else:
        what = f"pay with {method} there"
    _say(f"opening the payment page in {browser}; {what}.")
    if html and page_url:
        target, served = page_url, _handover(html)
    else:
        target, served = url, None
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome" if browser == "chrome" else browser, headless=headless)
        except Exception:
            raise UsageError("couldn't start Google Chrome for the payment page") from None
        try:
            out = _drive(b, client, target, served)
        finally:
            try:
                b.close()
            except Exception:
                pass
    if out["stalled"]:
        raise PaymentError(
            "the payment page never left ALSA for the payment platform, so your bank's check never started "
            "and nothing should be charged. ALSA may hold the seat for a few minutes; check `alsa tickets` "
            "before trying again", details={"status": "not_started"})
    if out["state"] == "refused":
        raise PaymentError("the payment was cancelled or refused; nothing was bought", alsa_message=out["refusal"])
    if out["html"]:
        res = confirmation.parse_result(client, out["html"], out["url"])
        res["paid_via"] = "worldline"
        return res
    if out["moved"]:
        raise PaymentError("the payment page returned to ALSA but no confirmation was shown; check your email "
                           "or `alsa tickets` before trying again")
    raise PaymentError("the payment window was closed or timed out before ALSA confirmed; if you approved the "
                       "payment, check your email or `alsa tickets` before trying again",
                       details={"status": "unconfirmed"})
