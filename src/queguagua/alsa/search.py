"""Search journeys and fares the way ALSA's results page does.

1. `SearchJourneysAction` (a portlet action on /checkout, needs p_auth) stores the search in the server
   session: stops, dates, passengers by type, promo code or bono, one way / round trip / open return;
2. `GetJourneyListResource?journeyDirection=I` (and `V` for the return) returns the journeys with their fares;
3. optionally `GetPackageFaresResource?journeyIndex=N` per journey: the fare packages (Básica, Flexible,
   Superflexible...) priced on top of the journey fare.

The session then holds that search, so a booking continues from it (booking.py).
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from . import config
from .client import AlsaClient, raise_for_alsa
from .errors import ApiShapeError, UsageError

P = config.PURCHASE_PORTLET
J = config.JOURNEY_SEARCH_PORTLET

# ALSA's passenger type ids: `passengerType-<id>=<count>` (DISABLED_TRAVELER=7, BABY_ALONE=11, SECOND_BABY=12 and
# PMR_COMPANION=13 also exist; the server silently rewrites combinations it doesn't like, so we validate first).
PASSENGER_TYPES = {"ADULT": 1, "CHILD": 2, "BABY": 3, "YOUNG": 4, "SENIOR": 5}
PASSENGER_LABELS = {
    "ADULT": "Adulto (26-59)", "YOUNG": "Joven (12-25)", "SENIOR": "Mayor (60+)",
    "CHILD": "Niño (4-11)", "BABY": "Bebé (0-3)",
}


@dataclass
class Passengers:
    adults: int = 1
    young: int = 0
    seniors: int = 0
    children: int = 0
    babies: int = 0

    def by_type(self) -> dict[str, int]:
        return {"ADULT": self.adults, "YOUNG": self.young, "SENIOR": self.seniors,
                "CHILD": self.children, "BABY": self.babies}

    @property
    def seats(self) -> int:
        """What ALSA's form sends as `seats`: every passenger, babies included (a baby gets its own seat)."""
        return self.adults + self.young + self.seniors + self.children + self.babies

    @property
    def total(self) -> int:
        return self.seats

    def validate(self) -> None:
        counts = self.by_type()
        if any(v < 0 for v in counts.values()):
            raise UsageError("passenger counts can't be negative")
        if self.adults + self.young + self.seniors + self.children < 1:
            raise UsageError("at least one adult, young, senior or child passenger")
        if self.total > config.MAX_PASSENGERS:
            raise UsageError(f"ALSA sells at most {config.MAX_PASSENGERS} passengers per booking")
        if self.babies > self.adults + self.young + self.seniors:
            raise UsageError("each baby needs an adult, young or senior passenger")

    def params(self) -> dict[str, str]:
        out = {}
        for t, n in sorted(self.by_type().items(), key=lambda kv: PASSENGER_TYPES[kv[0]]):
            if n:
                out[f"passengerType-{PASSENGER_TYPES[t]}"] = str(n)
        return out

    def public(self) -> dict[str, int]:
        return {k: v for k, v in {"adults": self.adults, "young": self.young, "seniors": self.seniors,
                                   "children": self.children, "babies": self.babies}.items() if v}


@dataclass
class SearchRequest:
    origin: dict
    destination: dict
    departure: date
    passengers: Passengers = field(default_factory=Passengers)
    return_date: date | None = None
    open_return: bool = False
    promo_code: str = ""
    young_promo_code: str = ""
    employee: bool = False

    @property
    def travel_type(self) -> str:
        if self.open_return:
            return "OPEN_RETURN"
        return "RETURN" if self.return_date else "OUTWARD"

    def params(self) -> dict[str, str]:
        p = {
            "alsaspam": "",
            "originStationId": self.origin["id"],
            "destinationStationId": self.destination["id"],
            "departureDate": config.alsa_date(self.departure),
            "returnDate": config.alsa_date(self.return_date) if self.return_date else "",
            "seats": str(self.passengers.seats),
            "promoCode": self.promo_code,
            "youngPromoCode": self.young_promo_code,
            "travelType": self.travel_type,
            "employee": "true" if self.employee else "false",
        }
        p.update(self.passengers.params())
        return p


