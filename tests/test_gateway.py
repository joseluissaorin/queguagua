"""Paying in the browser: what ALSA hands over, how its answer is read, packages with the Abono, and one
command per ALSA session."""

import httpx
import pytest

from queguagua.alsa import booking, config, gateway
from queguagua.alsa import search as search_mod
from queguagua.alsa.client import AlsaClient

CHECK = "https://www.alsa.es/checkout?p_p_id=X&_X_mvcRenderCommandName=%2FWorldlineReturnRender"
STEP4 = "https://www.alsa.es/checkout?p_p_id=X&p_p_lifecycle=0"


def test_a_refusal_is_read_from_the_page_that_checks_the_payment():
    text = "Atención: Transacción cancelada o rechazada\nVolver"
    assert gateway._outcome("<html></html>", CHECK, text) == ("refused", "Transacción cancelada o rechazada")
    assert gateway._outcome("<html></html>", CHECK, "Atención: Pago denegado por tu banco") == (
        "refused", "Pago denegado por tu banco")


def test_the_checking_page_without_an_answer_is_still_pending():
    assert gateway._outcome("<html></html>", CHECK, "Estamos comprobando tu pago") == ("pending", None)


def test_a_locator_wins_over_any_notice():
    html = """<script>params.purchase["success"] = '{"ticketLocator": "1abcdef"}';</script>"""
    text = "Atención: recuerda llevar tu documento de identidad"
    assert gateway._outcome(html, STEP4, text) == ("done", None)
    assert gateway._outcome("<html></html>", STEP4, text) == ("pending", None)  # a notice elsewhere isn't a refusal


def test_alsa_error_pages_are_refusals():
    assert gateway._outcome("", "https://www.alsa.es/x?RuntimeErrorRender", "")[0] == "refused"
    html = """<script>params["errorMessageKey"] = "payment.refused";</script>"""
    assert gateway._outcome(html, STEP4, "") == ("refused", "payment.refused")


class _Client:
    def __init__(self, response):
        self.response = response

    def action(self, *a, **k):
        return self.response


def test_the_payment_form_comes_back_with_its_page():
    page = "https://www.alsa.es/checkout?p_p_id=X&p_auth=abc"
    form = ('<form id="envio" name="envio" method="get" action="https://methodurl.psp-solutions.com/'
            '3ds-method-redirection/id/MasterCard?methodUrl=x&amp;threeDSMethodData=y"></form>'
            "<script>document.envio.submit()</script>")
    r = httpx.Response(200, text=form, headers={"content-type": "text/html"}, request=httpx.Request("POST", page))
    co = booking.Checkout(client=_Client(r), request=None)
    res = co.process_payment([], booking.Contact(email="a@b.c", phone="600000000", pax_index=-1), {}, False)
    assert res["kind"] == "gateway"
    assert res["url"].endswith("MasterCard?methodUrl=x&threeDSMethodData=y")
    # the browser submits it from this page, as alsa.es would: the HTML and where it came from travel along
    assert res["html"] == form and res["page_url"] == page


@pytest.mark.parametrize("names", [
    [("1403", "Básica Abono Único"), ("1428", "Superflexible Abono Único")],
    [("45", "Básica"), ("1001", "Flexible"), ("624", "Superflexible")],
])
def test_package_aliases_work_with_and_without_the_abono(monkeypatch, names):
    pkgs = [{"id": i, "name": n, "available": True, "extra_price": float(k)} for k, (i, n) in enumerate(names)]
    monkeypatch.setattr(search_mod, "package_fares", lambda *a: [dict(p) for p in pkgs])
    co = booking.Checkout(client=None, request=None)
    assert co._pick_package({"index": 0}, "superflexible", "I")["name"].startswith("Superflexible")
    assert co._pick_package({"index": 0}, "basica", "I")["name"].startswith("Básica")
    assert co._pick_package({"index": 0}, names[-1][1], "I")["id"] == names[-1][0]  # the full name still works
    if len(names) == 3:
        assert co._pick_package({"index": 0}, "flexible", "I")["id"] == "1001"  # not Superflexible


def test_one_command_per_alsa_session():
    fcntl = pytest.importorskip("fcntl")  # POSIX only; elsewhere the session is not locked
    path = config.cache_dir() / "session.lock"
    client = AlsaClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    other = open(path, "a")
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        client.close()
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)  # free once the first command ends
    finally:
        other.close()
