"""`alsa quote`, `alsa seats` and `alsa buy`: one booking from search to payment, in a single session.

Without `--yes`, `buy` stops right before ProcessPaymentAction and prints the quote (status "reviewed"):
nothing is booked or charged. With `--yes` it submits, and then either
- nothing is left to pay (Abono Único on a Comfort bus, points or purse covering it all): ALSA confirms at
  once and we read the locator from the confirmation page; or
- the money part goes through Worldline's hosted page (card, saved card, PayPal, Bizum, Google Pay,
  Klarna): see gateway.py.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from . import account, auth, booking, confirmation, config
from . import search as search_mod
from .booking import Checkout, Contact, PassengerInfo
from .client import AlsaClient
from .errors import AuthError, UsageError


@dataclass
class BuyOptions:
    departure: str | None = None
    journey: int | None = None
    to_stop: str | None = None
    from_stop: str | None = None
    service: str | None = None
    fare: str | None = None
    package: str | None = None
    return_departure: str | None = None
    return_journey: int | None = None
    return_package: str | None = None
    seats: list[int] = field(default_factory=list)
    return_seats: list[int] = field(default_factory=list)
    seat_pref: str | None = None          # window / aisle / any: pick one per passenger
    extras: list[str] = field(default_factory=list)
    passengers: list[str] = field(default_factory=list)
    discounts: list[str] = field(default_factory=list)   # "familia-general" or "2:discapacidad"
    email: str | None = None
    phone: str | None = None
    sms: bool = False
    pay: str = "saved-card"
    save_card: bool = False
    pay_later: bool = False
    whatsapp: bool = False
    donate: bool = False
    wheelchair: str | None = None          # onboard / hold
    wheelchair_passengers: list[int] = field(default_factory=list)   # 1-based
    transfer_seat: bool = False
    companion: bool = False
    large_family_card: str | None = None
    large_family_expiry: str | None = None
    abono: bool = False
    abono_code: str | None = None
    document: str | None = None
    need_login: bool = False


def _split_phone(raw: str | None) -> tuple[str, str]:
    if not raw:
        return "+34", ""
    m = re.match(r"\s*(\+\d{1,4})[\s-]*(.*)", raw)
    if m:
        return m.group(1), re.sub(r"\D", "", m.group(2))
    return "+34", re.sub(r"\D", "", raw)


def _holder(user: dict | None) -> PassengerInfo | None:
    if not user or not user.get("documentNumber") or not user.get("name"):
        return None
    try:
        dtype = int(user.get("documentType") or 1)
    except ValueError:
        dtype = 1
    surname = (user.get("surnames") or " ".join(x for x in [user.get("surname1"), user.get("surname2")] if x)).strip()
    return PassengerInfo(user["name"].strip(), surname, user["documentNumber"].strip(), dtype)


ACCOUNT_METHODS = ("saved-card", "points", "purse")


def needs_account(pay: str) -> bool:
    return any(part in ACCOUNT_METHODS for part in pay.split("+"))


def prepare(client: AlsaClient, req: search_mod.SearchRequest, opt: BuyOptions, *, stop_at: str = "step3",
            require_login: bool = False) -> dict:
    """Run the booking up to `stop_at` ("step2" or "step3") and return the checkout and its context."""
    user = auth.ensure_login(client, required=require_login or opt.need_login or bool(opt.abono and not opt.abono_code))
    abono_info = None
    if opt.abono or opt.abono_code:
        abono_info = search_mod.resolve_abono(client, req, security_code=opt.abono_code, document=opt.document)
    elif req.promo_code:
        promo = search_mod.check_promo(client, req, req.promo_code)
        if not promo.get("valid"):
            raise UsageError("ALSA didn't accept the promo code", alsa_message=promo.get("message"))
    search_mod.start(client, req)
    co = Checkout(client, req)
    co.choose(departure=opt.departure, index=opt.journey, stop_to=opt.to_stop, stop_from=opt.from_stop,
              service=opt.service, fare=opt.fare, package=opt.package, return_departure=opt.return_departure,
              return_index=opt.return_journey, return_package=opt.return_package)
    pmr = None
    if opt.wheelchair:
        if opt.wheelchair not in ("onboard", "hold"):
            raise UsageError("--wheelchair is 'onboard' (in your wheelchair) or 'hold' (wheelchair in the hold)")
        code, number = _split_phone(opt.phone or (user or {}).get("mobileNumber"))
        if not number:
            raise UsageError("the wheelchair service needs a contact mobile (--phone)")
        places = [int(co.outward.get("wheelchair_places") or 0)]
        if co.ret:
            places.append(int(co.ret.get("wheelchair_places") or 0))
        free_pmr = min(places)
        if free_pmr < len(opt.wheelchair_passengers or [1]):
            raise UsageError("that journey has no wheelchair place left", details={"wheelchair_places": free_pmr})
        pmr = {f"pmrPassenger{i + 1}": str(p - 1) for i, p in enumerate(opt.wheelchair_passengers or [1])}
        pmr.update({"wheelchairSetting": "1" if opt.wheelchair == "onboard" else "2",
                    "additionalSeat": "true" if (opt.transfer_seat and opt.wheelchair == "onboard") else "false",
                    "companion": "true" if opt.companion else "false",
                    "interDiallingCode": code, "phoneNumber": number})
    co.go_step2(pmr)
    if req.open_return and not ((co.cart.get("returnJourney") or {}).get("subtotal")):
        raise UsageError("ALSA's checkout drops the open return at the extras step (its website doesn't offer "
                         "open returns right now): buy a one-way or a round trip instead",
                         details={"open_return_price_at_step1": co.step1_return_subtotal})
    n = req.passengers.seats - req.passengers.babies
    if opt.seats or opt.seat_pref:
        taken: set[int] = set()
        for i in range(n):
            num = opt.seats[i] if i < len(opt.seats) else (co.best_seat(opt.seat_pref or "any", "I", taken)
                                                           if opt.seat_pref else None)
            if num:
                co.choose_seat(num, passenger=i, direction="I")
                taken.add(num)
    if co.ret and (opt.return_seats or opt.seat_pref):
        taken = set()
        for i in range(n):
            num = opt.return_seats[i] if i < len(opt.return_seats) else (co.best_seat(opt.seat_pref or "any", "V", taken)
                                                                         if opt.seat_pref else None)
            if num:
                co.choose_seat(num, passenger=i, direction="V")
                taken.add(num)
    for e in opt.extras:
        idx, _, name = e.rpartition(":")
        if idx.isdigit():
            co.add_extra_for(name, int(idx) - 1)
        else:
            co.add_extra(e)
    ctx: dict[str, Any] = {"user": user, "abono": abono_info}
    if stop_at == "step2":
        return {"checkout": co, **ctx}
    co.go_step3()
    if opt.sms:
        co.delivery("M")
    if opt.whatsapp:
        co.delivery("W")
    if opt.donate:
        co.donate()
    return {"checkout": co, **ctx}


def apply_discounts(co: Checkout, opt: BuyOptions, pax: list[PassengerInfo], user: dict | None) -> None:
    wanted: list[tuple[int, str]] = []
    for d in opt.discounts:
        idx, _, name = d.rpartition(":")
        wanted.append((int(idx) - 1 if idx.isdigit() else 0, booking.DISCOUNT_ALIASES.get(name.lower(), name)))
    for i, p in enumerate(pax):
        if p.discount and not any(w[0] == i for w in wanted):
            wanted.append((i, p.discount))
    for i, code in wanted:
        if i >= len(pax):
            raise UsageError(f"--discount for passenger {i + 1}, but there are {len(pax)}")
        card = opt.large_family_card or ((user or {}).get("familyCardNumber") if i == 0 else None)
        expiry = opt.large_family_expiry or ((user or {}).get("familyCardExpirationDate") if i == 0 else None)
        co.apply_discount(i, code, pax[i], large_family_card=card, large_family_expiry=_ddmmyyyy(expiry))


def _ddmmyyyy(value: str | None) -> str | None:
    """The account keeps the card expiry in Java's Date.toString() form; the payment page sends dd/mm/yyyy."""
    if not value:
        return None
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if m:
        return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{m.group(3)}"
    m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    from datetime import datetime

    for fmt in ("%a %b %d %H:%M:%S %Z %Y", "%a %b %d %H:%M:%S CET %Y", "%a %b %d %H:%M:%S CEST %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).strftime("%d/%m/%Y")
        except ValueError:
            pass
    parts = value.split()
    if len(parts) >= 6:
        try:
            return datetime.strptime(" ".join(parts[1:3] + parts[-1:]), "%b %d %Y").strftime("%d/%m/%Y")
        except ValueError:
            pass
    return value


def build_people(co: Checkout, opt: BuyOptions, user: dict | None) -> tuple[list[PassengerInfo], Contact]:
    need = len(co.passengers_template()) or co.request.passengers.seats
    pax = [PassengerInfo.parse(p) for p in opt.passengers]
    holder = _holder(user)
    if not pax and holder:
        pax = [holder]
    if len(pax) < need:
        raise UsageError(f"this booking needs data for {need} passenger(s): add --passenger "
                         "'Nombre;Apellidos;DNI' for each" + (" (the first defaults to your Alsa Plus account)"
                                                               if holder else ""),
                         details={"have": len(pax), "need": need})
    pax = pax[:need]
    email = opt.email or (user or {}).get("email")
    code, number = _split_phone(opt.phone or (user or {}).get("mobileNumber") or (user or {}).get("telephoneNumber"))
    if not email:
        raise UsageError("a contact email is needed (--email), or log in")
    if not number:
        raise UsageError("a contact mobile number is needed (--phone '+34 600000000'), or log in")
    return pax, Contact(email=email, phone=number, dialling_code=code, sms=opt.sms, whatsapp=opt.whatsapp)


def describe(co: Checkout, ctx: dict) -> dict:
    out = {
        "outward_journey": co.outward,
        "return_journey": co.ret,
        "quote": co.quote(),
        "payment_methods": co.payment_methods() if co.step3 else None,
        "saved_card": co.saved_card() if co.step3 else None,
        "discounts_offered": co.available_discounts() if co.step3 else None,
        "extras_offered": co.services(),
        "abono": ctx.get("abono"),
        "logged_in": bool(ctx.get("user")),
    }
    return out


def buy(client: AlsaClient, req: search_mod.SearchRequest, opt: BuyOptions, *, confirm: bool,
        browser: str = "chrome", headless_gateway: bool = False) -> dict:
    ctx = prepare(client, req, opt, require_login=confirm and needs_account(opt.pay))
    co: Checkout = ctx["checkout"]
    pax, contact = build_people(co, opt, ctx["user"])
    apply_discounts(co, opt, pax, ctx["user"])
    method = opt.pay
    if not ctx["user"] and needs_account(method):
        method = "card"  # a guest quote: show what a card payment would look like
    total = co.total() or 0
    if total == 0 and method not in ("free",):
        method = "free"
    pdata = co.payment_data(method, save_card=opt.save_card, pay_later=opt.pay_later)
    out = describe(co, ctx)
    out["passengers"] = [{"name": f"{p.name} {p.surname}".strip(), "document": p.document} for p in pax]
    out["contact"] = {"email": contact.email, "phone": f"{contact.dialling_code} {contact.phone}"}
    out["pay_with"] = method
    if not confirm:
        out["status"] = "reviewed"
        out["next"] = "Nothing was booked or charged. Re-run the same command with --yes to buy."
        return out
    give = bool((ctx["user"] or {}).get("giveData")) if ctx["user"] else False
    res = co.process_payment(pax, contact, pdata, give)
    if res["kind"] == "page":
        out.update(confirmation.parse_result(client, res["html"], res.get("url")))
        return out
    from . import gateway

    out.update(gateway.complete(client, res["url"], res.get("method", "POST"), browser=browser,
                                headless=headless_gateway, method=method))
    return out