# ---- promo codes and the Abono Único ------------------------------------------------------------------


def check_unified_ticket(client: AlsaClient, *, security_code: str, document: str, document_type: int,
                         departure: date) -> str:
    """Validate an Abono Único (holder's document + its 5-digit security code) for a travel date and
    return its id (the "Nº del Abono Único"), which then goes in the search as a promo code."""
    payload = client.resource_json("/home", J, "CheckCodeSecurityUnifiedTicketResourceCommand", json_body={
        "codeSecurityUnifiedTicket": security_code,
        "documentTypeUnifiedTicket": document_type,
        "documentNumberUnifiedTicket": document,
        "departureDateUnifiedTicket": config.alsa_date(departure),
    })
    raise_for_alsa(payload, "the Abono Único", UsageError)
    if not isinstance(payload, dict) or not payload.get("valid") or not payload.get("idUnifiedTicket"):
        msg = payload.get("message") or payload.get("errorMessage") if isinstance(payload, dict) else None
        raise UsageError("ALSA didn't accept the Abono Único for that date (document or security code?)",
                         alsa_message=msg)
    return str(payload["idUnifiedTicket"])


def check_promo(client: AlsaClient, req: SearchRequest, code: str) -> dict:
    """What the search box's "Comprobar" does. ALSA keeps the result in the session for the search."""
    body: dict[str, Any] = {
        "promoCode": code,
        "originStationId": req.origin["id"],
        "destinationStationId": req.destination["id"],
        "departureDate": _iso_midnight(req.departure),
        "returnDate": _iso_midnight(req.return_date) if req.return_date else None,
        "travelType": req.travel_type,
        "seats": req.passengers.seats,
    }
    for k, v in req.passengers.params().items():
        body[k] = int(v)
    payload = client.resource_json("/home", J, "CheckPromocodeResourceCommand", json_body=body)
    if not isinstance(payload, dict):
        raise ApiShapeError("CheckPromocodeResourceCommand changed shape")
    return payload


def _iso_midnight(d: date) -> str:
    """Midnight in Madrid as the UTC instant the web sends (2026-11-27 -> 2026-11-26T23:00:00.000Z)."""
    from datetime import timezone

    local = datetime(d.year, d.month, d.day, tzinfo=config.MADRID)
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def promo_summary(payload: dict) -> dict:
    out = {"code": payload.get("promoCode"), "valid": bool(payload.get("valid")),
           "type": payload.get("promoType"), "description": payload.get("description") or None}
    if payload.get("message"):
        out["alsa_message"] = payload["message"]
    return out


# ---- the search itself -------------------------------------------------------------------------------


def start(client: AlsaClient, req: SearchRequest) -> dict:
    """Run the search action; returns the page params of the results page (step 1)."""
    from . import pageparams

    r = client.action("/checkout", P, "SearchJourneysAction", params=req.params())
    params = pageparams.parse(r.text)
    err = params.get("", {}).get("errorMessageKey")
    if err:
        raise UsageError("ALSA rejected the search", alsa_message=str(err))
    return params


def journey_list(client: AlsaClient, direction: str = "I") -> dict:
    payload = client.resource_json("/checkout", P, "GetJourneyListResource", params={"journeyDirection": direction})
    if not isinstance(payload, dict) or "journeys" not in payload:
        raise ApiShapeError("GetJourneyListResource changed shape")
    return payload


def package_fares(client: AlsaClient, index: int, direction: str = "I") -> list[dict]:
    payload = client.resource_json("/checkout", P, "GetPackageFaresResource",
                                   params={"journeyIndex": str(index), "journeyDirection": direction})
    return [normalize_package(p) for p in (payload or {}).get("packageFareList", [])]


def itinerary(client: AlsaClient, index: int, direction: str = "I") -> list[dict]:
    payload = client.resource_json("/checkout", P, "GetItineraryResource",
                                   params={"journeyIndex": str(index), "journeyDirection": direction})
    stops = payload if isinstance(payload, list) else (payload or {}).get("itinerary") or (payload or {}).get("stops") or []
    return [normalize_stop(s) for s in stops]


