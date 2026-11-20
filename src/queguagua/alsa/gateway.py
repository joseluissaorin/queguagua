"""Finish a payment on Worldline's hosted checkout in a real browser, then read ALSA's confirmation.

ALSA's ProcessPaymentAction answers with a form that posts to
https://payment.direct.worldline-solutions.com/hostedcheckout/Payment/Form/<id>. Card data, the CVC of a
saved card, PayPal, Bizum and the bank's 3-D Secure step all happen there, so they need a browser and you.
When it's done Worldline sends the browser back to
https://www.alsa.es/checkout/-/purchaseespaniaworldlinecheckout/<p_auth>/worldlineReturnAction?RETURNMAC=..&hostedCheckoutId=..
which belongs to *our* session. So we open installed Google Chrome through Playwright with the CLI's
cookies loaded, let ALSA's own return page run, and read the confirmation from it. Nothing about the card
ever reaches the CLI.

Needs the optional extra: `uv tool install 'queguagua[checkout]'` (Playwright drives your installed Chrome;
no browser download).
"""

import sys
import time

from . import confirmation
from .client import AlsaClient
from .errors import PaymentError, UsageError

_TIMEOUT_S = 15 * 60


def complete(client: AlsaClient, url: str, http_method: str, *, browser: str = "chrome", headless: bool = False,
             method: str = "card") -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise UsageError(
            "paying through Worldline's page needs the checkout extra: uv tool install 'queguagua[checkout]' "
            "(nothing was charged; your booking is held for a few minutes)",
            details={"gateway_url": url}) from None

    what = "check the CVC or 3-D Secure" if method == "saved-card" else f"pay with {method}"
    print(f"alsa: opening Worldline's payment page in {browser}; {what} there.", file=sys.stderr)
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome" if browser == "chrome" else browser, headless=headless)
        except Exception:
            raise UsageError("couldn't start Google Chrome for the payment page") from None
        ctx = b.new_context(locale="es-ES")
        ctx.add_cookies(client.cookies_for_browser())
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        page.goto(url)  # Worldline's hosted checkout answers GET as well as the form POST ALSA builds
        start = time.time()
        returned = False
        final_html, final_url = None, None
        closed = {"v": False}
        page.on("close", lambda *_: closed.__setitem__("v", True))
        while time.time() - start < _TIMEOUT_S and not closed["v"]:
            try:
                cur = page.url
            except Exception:
                break
            if "alsa.es" in cur:
                returned = True
                # ALSA's return page checks the payment (WorldlineReturnResource), then shows the result.
                if "worldlineReturnAction" in cur or "WorldlineReturnRender" in cur:
                    time.sleep(1)
                    continue
                try:
                    page.wait_for_load_state("networkidle", timeout=60_000)
                    final_html, final_url = page.content(), page.url
                except Exception:
                    pass
                break
            time.sleep(1)
        # Bring the browser's cookies back so later commands keep the same session.
        try:
            for c in ctx.cookies():
                if c["domain"].endswith("alsa.es"):
                    client.http.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
        except Exception:
            pass
        try:
            b.close()
        except Exception:
            pass
    if final_url and "RuntimeErrorRender" in final_url:
        raise PaymentError("the payment was cancelled or refused (ALSA shows its error page); nothing was bought")
    if final_html:
        res = confirmation.parse_result(client, final_html, final_url)
        res["paid_via"] = "worldline"
        return res
    if returned:
        raise PaymentError("the payment page returned to ALSA but no confirmation was shown; check your email "
                           "or `alsa tickets` before trying again")
    raise PaymentError("the payment window was closed or timed out before ALSA confirmed; if you approved the "
                       "payment, check your email or `alsa tickets` before trying again",
                       details={"status": "unconfirmed"})
