"""Buying bonos and passes: the Abono Único, Bono Comparte (10 trips), monthly passes, regional bonos...

Every bono is sold by one portlet, `com_babel_alsa_vouchers_VouchersPortlet`, on several pages. The server
keeps the chosen product in the session, so the order matters:

    GET  /bonos/abono-unico            (or POST jsonGetVouchersList for a route)   -> the catalogue
    POST jsonGetVouchersDiscounts      idVoucherType, startDate                    -> large-family discounts
    POST jsonVouchersSelectDiscount    discountType=0|20|50                        (optional)
    POST getVouchersPaymentMethods     idVoucherType, startDate, end-date, selectedSubset -> final price + methods
    POST paymentProcessAction (form)   voucherSelected=<JSON> ...                  -> payment (Worldline) or done
"""

import json
from datetime import date
from typing import Any

from . import auth, config, pageparams
from .client import AlsaClient
from .errors import ApiShapeError, UsageError

V = "com_babel_alsa_vouchers_VouchersPortlet"
ROUTE_PAGE = "/bonos/compra-tu-bono"
AU_PAGE = "/bonos/abono-unico"
AU_TYPES = {"adult": "5626", "adulto": "5626", "young": "5627", "joven": "5627"}


def _norm(v: dict) -> dict:
    trips = v.get("voucherTripsNumber") or 0
    return {
        "type_id": str(v.get("voucherType")),
        "name": v.get("voucherName"),
        "family": v.get("digitalVoucherName"),
        "price": v.get("amount"),
        "trips": trips or None,
        "unlimited": not trips,
        "price_per_trip": v.get("unitaryPriceWithVoucher") or None,
        "price_per_trip_without": v.get("unitaryPrice") or None,
        "validity_days": int(v["validDays"]) if str(v.get("validDays") or "").isdigit() else None,
        "validity": v.get("validityVoucherText") or None,
        "start_from": v.get("minDateFrom") or None,
        "start_until": v.get("maxDateFrom") or None,
        "choose_start_date": bool(v.get("showValidityDateInput") or v.get("isUnifiedVoucher")),
        "service": v.get("serviceNameType"),
        "abono_unico": bool(v.get("isUnifiedVoucher")),
        "needs_ministry_code": bool(v.get("validateRegisterCode")),
        "ministry_code_prefix": v.get("promotionCode") or None,
        "birth_date_check": bool(v.get("validateBirthDateBonosRegionales") or v.get("validateBirthDateBonosMitma")),
        "passport_ok": bool(v.get("enablePassport")),
        "already_owned": v.get("info") == "2568",
        "deposit": v.get("depositAmount") or None,
        "observations": v.get("observations") or None,
        "_raw_index": v.get("_index"),
    }


def au_catalogue(client: AlsaClient) -> list[dict]:
    r = client.page(AU_PAGE, what="Abono Único page")
    vl = pageparams.parse(r.text).get("", {}).get("vouchersList")
    if not isinstance(vl, list):
        raise ApiShapeError("the Abono Único page has no product list")
    return [{**_norm(v), "_raw_index": i} for i, v in enumerate(vl)]


def route_catalogue(client: AlsaClient, origin_id: str, destination_id: str) -> list[dict]:
    client.page(ROUTE_PAGE, {"originId": origin_id, "destinationId": destination_id}, what="bonos page")
    payload = client.resource_json(ROUTE_PAGE, V, "jsonGetVouchersList", method="POST", params={
        "originId": origin_id, "destinationId": destination_id, "searchDate": "", "unifiedVouchers": "true",
        "voucherTours": "false", "vouchersFrequents": "true", "vouchersShareds": "true"})
    raw = payload.get("vouchersJson") if isinstance(payload, dict) else None
    items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    return [{**_norm(v), "_raw_index": i} for i, v in enumerate(items)]


def public(items: list[dict]) -> list[dict]:
    return [{k: v for k, v in it.items() if not k.startswith("_")} for it in items]