# ---- normalization -----------------------------------------------------------------------------------

_HTML = re.compile(r"<[^>]+>")


def _text(html: str | None) -> str | None:
    if not html:
        return None
    t = _HTML.sub(" ", html).replace("&euro;", "€").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", t).strip() or None


def iso_local(epoch_ms: int | None, local: str | None) -> str | None:
    """ALSA gives both an epoch (UTC) and the stop's local wall time ("27/11/2026 01:30"). Their difference is
    the stop's UTC offset, so the result is exact for Madrid, Canarias, Lisbon or Paris alike."""
    from datetime import timezone

    if not local:
        return None
    try:
        wall = datetime.strptime(local, "%d/%m/%Y %H:%M")
    except ValueError:
        return None
    if epoch_ms:
        utc = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).replace(tzinfo=None)
        offset = round((wall - utc).total_seconds() / 900) * 900
        tz = timezone(timedelta(seconds=offset))
        return wall.replace(tzinfo=tz).isoformat()
    return wall.replace(tzinfo=config.MADRID).isoformat()


def normalize_fare(f: dict) -> dict:
    out = {
        "index": f.get("index"),
        "name": f.get("fareName"),
        "price": f.get("price"),
        "currency": "EUR",
        "type": f.get("fareType"),
        "conditions": f.get("fareConditions") or f.get("fareTypeDescription") or None,
        "open_return_price": f.get("openReturnPrice") or None,
        "promoted": bool(f.get("isPromoted")),
        "promo_codes": [p.get("code") for p in f.get("promotionCodeList") or [] if p.get("code")],
        "requires_return": f.get("outwardReturnRequired") == "S",
        "per_passenger": [
            {"type": t.get("passengerType"), "count": t.get("amount"), "price": t.get("price"),
             "promotion": t.get("promotionDescription") or None}
            for t in f.get("travellersData") or []
        ],
    }
    if f.get("priceOriginal"):
        out["price_without_promo"] = f.get("priceOriginal")
    return out


def normalize_package(p: dict) -> dict:
    return {
        "id": p.get("farePackageId"),
        "name": p.get("packageName"),
        "extra_price": p.get("totalPassengerPackagePrice", p.get("packagePrice")),
        "recommended": bool(p.get("recommended")),
        "available": bool(p.get("enabled", True)),
        "highlights": [t for o in p.get("packageObservations") or [] if (t := _text(o.get("description")))],
        "conditions": [t for o in p.get("packageObservationsOther") or [] if (t := _text(o.get("description")))],
    }


