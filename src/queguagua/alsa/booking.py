"""A booking, step by step, exactly as ALSA's checkout runs it. The cart lives in the server session.

    step 1  search.start() + GetJourneyListResource            (search.py)
            GetPackageFaresResource / UpdateJourneySelectionResource   journey, fare and fare package
    step 2  Step2Action -> page: seat maps (jsonBusList), extras (jsonPremiumServicesList), cart
            UpdateSeatSelectionResource                         a seat per passenger and direction
            SelectPremiumServiceForAllResource / ResetPremiumServiceResource / SelectUnselectPremiumServiceResource
    step 3  Step3Action -> page: passengers and their discounts, payment methods, saved card, points
            UpdateDiscountsResource, UpdateSendDistributionsResource, CheckGiveDataResource
    pay     ProcessPaymentAction (form field processPaymentData=<JSON>)
            -> an auto-submitting form to Worldline's hosted checkout (card, saved card, PayPal, Bizum...)
            -> or straight to the confirmation (nothing left to pay: Abono Único, points, purse)

`Checkout.quote()` describes the cart at any point; nothing is bought until `pay()`.
"""

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any

from . import config, pageparams
from . import search as search_mod
from .client import AlsaClient
from .errors import ApiShapeError, PaymentError, UsageError

P = config.PURCHASE_PORTLET

# By the first word of the package's name: with the Abono Único ALSA sells the same three under other ids
# ("Superflexible Abono Único" is 1428, not 624).
PACKAGE_ALIASES = {
    "basica": "basica", "basic": "basica",
    "flexible": "flexible", "flex": "flexible",
    "superflexible": "superflexible", "super": "superflexible", "superflex": "superflexible",
}

EXTRA_ALIASES = {
    "pet": "1", "mascota": "1", "animal": "1",
    "sport": "2", "bike": "2", "bici": "2", "bicicleta": "2", "deportivo": "2",
    "block-seat": "6", "asiento-contiguo": "6", "bloquear": "6",
    "insurance": "insurance", "seguro": "insurance",
    "carbon": "550", "co2": "550", "huella": "550",
    "assistance": "201", "asistencia": "201",
}

# ALSA offers DNI, NIE and "other" (a passport goes as "other"; there is no separate passport type).
DOCUMENT_TYPES = {"other": 0, "otro": 0, "passport": 0, "pasaporte": 0, "dni": 1, "nie": 2}
DOCUMENT_LABELS = {0: "Otro documento", 1: "DNI español", 2: "NIE español"}

DISCOUNT_ALIASES = {
    "familia-general": "20", "fn-general": "20", "large-family": "20",
    "familia-especial": "50", "fn-especial": "50", "large-family-special": "50",
    "discapacidad": "125", "disability": "125", "acompanante": "125", "acompañante": "125",
}

PAY_METHODS = ("saved-card", "card", "points", "purse", "paypal", "bizum", "google-pay", "apple-pay", "klarna", "free")


def _find_journey(journeys: list[dict], *, departure: str | None, index: int | None, stop_to: str | None,
                  stop_from: str | None, service: str | None, what: str) -> dict:
    from .stations import fold

    if index is not None:
        for j in journeys:
            if j["index"] == index:
                return j
        raise UsageError(f"no {what} journey with index {index}")
    if not departure:
        raise UsageError(f"choose the {what} journey with its departure time (--departure HH:MM) or --journey")
    cands = [j for j in journeys if (j["departure"] or "")[11:16] == departure]
    if stop_to:
        cands = [j for j in cands if fold(stop_to) in fold(j["destination"]["name"] or "")]
    if stop_from:
        cands = [j for j in cands if fold(stop_from) in fold(j["origin"]["name"] or "")]
    if service:
        cands = [j for j in cands if any(fold(service) in fold(s) for s in j["service"])]
    if not cands:
        raise UsageError(f"no {what} journey leaves at {departure}",
                         details={"departures": sorted({(j["departure"] or "")[11:16] for j in journeys})})
    if len(cands) > 1:
        sale = [j for j in cands if j["available"]]
        if len(sale) == 1:
            return sale[0]
        raise UsageError(f"{len(cands)} {what} journeys leave at {departure}: add --to-stop/--service or --journey",
                         details={"candidates": [{"index": j["index"], "to": j["destination"]["name"],
                                                  "service": j["service"]} for j in cands]})
    return cands[0]