def _prices(client: AlsaClient, page: str, type_id: str, start: date, discount: str | None) -> dict:
    sd = config.alsa_date(start)
    discounts = client.resource(page, V, "jsonGetVouchersDiscounts", method="POST",
                                params={"idVoucherType": type_id, "startDate": sd, "end-date": ""})
    offered = []
    try:
        offered = [{"id": str(d.get("type") or d.get("discountType")), "name": d.get("name"),
                    "percent": d.get("percentage")} for d in discounts.json() or []]
    except ValueError:
        pass
    if discount is not None:
        client.resource(page, V, "jsonVouchersSelectDiscount", method="POST", params={"discountType": discount})
    pm = client.resource_json(page, V, "getVouchersPaymentMethods", method="POST", params={
        "idVoucherType": type_id, "startDate": sd, "end-date": "", "selectedSubset": ""})
    if not isinstance(pm, dict) or pm.get("error"):
        raise UsageError("ALSA didn't price that bono", alsa_message=(pm or {}).get("errorMessage"))
    return {"discounts": offered, "payments": pm}


def buy(client: AlsaClient, *, kind: str, origin: dict | None = None, destination: dict | None = None,
        start: date | None = None, holder: dict | None = None, birth_date: str | None = None,
        ministry_code: str | None = None, discount: str | None = None, pay: str = "saved-card",
        email: str | None = None, phone: str | None = None, confirm: bool = False,
        browser: str = "chrome") -> dict:
    """Buy the Abono Único (kind adult/young) or a route bono (kind = its type id or name)."""
    user = auth.ensure_login(client, required=False)
    if kind.lower() in AU_TYPES:
        page, items = AU_PAGE, au_catalogue(client)
        type_id = AU_TYPES[kind.lower()]
    else:
        if not (origin and destination):
            raise UsageError("a route bono needs FROM and TO")
        page, items = ROUTE_PAGE, route_catalogue(client, origin["id"], destination["id"])
        from .stations import fold

        match = [i for i in items if i["type_id"] == kind or fold(kind) in fold(i["name"] or "")]
        if not match:
            raise UsageError(f"no bono {kind!r} on that route", details={"bonos": public(items)})
        type_id = match[0]["type_id"]
        if match[0]["abono_unico"]:
            page, items = AU_PAGE, au_catalogue(client)
    item = next((i for i in items if i["type_id"] == type_id), None)
    if not item:
        raise UsageError(f"ALSA doesn't sell bono {type_id} now")
    today = config.today()
    start = start or today
    if item["start_from"] and start.isoformat() < item["start_from"]:
        raise UsageError(f"the start date can't be before {item['start_from']}")
    if item["start_until"] and start.isoformat() > item["start_until"]:
        raise UsageError(f"the start date can't be after {item['start_until']}")
    if item["needs_ministry_code"] and not ministry_code:
        raise UsageError(f"this bono needs your Ministry registration code ({item['ministry_code_prefix']}-...): "
                         "--ministry-code, from codigoviajero.transportes.gob.es")
    code_doc = None
    if ministry_code:
        res = client.resource_json(page, V, "validateDocumentNumberMitmaVoucher", method="POST", params={
            "codeMitma": ministry_code, "idVoucherType": type_id, "voucherTypology": "7",
            "documentNumber": (holder or {}).get("document") or (user or {}).get("documentNumber") or ""})
        if not isinstance(res, dict) or not res.get("isDocumentNumberValid"):
            raise UsageError("ALSA didn't accept the Ministry code for this bono",
                             alsa_message=(res or {}).get("errorCodeBackText"))
        code_doc = res.get("documentValidate")
    priced = _prices(client, page, type_id, start, {"familia-general": "20", "familia-especial": "50"}.get(
        discount or "", discount) if discount else None)
    pm = priced["payments"]
    methods = pm.get("paymentsType") or []
    total = next((m.get("money") for m in methods), None)
    token = pm.get("creditCardTokenInfo") if isinstance(pm.get("creditCardTokenInfo"), dict) else None
    h = holder or {}
    name = h.get("name") or (user or {}).get("name")
    surname = h.get("surname") or (user or {}).get("surnames")
    doc = code_doc or h.get("document") or (user or {}).get("documentNumber")
    dtype = str(h.get("document_type") or (user or {}).get("documentType") or "1")
    bdate = birth_date or (user or {}).get("birthDate")
    email = email or (user or {}).get("email")
    phone = phone or (user or {}).get("mobileNumber")
    if not (name and surname and doc):
        raise UsageError("holder's name, surname and document are needed (--holder 'Nombre;Apellidos;DNI'), "
                         "or log in")
    if not user:
        raise UsageError("buying a bono without Alsa Plus registers a new account; log in first (`alsa login`)")
    if not (email and phone):
        raise UsageError("contact email and phone are needed (--email, --phone)")
    out: dict[str, Any] = {
        "bono": {k: v for k, v in item.items() if not k.startswith("_")},
        "start": start.isoformat(),
        "holder": {"name": f"{name} {surname}".strip(), "document": doc},
        "discounts_offered": priced["discounts"],
        "total": total, "currency": "EUR",
        "payment_methods": [m.get("paymentMethod") for m in methods],
        "saved_card_usable": bool(pm.get("creditCardTokenActive")),
        "pay_with": "free" if (total == 0) else pay,
    }
    if token and token.get("creditCardNumber"):
        num = "".join(ch for ch in token["creditCardNumber"] if ch.isdigit())
        out["saved_card"] = {"type": token.get("creditCardType"), "last4": num[-4:] or None}
    if not confirm:
        out["status"] = "reviewed"
        out["next"] = "Nothing was bought. Re-run with --yes to buy it."
        return out
    names = {"card": "CreditCard", "saved-card": "CreditCard", "paypal": "PayPal", "bizum": "Bizum",
             "google-pay": "GooglePay", "klarna": "Klarna"}
    method_obj = next((m for m in methods if m.get("paymentMethod") == names.get(pay)), None) if total else (
        methods[0] if methods else None)
    if not method_obj:
        raise UsageError(f"ALSA doesn't offer {pay} for this bono", details={"offered": out["payment_methods"]})
    if pay == "saved-card" and total and not pm.get("creditCardTokenActive"):
        raise UsageError("ALSA doesn't offer your saved card for this bono; use --pay card")
    code, number = (phone.split("-", 1) + [""])[:2] if "-" in phone else ("+34", phone)
    payment_info: dict[str, Any] = {"idPaymentMethodMain": str(method_obj.get("id")), "email": email,
                                    "mobileNumber": f"{code}-{''.join(c for c in number if c.isdigit())}",
                                    "documentType": int(dtype)}
    if method_obj.get("paymentMethod") == "CreditCard":
        payment_info.update({"documentNumber": doc, "requestCreditCardToken": False,
                             "creditCardActiveTokenPayment": pay == "saved-card"})
    selected = {"passenger": {"name": name, "surname": surname, "email": "", "documentNumber": doc,
                              "documentType": dtype, "birthDate": bdate or ""},
                "paymentInfo": payment_info,
                "voucherTypeSelected": {"dateFrom": start.isoformat() if item["choose_start_date"]
                                        else config.alsa_date(start)},
                "codeMitma": ministry_code or "", "selectedSubset": ""}
    form = {"pickerfirstTrip": config.alsa_date(start), "passengerName": name, "passengerSurname": surname,
            "passengerDocumentType": "0" if dtype == "1" else "1", "passengerDocumentNumber": doc,
            "contactEmail": email, "internationalDiallingCode": "", "contactPhoneNumber": number,
            "phonePrefixAndNumber": "", "apBirthdate": "",
            "voucherDiscountSelection": f"discount-{discount}" if discount in ("20", "50") else "accumulative-none",
            f"moneyPaymentType-{method_obj.get('id')}": "[object Object]",
            "voucherSelected": json.dumps(selected, ensure_ascii=False),
            "apGiveData": "false", "apGiveDataAlsa": "false", "createAlsaPlusUser": "false"}
    if page == ROUTE_PAGE and item.get("_raw_index") is not None:
        form["voucherType"] = str(item["_raw_index"])
    r = client.action(page, V, "paymentProcessAction", method="POST", form=form, retry=False)
    import re

    m = re.search(r'<form[^>]*id="envio"[^>]*action="([^"]+)"', r.text)
    if m:
        from . import gateway

        out.update(gateway.complete(client, m.group(1).replace("&amp;", "&"), "POST", browser=browser, method=pay))
        return out
    from . import confirmation

    try:
        out.update(confirmation.parse_result(client, r.text, str(r.url)))
    except Exception:
        out["status"] = "unknown"
    out["notice"] = "Check `alsa bonos mine` to see the new bono and, for an Abono Único, its security code."
    return out