def normalize_stop(s: dict) -> dict:
    import math

    def deg(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return round(math.degrees(v), 6) if abs(v) <= math.pi else v  # ALSA sends radians

    return {
        "name": s.get("name") or s.get("stopName") or s.get("description"),
        "address": s.get("address") or None,
        "arrival": s.get("arrivalTime") or s.get("arrival") or None,
        "departure": s.get("departureTime") or s.get("departure") or None,
        "stop_minutes": s.get("stopDuration") or s.get("stopTime") or None,
        "type": s.get("type") or s.get("stopType") or None,
        "lat": deg(s.get("latitude")),
        "lon": deg(s.get("longitude")),
    }


SALE_STATUS = {"V": "on_sale", "F": "sold_out_or_closed"}


def normalize_journey(j: dict, direction: str) -> dict:
    dep = iso_local(j.get("departureDate"), j.get("departureDataToFilter"))
    arr = iso_local(j.get("arrivalDate"), j.get("arrivalDataToFilter"))
    minutes = None
    if j.get("departureDate") and j.get("arrivalDate"):
        minutes = round((j["arrivalDate"] - j["departureDate"]) / 60000)
    bc = j.get("busCharacteristic") or {}
    fares = sorted((normalize_fare(f) for f in j.get("fares") or []), key=lambda f: (f["price"] is None, f["price"] or 0))
    return {
        "index": j.get("index"),
        "direction": "outward" if direction == "I" else "return",
        "departure": dep,
        "arrival": arr,
        "duration_minutes": minutes,
        "origin": {"id": j.get("originId"), "name": j.get("originName")},
        "destination": {"id": j.get("destinationId"), "name": j.get("destinationName")},
        "service": j.get("serviceTypeDescList") or [],
        "service_codes": j.get("serviceTypeList") or [],
        "line": j.get("lineName") or None,
        "changes": j.get("transfersNumber") or 0,
        "change_at": [t.get("name") if isinstance(t, dict) else t for t in j.get("transfersTown") or []],
        "stops": int(j["totalNumberOfStops"]) if str(j.get("totalNumberOfStops") or "").isdigit() else None,
        "available": j.get("canBeSold") == "V",
        "sale_status": SALE_STATUS.get(j.get("canBeSold"), j.get("canBeSold")),
        "fares": fares,
        "cheapest": fares[0]["price"] if fares else None,
        "features": [c.get("description") for c in bc.get("characteristicList") or [] if c.get("description")],
        "night_bus": bool(bc.get("isNightBus")),
        "non_stop": bool(bc.get("isNonStopBus")),
        "double_decker": bool(bc.get("isDoubleDeckerBus")),
        "abono_unico_ok": bool(bc.get("isFreeVoucherApplyable")),
        "pets": (j.get("petAvailability") or "").lower() or None,
        "sport_equipment": (j.get("sportAvailability") or "").lower() or None,
        "wheelchair": (j.get("handicappedAvailability") or "").lower() or None,
        "block_adjacent_seat": (j.get("contiguousPaxAvailability") or "").lower() or None,
        "warning": _text(j.get("warning")),
        "observations": _text(j.get("observations")),
        "service_code": j.get("serviceCodes") or None,
        "company": j.get("companyService") or None,
        "train": bool(j.get("isTrainTrip")),
        "wheelchair_places": j.get("numberPMRSeats") or 0,
    }


def normalize_voucher(v: dict) -> dict:
    return {
        "name": v.get("voucherName") or v.get("digitalVoucherName"),
        "type": v.get("voucherType"),
        "price": v.get("amount"),
        "trips": v.get("voucherTripsNumber") or None,
        "validity_days": int(v["validDays"]) if str(v.get("validDays") or "").isdigit() else None,
        "service": v.get("serviceNameType"),
        "abono_unico": bool(v.get("isUnifiedVoucher")),
        "start_between": [v.get("minDateFrom"), v.get("maxDateFrom")] if v.get("minDateFrom") else None,
        "observations": _text(v.get("observations")),
    }


# ---- the whole search, as `alsa search` runs it --------------------------------------------------------


@dataclass
class Filters:
    after: str | None = None          # HH:MM, departure at or after
    before: str | None = None         # HH:MM, departure at or before
    arrive_by: str | None = None      # HH:MM, arrival at or before (same day)
    service: str | None = None        # comfort / supra / premium / ... (substring, accents ignored)
    available_only: bool = False
    direct_only: bool = False
    limit: int = 20


def _hhmm(iso: str | None) -> str | None:
    return iso[11:16] if iso else None


def apply_filters(journeys: list[dict], f: Filters, travel_date: date) -> list[dict]:
    from .stations import fold

    out = []
    for j in journeys:
        dep, arr = _hhmm(j["departure"]), _hhmm(j["arrival"])
        if f.after and dep and dep < f.after:
            continue
        if f.before and dep and dep > f.before:
            continue
        if f.arrive_by:
            if not arr or (j["arrival"] or "")[:10] != travel_date.isoformat() or arr > f.arrive_by:
                continue
        if f.service and not any(fold(f.service) in fold(s) for s in j["service"]):
            continue
        if f.available_only and not j["available"]:
            continue
        if f.direct_only and j["changes"]:
            continue
        out.append(j)
    return out[: f.limit]


def resolve_abono(client: AlsaClient, req: SearchRequest, *, security_code: str | None, document: str | None,
                  document_type: int = 1) -> dict:
    """Validate the Abono Único for the outward date (from the account when no code is given) and put its
    id in the request as the promo code."""
    source = "flags"
    if not security_code:
        from . import account

        ab = account.abono_for(client, req.departure)
        security_code, document, document_type, source = ab["security_code"], ab["document"], ab["document_type"], "account"
    if not document:
        raise UsageError("the Abono Único needs the holder's document (--document) with --abono-code")
    abono_id = check_unified_ticket(client, security_code=security_code, document=document,
                                    document_type=document_type, departure=req.departure)
    req.promo_code = abono_id
    promo = check_promo(client, req, abono_id)
    if not promo.get("valid"):
        raise UsageError("ALSA didn't accept the Abono Único for this route or date", alsa_message=promo.get("message"))
    return {"abono_unico": True, "source": source, "valid": True, "type": promo.get("promoType")}


def run(client: AlsaClient, req: SearchRequest, filters: Filters, *, packages: bool = False,
        abono: dict | None = None) -> dict:
    """Search, list outward (and return) journeys, filter, optionally price packages. Leaves the search in the
    session so a booking can continue from it."""
    req.passengers.validate()
    if req.return_date and req.return_date < req.departure:
        raise UsageError("the return date is before the departure date")
    promo_info = None
    if abono is not None:
        promo_info = resolve_abono(client, req, **abono)
    elif req.promo_code:
        promo = check_promo(client, req, req.promo_code)
        promo_info = promo_summary(promo)
        if not promo.get("valid"):
            hint = None
            if promo.get("promoType") is None and "único" in (promo.get("message") or "").lower():
                hint = "That looks like an Abono Único number: use --abono (with --abono-code and --document, or logged in)."
            raise UsageError("ALSA didn't accept the promo code", alsa_message=promo.get("message"),
                             details={"hint": hint} if hint else None)
    start(client, req)
    out_list = journey_list(client, "I")
    outward = [normalize_journey(j, "I") for j in out_list.get("journeys", [])]
    shown = apply_filters(outward, filters, req.departure)
    ret_shown: list[dict] | None = None
    ret_count = None
    if req.return_date or req.open_return:
        if req.return_date:
            rl = journey_list(client, "V")
            ret_all = [normalize_journey(j, "V") for j in rl.get("journeys", [])]
            ret_count = len(ret_all)
            rf = Filters(available_only=filters.available_only, service=filters.service,
                         direct_only=filters.direct_only, limit=filters.limit)
            ret_shown = apply_filters(ret_all, rf, req.return_date)
    if packages:
        for j in shown:
            if j["available"]:
                j["packages"] = package_fares(client, j["index"], "I")
        for j in ret_shown or []:
            if j["available"]:
                j["packages"] = package_fares(client, j["index"], "V")
    payload: dict[str, Any] = {
        "date": req.departure.isoformat(),
        "return_date": req.return_date.isoformat() if req.return_date else None,
        "trip": {"OUTWARD": "one_way", "RETURN": "round_trip", "OPEN_RETURN": "open_return"}[req.travel_type],
        "origin": {k: req.origin.get(k) for k in ("id", "name", "group")},
        "destination": {k: req.destination.get(k) for k in ("id", "name", "group")},
        "passengers": req.passengers.public(),
        "promo": promo_info,
        "count": len(outward),
        "shown": len(shown),
        "journeys": shown,
    }
    if ret_shown is not None:
        payload["return_count"] = ret_count
        payload["return_journeys"] = ret_shown
    vouchers = [normalize_voucher(v) for v in out_list.get("voucherList") or []]
    if vouchers:
        payload["bonos_for_route"] = vouchers
    if out_list.get("carbonFootprint") is not None:
        payload["co2_kg_per_passenger"] = out_list.get("carbonFootprint")
    if not outward:
        payload["notice"] = "ALSA lists no journeys for that route and date."
    elif not shown:
        payload["notice"] = "No journey matches the filters."
    payload["retries"] = client.retries
    return payload