@dataclass
class PassengerInfo:
    name: str
    surname: str
    document: str
    document_type: int = 1
    discount: str | None = None  # ALSA discount type code ("20", "50", "125")

    @classmethod
    def parse(cls, text: str) -> "PassengerInfo":
        """"Nombre;Apellidos;DNI[;dni|nie|passport|other][;discount]" """
        parts = [p.strip() for p in text.split(";")]
        if len(parts) == 2 and all(parts):  # a baby: name and surname only
            return cls(parts[0], parts[1], "", 1, None)
        if len(parts) < 3 or not all(parts[:3]):
            raise UsageError("passenger format: 'Nombre;Apellidos;Documento[;dni|nie|other][;discount]' "
                             "(babies: 'Nombre;Apellidos')")
        dtype = 1
        disc = None
        for extra in parts[3:]:
            low = extra.lower()
            if low in DOCUMENT_TYPES:
                dtype = DOCUMENT_TYPES[low]
            elif low in DISCOUNT_ALIASES or low.isdigit():
                disc = DISCOUNT_ALIASES.get(low, low)
            elif low:
                raise UsageError(f"unknown passenger field {extra!r}")
        if dtype == 1 and not re.fullmatch(r"[0-9]{8}[A-Za-z]", parts[2]):
            raise UsageError(f"{parts[2]!r} isn't a DNI (8 digits and a letter); add ';nie' or ';passport'")
        return cls(parts[0], parts[1], parts[2].upper(), dtype, disc)

    def personal_info(self) -> dict:
        info: dict[str, Any] = {"name": self.name.strip(), "surname": self.surname.strip()}
        if self.document:
            info["document"] = {"documentType": {"documentType": self.document_type,
                                                 "documentDescription": DOCUMENT_LABELS.get(self.document_type, "")},
                                "documentNumber": self.document}
        return info


@dataclass
class Contact:
    email: str
    phone: str
    dialling_code: str = "+34"
    country_code: str = "ES"
    country_name: str = "España"
    sms: bool = False
    whatsapp: bool = False
    pax_index: int = 0


