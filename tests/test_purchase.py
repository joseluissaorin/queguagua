import json

from queguagua.alsa import booking, purchase


def test_expiry_formats():
    assert purchase._ddmmyyyy("31/12/2029") == "31/12/2029"
    assert purchase._ddmmyyyy("2029-12-31") == "31/12/2029"
    assert purchase._ddmmyyyy("Mon Dec 31 00:00:00 CET 2029") == "31/12/2029"
    assert purchase._ddmmyyyy(None) is None


def test_phone_split():
    assert purchase._split_phone("+34-600000000") == ("+34", "600000000")
    assert purchase._split_phone("600 000 000") == ("+34", "600000000")
    assert purchase._split_phone("+351 912 345 678") == ("+351", "912345678")


def test_account_methods():
    assert purchase.needs_account("saved-card") and purchase.needs_account("points+card")
    assert not purchase.needs_account("card") and not purchase.needs_account("bizum")


def test_cart_is_read_from_any_answer_shape():
    co = booking.Checkout(client=None, request=None)
    co._absorb({"jsonCart": json.dumps({"totalAmount": 57.35})})
    assert co.total() == 57.35
    co.step3 = {"x": 1}
    co._absorb({"jsonCartAndPayments": json.dumps({"cart": {"totalAmount": 58.35}, "paymentsType": []})})
    assert co.total() == 58.35 and co.payments["paymentsType"] == []
    co._absorb({"cart": {"totalAmount": 58.45}, "paymentsType": [{"id": "8"}]})
    assert co.total() == 58.45


def test_holder_from_account_strips_spaces():
    p = purchase._holder({"name": "Ana ", "surnames": "García López ", "documentNumber": "12345678Z", "documentType": "1"})
    assert (p.name, p.surname, p.document) == ("Ana", "García López", "12345678Z")
