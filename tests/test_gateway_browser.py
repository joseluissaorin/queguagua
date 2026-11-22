"""The payment hand-over in a real Chrome, with the network faked: what failed on 22 Nov 2026 can't come back.

That day the browser sat on a blank alsa.es page for minutes, with the seat held: the CLI slept with
`time.sleep` while the page waited on one of our routes, and ALSA's page only submits its form once its
58 scripts have loaded. Here one script never answers, and the payment still has to go through.

Needs Playwright and Google Chrome; skipped without them.
"""

from contextlib import contextmanager

import httpx
import pytest

pw = pytest.importorskip("playwright.sync_api")
_real_playwright = pw.sync_playwright

from queguagua.alsa import gateway  # noqa: E402
from queguagua.alsa.errors import PaymentError  # noqa: E402

PAGE = "https://www.alsa.es/checkout?p_p_id=X&_X_javax.portlet.action=%2FProcessPaymentAction&p_auth=abc"
ACTION = ("https://methodurl.psp-solutions.com/3ds-method-redirection/id/MasterCard"
          "?methodUrl=https%3A%2F%2Facs.example%2F3dsMethod&amp;threeDSMethodData=y")
BACK = "https://www.alsa.es/checkout?p_p_id=X&_X_mvcRenderCommandName=%2FWorldlineReturnRender"
# ALSA's hand-over page, as it comes: a script in <head> that blocks the parser, and the form submitted on
# jQuery's document-ready (jQuery never arrives either).
HANDOVER = f"""<!doctype html><html><head>
<script src="https://try.abtasty.com/never.js"></script>
<script src="https://estaticos.alsa.es/combo?jquery.js"></script>
</head><body><strong>Está siendo redireccionado a la plataforma de pago...</strong>
<form id="envio" name="envio" method="get" action="{ACTION}" data-test-id="paymentRedirectForm"></form>
<script>var sends = 0; function redirect(){{ sends++; document.envio.submit(); }}
$(document).ready(function() {{ if (sends < 1) {{ redirect(); }} }});</script>
</body></html>"""
CONFIRMED = """<html><body><script>params.purchase["success"] = '{"ticketLocator": "1abcdef"}';</script>
<p>Compra realizada</p></body></html>"""
REFUSED = "<html><body><p>Atención: Transacción cancelada o rechazada</p><a>Volver</a></body></html>"


class _Client:
    def __init__(self):
        self.http = httpx.Client()

    def cookies_for_browser(self):
        return [{"name": "JSESSIONID", "value": "s", "domain": ".alsa.es", "path": "/"}]


@contextmanager
def _chrome(network):
    """sync_playwright as gateway uses it, headless, with `network` answering every request."""
    with _real_playwright() as p:
        class Chromium:
            def launch(self, **kw):
                try:
                    b = p.chromium.launch(**{**kw, "headless": True})
                except Exception as e:  # noqa: BLE001
                    pytest.skip(f"no Chrome to drive: {type(e).__name__}")
                new_context = b.new_context

                def context(**k):
                    ctx = new_context(**k)
                    ctx.route("**/*", network)
                    return ctx

                b.new_context = context
                return b

        class P:
            chromium = Chromium()

        yield P()


def _pay(monkeypatch, network, **kw):
    monkeypatch.setattr(pw, "sync_playwright", lambda: _chrome(network))
    return gateway.complete(_Client(), ACTION.replace("&amp;", "&"), "GET", method="saved-card", headless=True,
                            html=HANDOVER, page_url=PAGE, **kw)


def _network(bank_page: str | None, seen: list):
    """The payment platform answers with `bank_page`'s outcome (None: it never answers); slow scripts never do."""

    def handle(route):
        u = route.request.url
        seen.append(u)
        if u.startswith("https://methodurl.psp-solutions.com/"):
            if bank_page is None:
                return  # never answers
            route.fulfill(status=200, content_type="text/html",
                          body=f"<script>location.href = {BACK!r}</script>")
        elif u == BACK:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=bank_page)
        elif "abtasty" in u or "estaticos.alsa.es" in u:
            return  # a script that hangs, as third-party scripts do
        else:
            route.abort()

    return handle


def test_the_payment_goes_through_even_if_alsas_scripts_hang(monkeypatch):
    monkeypatch.setattr(gateway, "_TIMEOUT_S", 30)
    seen = []
    res = _pay(monkeypatch, _network(CONFIRMED, seen))
    assert res["status"] == "confirmed" and res["locator"] == "1abcdef"
    to_bank = [u for u in seen if "psp-solutions" in u]
    # as from alsa.es: a GET form drops the query string of its action
    assert to_bank == ["https://methodurl.psp-solutions.com/3ds-method-redirection/id/MasterCard?"]
    assert not any("abtasty" in u for u in seen)  # only the form is served, not the portal around it


def test_a_refusal_comes_back_as_a_payment_error(monkeypatch):
    monkeypatch.setattr(gateway, "_TIMEOUT_S", 30)
    with pytest.raises(PaymentError) as e:
        _pay(monkeypatch, _network(REFUSED, []))
    assert e.value.alsa_message == "Transacción cancelada o rechazada"


def test_a_payment_that_never_leaves_alsa_stops_and_says_so(monkeypatch):
    monkeypatch.setattr(gateway, "_TIMEOUT_S", 60)
    monkeypatch.setattr(gateway, "_DEPART_S", 3)
    with pytest.raises(PaymentError) as e:
        _pay(monkeypatch, _network(None, []))
    assert e.value.details.get("status") == "not_started"
    assert "never left ALSA" in str(e.value)