@dataclass
class Checkout:
    client: AlsaClient
    request: search_mod.SearchRequest
    outward: dict | None = None
    ret: dict | None = None
    step2: dict = field(default_factory=dict)
    step3: dict = field(default_factory=dict)
    cart: dict = field(default_factory=dict)
    seats: list[dict] = field(default_factory=list)
    extras: list[dict] = field(default_factory=list)
    package: dict | None = None
    return_package: dict | None = None
    discounts: list[dict] = field(default_factory=list)
    step1_return_subtotal: float | None = None

    def _absorb(self, payload: Any) -> None:
        """Take the cart from whatever a resource answered: `jsonCart`, `jsonCartAndPayments` or
        `cartAndPayments` (often as a JSON string), or the cart-and-payments object itself."""
        if not isinstance(payload, dict):
            return
        if "cart" in payload and "paymentsType" in payload:
            self.step3["jsonCartAndPayments"] = payload
            self.cart = payload.get("cart") or self.cart
            return
        for key in ("jsonCartAndPayments", "cartAndPayments"):
            if payload.get(key):
                cp = json.loads(payload[key]) if isinstance(payload[key], str) else payload[key]
                if self.step3:
                    self.step3["jsonCartAndPayments"] = cp
                self.cart = cp.get("cart") or self.cart
                return
        if payload.get("jsonCart"):
            jc = payload["jsonCart"]
            self.cart = json.loads(jc) if isinstance(jc, str) else jc

    # ---- step 1 --------------------------------------------------------------------------------------

    def choose(self, *, departure: str | None = None, index: int | None = None, stop_to: str | None = None,
               stop_from: str | None = None, service: str | None = None, fare: str | None = None,
               package: str | None = None, return_departure: str | None = None, return_index: int | None = None,
               return_package: str | None = None) -> None:
        jl = search_mod.journey_list(self.client, "I")
        outs = [search_mod.normalize_journey(j, "I") for j in jl["journeys"]]
        self.outward = _find_journey(outs, departure=departure, index=index, stop_to=stop_to,
                                     stop_from=stop_from, service=service, what="outward")
        if not self.outward["available"]:
            raise UsageError("that journey isn't on sale (sold out or closed)",
                             details={"sale_status": self.outward["sale_status"]})
        out_fare = self._pick_fare(self.outward, fare)
        self.package = self._pick_package(self.outward, package, "I")
        ret_fare_idx, ret_pkg_id = -1, ""
        if self.request.return_date:
            rl = search_mod.journey_list(self.client, "V")
            rets = [search_mod.normalize_journey(j, "V") for j in rl["journeys"]]
            self.ret = _find_journey(rets, departure=return_departure, index=return_index, stop_to=stop_from,
                                     stop_from=stop_to, service=service, what="return")
            if not self.ret["available"]:
                raise UsageError("that return journey isn't on sale")
            ret_fare_idx = self._pick_fare(self.ret, fare)["index"]
            self.return_package = self._pick_package(self.ret, return_package or package, "V")
            ret_pkg_id = (self.return_package or {}).get("id") or ""
        payload = self.client.resource_json("/checkout", P, "UpdateJourneySelectionResource", params={
            "outwardJourney": self.outward["index"], "outwardFare": out_fare["index"],
            "outwardPackageFare": (self.package or {}).get("id") or "",
            "returnJourney": self.ret["index"] if self.ret else -1, "returnFare": ret_fare_idx,
            "returnPackageFare": ret_pkg_id,
        })
        if not isinstance(payload, dict) or "jsonCart" not in payload:
            raise ApiShapeError("UpdateJourneySelectionResource changed shape")
        self.cart = payload["jsonCart"] if isinstance(payload["jsonCart"], dict) else json.loads(payload["jsonCart"])
        self.step1_return_subtotal = (self.cart.get("returnJourney") or {}).get("subtotal")

    @staticmethod
    def _pick_fare(journey: dict, fare: str | None) -> dict:
        fares = journey["fares"]
        if not fares:
            raise UsageError("that journey has no fare on sale")
        if fare is None:
            return fares[0]
        from .stations import fold

        for f in fares:
            if str(f["index"]) == fare or fold(f["name"] or "") == fold(fare):
                return f
        raise UsageError(f"no fare {fare!r} on that journey", details={"fares": [f["name"] for f in fares]})

    def _pick_package(self, journey: dict, package: str | None, direction: str) -> dict | None:
        pkgs = search_mod.package_fares(self.client, journey["index"], direction)
        journey["packages"] = pkgs
        if not pkgs:
            return None
        avail = [p for p in pkgs if p["available"]]
        if package is None:
            return min(avail or pkgs, key=lambda p: p["extra_price"] or 0)
        from .stations import fold

        want = PACKAGE_ALIASES.get(fold(package))
        for p in pkgs:
            name = fold(p["name"] or "")
            if p["id"] == package or name == fold(package) or (want and name.split(" ")[0] == want):
                if not p["available"]:
                    raise UsageError(f"the {p['name']} package isn't available on that journey",
                                     details={"available": [x["name"] for x in pkgs if x["available"]]})
                return p
        raise UsageError(f"no package {package!r}", details={"packages": [p["name"] for p in pkgs]})

    # ---- step 2 --------------------------------------------------------------------------------------

    def go_step2(self, extra_params: dict | None = None) -> None:
        """`extra_params` carries the wheelchair answers, which ALSA's page appends to the Step2Action URL."""
        r = self.client.action("/checkout", P, "Step2Action", params=extra_params)
        self.step2 = pageparams.parse(r.text).get("purchase", {})
        if "jsonCart" not in self.step2:
            raise ApiShapeError("the extras page (step 2) has no cart: ALSA's checkout may have changed")
        self.cart = self.step2["jsonCart"]

    def seat_map(self, direction: str = "I", bus_index: int = 0) -> dict:
        buses = (self.step2.get("jsonBusList") or {}).get("outwardBuses" if direction == "I" else "returnBuses") or []
        if bus_index >= len(buses):
            return {"numbered": False, "seats": []}
        bus = buses[bus_index]
        groups = bus.get("groupSeatMap") or {}
        seats = []
        for car in bus.get("cars") or []:
            for deck in car.get("decks") or []:
                for row in deck.get("rows") or []:
                    for s in row.get("seats") or []:
                        if s.get("status") in ("AVAILABLE", "OCCUPIED") and s.get("seatNumber"):
                            g = groups.get(s.get("groupSeat") or "", {})
                            prices = g.get("pricePerPassengerList") or []
                            seats.append({"seat": s["seatNumber"], "free": s["status"] == "AVAILABLE",
                                          "position": (s.get("seatPosition") or "").lower() or None,
                                          "deck": s.get("deck"), "row": s.get("rowNumber"),
                                          "special": bool(g.get("isSpecial")),
                                          "price": prices[0] if prices else None})
        assigned = [{"passenger": a.get("passengerIndex"), "seat": a.get("seatNumber")}
                    for a in bus.get("assignedSeats") or []]
        return {"numbered": bool(bus.get("numbering")), "service": bus.get("serviceTypeDescription"),
                "decks": max((s["deck"] or 1 for s in seats), default=1),
                "free": sum(1 for s in seats if s["free"]), "preassigned": assigned, "seats": seats}

    def _raw_seat(self, direction: str, bus_index: int, number: int) -> dict:
        buses = (self.step2.get("jsonBusList") or {}).get("outwardBuses" if direction == "I" else "returnBuses") or []
        if bus_index >= len(buses):
            raise UsageError("that journey has no seat map")
        for car in buses[bus_index].get("cars") or []:
            for deck in car.get("decks") or []:
                for row in deck.get("rows") or []:
                    for s in row.get("seats") or []:
                        if s.get("seatNumber") == number:
                            if s.get("status") != "AVAILABLE":
                                raise UsageError(f"seat {number} isn't free")
                            return s
        raise UsageError(f"there's no seat {number} on that bus")

    def choose_seat(self, number: int, *, passenger: int = 0, direction: str = "I", bus_index: int = 0) -> None:
        seat = copy.deepcopy(self._raw_seat(direction, bus_index, number))
        seat.update({"status": 1, "type": 1, "direction": direction, "passengerIndex": passenger})
        payload = self.client.resource_json("/checkout", P, "UpdateSeatSelectionResource", json_body={
            "seat": seat, "busIndex": bus_index, "passengerIndex": passenger, "journeyDirection": direction})
        if isinstance(payload, dict) and payload.get("unableToChangeSeats"):
            raise UsageError("ALSA doesn't allow choosing seats on this journey")
        self._absorb(payload)
        if isinstance(payload, dict) and payload.get("jsonBusList"):
            jb = payload["jsonBusList"]
            self.step2["jsonBusList"] = json.loads(jb) if isinstance(jb, str) else jb
        self.seats.append({"direction": "outward" if direction == "I" else "return", "passenger": passenger,
                           "seat": number})

    def best_seat(self, pref: str, direction: str = "I", taken: set[int] | None = None) -> int:
        m = self.seat_map(direction)
        free = [s for s in m["seats"] if s["free"] and s["seat"] not in (taken or set())]
        if pref in ("window", "aisle"):
            pick = [s for s in free if s["position"] == pref] or free
        else:
            pick = free
        if not pick:
            raise UsageError("no free seat left to choose")
        pick.sort(key=lambda s: (s["special"], s["price"] or 0, s["deck"] or 0, s["row"] or 0))
        return pick[0]["seat"]

    def services(self) -> list[dict]:
        out = []
        for s in self.step2.get("jsonPremiumServicesList") or self.step3.get("jsonPremiumServicesList") or []:
            prices = [p.get("price") for p in s.get("priceList") or [] if p.get("price") is not None]
            out.append({"id": s.get("id"), "name": s.get("name"), "price": min(prices) if prices else None,
                        "outward": s.get("isOutwardValid") == "S", "return": s.get("isReturnValid") == "S",
                        "max_per_passenger": s.get("outwardMaxUnitsPerTraveller"),
                        "description": search_mod._text(s.get("observations"))})
        return out

    def add_extra(self, extra: str) -> None:
        sid = EXTRA_ALIASES.get(extra.lower(), extra)
        known = {s["id"] for s in self.services()}
        if sid not in known:
            raise UsageError(f"extra {extra!r} isn't offered on this journey",
                             details={"offered": [{"id": s["id"], "name": s["name"]} for s in self.services()]})
        payload = self.client.resource_json("/checkout", P, "SelectPremiumServiceForAllResource", json_body={"id": sid})
        self._absorb(payload)
        self.extras.append({"id": sid, "name": next(s["name"] for s in self.services() if s["id"] == sid)})

    # ---- step 3 --------------------------------------------------------------------------------------

    def go_step3(self) -> None:
        r = self.client.action("/checkout", P, "Step3Action")
        params = pageparams.parse(r.text)
        self.step3 = params.get("purchase", {})
        if "jsonCartAndPayments" not in self.step3:
            raise ApiShapeError("the payment page (step 3) has no cart: ALSA's checkout may have changed")
        self.cart = self.step3["jsonCartAndPayments"].get("cart") or self.cart

    @property
    def payments(self) -> dict:
        return self.step3.get("jsonCartAndPayments") or {}

    def payment_methods(self) -> list[dict]:
        out = []
        for p in self.payments.get("paymentsType") or []:
            def r2(v):
                return round(v, 2) if isinstance(v, (int, float)) else v

            out.append({"method": p.get("paymentMethod"), "id": p.get("id"), "code": p.get("paymentCode"),
                        "money": r2(p.get("money")), "points_used": p.get("points") or None,
                        "points_value": r2(p.get("cashPoints")) or None, "purse": r2(p.get("purse")) or None,
                        "combinable_with_money": not p.get("onlyThisTypePay"),
                        "free": bool(p.get("freeOfCharge"))})
        return out

    def saved_card(self) -> dict | None:
        info = self.payments.get("creditCardTokenInfo")
        if not isinstance(info, dict) or not info.get("creditCardNumber"):
            return None
        num = re.sub(r"\D", "", info.get("creditCardNumber") or "")
        return {"type": info.get("creditCardType"), "last4": num[-4:] if num else None,
                "provider": info.get("provider")}

    def passengers_template(self) -> list[dict]:
        return self.step3.get("jsonPassengersList") or []

    def available_discounts(self) -> list[dict]:
        out = []
        for i, p in enumerate(self.passengers_template()):
            for d in p.get("showDiscounts") or []:
                out.append({"passenger": i, "id": d.get("type"), "name": d.get("name"),
                            "percent": d.get("percentage"), "stackable": d.get("accumulative") == "S",
                            "requirements": d.get("requirements")})
        return out

    def apply_discount(self, passenger: int, discount_type: str, person: "PassengerInfo", *,
                       large_family_card: str | None = None, large_family_expiry: str | None = None) -> dict:
        """UpdateDiscountsResource, with the body ALSA's payment page sends when a discount is ticked."""
        pax = self.passengers_template()
        if passenger >= len(pax):
            raise UsageError(f"there's no passenger {passenger + 1}")
        offered = {str(d.get("type")): d for d in pax[passenger].get("showDiscounts") or []}
        if discount_type not in offered:
            raise UsageError(f"discount {discount_type!r} isn't offered to passenger {passenger + 1}",
                             details={"offered": [{"id": k, "name": v.get("name")} for k, v in offered.items()]})
        d = offered[discount_type]
        extra: dict[str, Any] = {"name": person.name, "surname": person.surname, "documentNumber": person.document}
        if discount_type in ("20", "50"):
            if not (large_family_card and large_family_expiry):
                raise UsageError("a large-family discount needs the card number and its expiry "
                                 "(--large-family-card, --large-family-expiry DD/MM/YYYY)")
            extra["largeFamilyDocumentNumber"] = large_family_card
            extra["largeFamilyDocumentExpiration"] = large_family_expiry
        body = {"passengerIndex": passenger, "appliedDiscountsToCancel": [],
                "passengerDiscountData": {"type": d.get("type"), "accumulative": d.get("accumulative"),
                                          "percentage": d.get("percentage")},
                "extraPassengerDiscountData": extra}
        payload = self.client.resource_json("/checkout", P, "UpdateDiscountsResource", json_body=body,
                                            url=self.step3.get("updateDiscountsResourceURL"))
        if not isinstance(payload, dict):
            raise ApiShapeError("UpdateDiscountsResource changed shape")
        val = payload.get("discountValidation") or {}
        if val and not val.get("discountValid", True):
            raise UsageError("ALSA didn't accept the discount", alsa_message=search_mod._text(val.get("discountMessage")))
        self._absorb(payload)
        applied = {"passenger": passenger + 1, "discount": d.get("name"), "percent": d.get("percentage")}
        self.discounts.append(applied)
        return applied

    def add_extra_for(self, extra: str, passenger: int, direction: str = "I", step: int = 2) -> None:
        """A per-passenger extra (SelectUnselectPremiumServiceResource), e.g. a pet for passenger 2 only."""
        sid = EXTRA_ALIASES.get(extra.lower(), extra)
        payload = self.client.resource_json("/checkout", P, "SelectUnselectPremiumServiceResource", json_body={
            "id": sid, "passenger": passenger, "journeyDirection": direction, "select": "S", "step": step})
        self._absorb(payload)
        if sid == str(self.step3.get("donationServiceId") or "501"):
            name = "Donación (1 €)"
        else:
            name = next((s["name"] for s in self.services() if s["id"] == sid), sid)
        self.extras.append({"id": sid, "name": name, "passenger": passenger + 1,
                            "direction": "outward" if direction == "I" else "return"})

    def delivery(self, kind: str) -> None:
        """Also send the locator by SMS ("M", 0.10 €) or WhatsApp ("W"). The same call toggles it off."""
        payload = self.client.resource_json("/checkout", P, "UpdateSendDistributionsResource",
                                            params={"sendDistributionType": kind})
        self._absorb(payload)

    def donate(self) -> None:
        """ALSA's 1 € donation (service 501), chosen on the payment page."""
        sid = str(self.step3.get("donationServiceId") or "501")
        self.add_extra_for(sid, 0, "I", step=3)

    # ---- quote and pay -------------------------------------------------------------------------------

    def total(self) -> float | None:
        return (self.cart or {}).get("totalAmount")

    def quote(self) -> dict:
        c = self.cart or {}

        def leg(j: dict | None) -> dict | None:
            if not j:
                return None
            return {
                "from": j.get("originStationDescription") or j.get("origenDescription"),
                "to": j.get("destinationStationDescription") or j.get("destinationDescription"),
                "departure": search_mod.iso_local(j.get("departure"), j.get("departureDataToFilter")),
                "arrival": search_mod.iso_local(j.get("arrival"), j.get("arrivalDataToFilter")),
                "service": j.get("serviceTypeList"),
                "lines": [{"what": l.get("translationKey"), "fare": l.get("elementDescriptionInfo"),
                           "count": l.get("numberOfElements"), "unit": l.get("unitCost"), "subtotal": l.get("subtotal")}
                          for l in j.get("passengersLines") or []],
                "extras": [{"what": l.get("elementDescription"), "count": l.get("numberOfElements"),
                            "unit": l.get("unitCost"), "subtotal": l.get("subtotal")}
                           for l in j.get("additionalServicesLines") or []],
                "discounts": [{"what": l.get("elementDescription") or l.get("translationKey"),
                               "subtotal": l.get("subtotal")} for l in j.get("discountsLines") or []],
                "subtotal": j.get("subtotal"),
            }

        return {
            "outward": leg(c.get("outwardJourney")),
            "return": leg(c.get("returnJourney")),
            "package": self.package and {"id": self.package["id"], "name": self.package["name"]},
            "return_package": self.return_package and {"id": self.return_package["id"], "name": self.return_package["name"]},
            "seats": self.seats,
            "extras": self.extras,
            "passenger_discounts": self.discounts,
            "management_fee": c.get("totalManagementCost"),
            "insurance": c.get("totalInsurancesPrices") or None,
            "open_return_cost": c.get("totalReturnOpenCost") or None,
            "delivery_cost": c.get("totalDistributionCost") or None,
            "total": c.get("totalAmount"),
            "currency": "EUR",
        }

    def payment_data(self, method: str, *, save_card: bool = False, pay_later: bool = False) -> dict:
        """Translate a CLI method into the ids the payment page would send (see doSelectPoints/doSelectMoney
        in ALSA's purchase app): points pay part as `main` with money as `supplementary`."""
        by_method = {p.get("paymentMethod"): p for p in self.payments.get("paymentsType") or []}
        by_code = {str(p.get("paymentCode")): p for p in self.payments.get("paymentsType") or []}
        pd = {"mainPaymentMethodId": "", "supplementaryPaymentMethodId": "", "googlePayToken": None,
              "saveCreditCardToken": False, "useCreditCardToken": False, "savePaypalToken": False,
              "usePaypalToken": False, "paypalPayLater": False}
        names = {"card": "CreditCard", "saved-card": "CreditCard", "paypal": "PayPal", "bizum": "Bizum",
                 "google-pay": "GooglePay", "apple-pay": "ApplePay", "klarna": "Klarna"}
        parts = method.split("+")
        main = parts[0]
        money = parts[1] if len(parts) > 1 else None
        offered = sorted(by_method)

        def money_id(m: str) -> str:
            p = by_method.get(names.get(m, ""))
            if not p:
                raise UsageError(f"ALSA doesn't offer {m} for this purchase", details={"offered": offered})
            return str(p.get("id"))

        if main == "points":
            pts = by_code.get("6") or by_method.get("BPPoints")
            if not pts:
                raise UsageError("no Alsa Plus points to pay with (log in, or not enough points)",
                                 details={"offered": offered})
            pd["mainPaymentMethodId"] = str(pts.get("id"))
            if not pts.get("onlyThisTypePay"):
                if not money:
                    raise UsageError("your points don't cover the total: use --pay points+saved-card (or +card, +paypal...)",
                                     details={"points_cover": pts.get("cashPoints"), "rest": pts.get("money")})
                pd["supplementaryPaymentMethodId"] = money_id(money)
                main = money
            else:
                main = "points"
        elif main == "purse":
            purse = by_code.get("2") or by_method.get("Purse")
            if not purse:
                raise UsageError("no purse balance to pay with", details={"offered": offered})
            pd["mainPaymentMethodId"] = str(purse.get("id"))
        elif main == "free":
            free = [p for p in self.payments.get("paymentsType") or [] if p.get("freeOfCharge")]
            pre = str(self.step3.get("PAYMENTMETHOD_PRESELECT_VALUE_STEP3") or "")
            chosen = next((p for p in free if str(p.get("id")) == pre), free[0] if free else None)
            if chosen:
                pd["mainPaymentMethodId"] = str(chosen.get("id"))
            elif (self.total() or 0) > 0:
                raise UsageError("this purchase isn't free", details={"total": self.total()})
        else:
            pd["mainPaymentMethodId"] = money_id(main)
        if main == "saved-card":
            if not self.saved_card():
                raise UsageError("your Alsa Plus account has no saved card (pay with --pay card --save-card once)")
            pd["useCreditCardToken"] = True
        if main == "card" and save_card:
            pd["saveCreditCardToken"] = True
        if main == "paypal" and pay_later:
            pd["paypalPayLater"] = True
        return pd

    def process_payment(self, passengers: list[PassengerInfo], contact: Contact, payment_data: dict,
                        give_data: bool) -> dict:
        """POST ProcessPaymentAction. Returns {"kind": "gateway", "url": ...} or {"kind": "page", "html": ...}."""
        body = {
            "contactData": {
                "selectedPaxIndex": contact.pax_index,
                "personalInfo": passengers[contact.pax_index].personal_info() if contact.pax_index >= 0 else {},
                "email": contact.email, "sendSMS": contact.sms, "sendWhatsapp": contact.whatsapp,
                "phone": {"interDiallingCode": {"countryCode": contact.country_code, "description": contact.country_name,
                                                "diallingCode": contact.dialling_code},
                          "phoneNumber": contact.phone},
            },
            "paymentData": payment_data,
            "passengerDataArray": [
                {"paxIndex": i, "giveData": bool(give_data and i == 0), "personalInfo": p.personal_info()}
                for i, p in enumerate(passengers)
            ],
        }
        r = self.client.action("/checkout", P, "ProcessPaymentAction", method="POST", retry=False,
                               form={"processPaymentData": json.dumps(body, ensure_ascii=False)})
        if r.is_redirect:
            loc = r.headers.get("location", "")
            return {"kind": "gateway", "url": loc, "method": "GET"}
        m = re.search(r'<form[^>]*id="envio"[^>]*action="([^"]+)"', r.text)
        if m:
            # The browser has to submit it from this very page (see gateway.py), so keep the page too.
            return {"kind": "gateway", "url": m.group(1).replace("&amp;", "&"), "method": "POST",
                    "html": r.text, "page_url": str(r.url)}
        params = pageparams.parse(r.text)
        err = params.get("", {}).get("errorMessageKey")
        if err or "RuntimeErrorRender" in str(r.url):
            raise PaymentError("ALSA refused the purchase before payment", alsa_message=str(err) if err else None)
        return {"kind": "page", "html": r.text, "url": str(r.url)}
