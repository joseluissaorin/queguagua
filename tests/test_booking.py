import pytest

from queguagua.alsa import booking
from queguagua.alsa.errors import UsageError


def _co(payments, step3_extra=None):
    co = booking.Checkout(client=None, request=None)
    co.step3 = {"jsonCartAndPayments": {"cart": {"totalAmount": 25.53}, "paymentsType": payments,
                                        "creditCardTokenInfo": {"creditCardNumber": "XXXXXXXXXXXX4242",
                                                                "creditCardType": "MasterCard", "provider": "OGONE"}},
                **(step3_extra or {})}
    co.cart = co.step3["jsonCartAndPayments"]["cart"]
    return co


PAYMENTS = [
    {"paymentMethod": "BPPoints", "id": "998", "paymentCode": "6", "onlyThisTypePay": False, "money": 22.58, "cashPoints": 2.95},
    {"paymentMethod": "CreditCard", "id": "8", "paymentCode": "8", "onlyThisTypePay": True, "money": 25.53},
    {"paymentMethod": "PayPal", "id": "27", "paymentCode": "27", "onlyThisTypePay": True, "money": 25.53},
]


def test_saved_card_uses_the_token():
    pd = _co(PAYMENTS).payment_data("saved-card")
    assert pd["mainPaymentMethodId"] == "8" and pd["useCreditCardToken"] is True
    assert pd["supplementaryPaymentMethodId"] == ""


def test_points_with_money_go_main_points_supplementary_money():
    pd = _co(PAYMENTS).payment_data("points+saved-card")
    assert pd["mainPaymentMethodId"] == "998" and pd["supplementaryPaymentMethodId"] == "8"
    assert pd["useCreditCardToken"] is True


def test_points_alone_must_cover_the_total():
    with pytest.raises(UsageError):
        _co(PAYMENTS).payment_data("points")


def test_unknown_method_lists_offered():
    with pytest.raises(UsageError) as e:
        _co(PAYMENTS).payment_data("bizum")
    assert "PayPal" in e.value.details["offered"]


def test_free_prefers_the_preselected_method():
    free = [{"paymentMethod": "CashCard", "id": "2", "paymentCode": "2", "freeOfCharge": True},
            {"paymentMethod": "CreditCard", "id": "8", "paymentCode": "8", "freeOfCharge": True}]
    co = _co(free, {"PAYMENTMETHOD_PRESELECT_VALUE_STEP3": 8})
    co.cart = {"totalAmount": 0.0}
    assert co.payment_data("free")["mainPaymentMethodId"] == "8"


def test_saved_card_summary_hides_the_number():
    assert _co(PAYMENTS).saved_card() == {"type": "MasterCard", "last4": "4242", "provider": "OGONE"}


def test_passenger_parsing():
    p = booking.PassengerInfo.parse("Ana;García López;12345678Z;familia-general")
    assert (p.name, p.surname, p.document, p.document_type, p.discount) == ("Ana", "García López", "12345678Z", 1, "20")
    assert booking.PassengerInfo.parse("Jo;Doe;X1234567L;nie").document_type == 2
    with pytest.raises(UsageError):
        booking.PassengerInfo.parse("Jo;Doe;NOTADNI")
    assert booking.PassengerInfo.parse("Jo;Doe;AB123456;passport").document_type == 0  # ALSA's "otro documento"
    baby = booking.PassengerInfo.parse("Bebé;Doe")
    assert baby.document == "" and "document" not in baby.personal_info()
