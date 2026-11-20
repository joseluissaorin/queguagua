"""The Alsa Plus private area: profile, points, purse, bonos (Abono Único included) and past trips."""

import re
from datetime import date, datetime
from typing import Any

from . import auth, pageparams
from .client import AlsaClient
from .errors import UsageError

_PURSE = re.compile(r"Monedero(?:\s|<[^>]*>)*([0-9]+(?:[.,][0-9]+)?)(?:\s|<[^>]*>)*(?:&euro;|€)")


def _d(s: str | None) -> date | None:
    try:
        return datetime.strptime(s or "", "%d/%m/%Y").date()
    except ValueError:
        return None


def purse_from_html(html: str) -> float | None:
    m = _PURSE.search(html)
    return float(m.group(1).replace(",", ".")) if m else None


def whoami(client: AlsaClient) -> dict:
    r = client.page("/", what="home page")
    u = auth.user_from_page(pageparams.parse(r.text))
    if not u:
        return {"logged_in": False}
    return auth.public_user(u, purse=purse_from_html(r.text))


def my_bonos_raw(client: AlsaClient) -> list[dict]:
    auth.ensure_login(client)
    r = client.page("/area-privada/bonos/mis-bonos", what="Mis bonos page")
    vl = pageparams.parse(r.text).get("", {}).get("voucherList")
    return vl if isinstance(vl, list) else []


def normalize_bono(b: dict, *, reveal: bool = False) -> dict:
    t = b.get("voucherTypeSelected") or {}
    start, end = _d(b.get("dateFrom") or t.get("dateFrom")), _d(b.get("dateTo") or t.get("dateTo"))
    today = date.today()
    trips = []
    for kind, key in (("own", "redeemedOwnTrips"), ("friend", "redeemedFriendTrips"), ("sent", "redeemedSendTrips")):
        for x in b.get(key) or []:
            trips.append({"kind": kind, "locator": x.get("locator"), "from": x.get("originName"),
                          "to": x.get("destinationName"), "date": x.get("date"), "time": x.get("time"),
                          "bought": x.get("sellingDate")})
    out: dict[str, Any] = {
        "name": b.get("voucherName") or t.get("voucherName"),
        "kind": b.get("digitalVoucherName") or t.get("digitalVoucherName"),
        "type_id": t.get("voucherType"),
        "abono_unico": bool(t.get("isUnifiedVoucher")) or bool(b.get("idUnifiedTicket")),
        "active": bool(b.get("active")),
        "valid_from": start.isoformat() if start else None,
        "valid_to": end.isoformat() if end else None,
        "valid_today": bool(start and end and start <= today <= end),
        "route": None if (b.get("originStationId") in (None, "0")) else
                 {"from": (b.get("originName") or "").strip(), "to": (b.get("destinationName") or "").strip()},
        "service": t.get("serviceNameType"),
        "trips_total": t.get("voucherTripsNumber") or None,
        "trips_left": t.get("voucherAvailableTrips") if t.get("voucherTripsNumber") else None,
        "unlimited": not t.get("voucherTripsNumber"),
        "price": t.get("amount"),
        "purchase_locator": b.get("locator"),
        "holder": " ".join(x for x in [b.get("passengerName"), b.get("passengerSurname")] if x) or None,
        "trips": trips,
    }
    code = b.get("idUnifiedTicket") or b.get("promoCode")
    if code:
        out["code"] = code
    if reveal and b.get("codeSecurityUnifiedTicket"):
        out["security_code"] = b["codeSecurityUnifiedTicket"]
    return out


def my_bonos(client: AlsaClient, *, reveal: bool = False) -> list[dict]:
    return [normalize_bono(b, reveal=reveal) for b in my_bonos_raw(client)]


def abono_for(client: AlsaClient, travel_date: date) -> dict:
    """The account's Abono Único valid on `travel_date`: document, document type and security code."""
    candidates = []
    for b in my_bonos_raw(client):
        if not b.get("idUnifiedTicket") or not b.get("codeSecurityUnifiedTicket"):
            continue
        start, end = _d(b.get("dateFrom")), _d(b.get("dateTo"))
        if start and end and start <= travel_date <= end:
            candidates.append(b)
    if not candidates:
        raise UsageError(f"no Abono Único in your Alsa Plus account is valid on {travel_date.isoformat()}",
                         details={"hint": "`alsa bonos mine` lists them; `alsa abono buy` buys one"})
    b = candidates[0]
    return {"id": b["idUnifiedTicket"], "security_code": b["codeSecurityUnifiedTicket"],
            "document": b.get("passengerDocumentNumber"), "document_type": int(b.get("passengerDocumentType") or 1),
            "name": b.get("voucherName")}


B = "BusplusJourneysPortlet_WAR_Alsaportlet"


def trips(client: AlsaClient, *, months: int = 12, page: int = 1, newest_first: bool = True) -> dict:
    """Your Alsa Plus trip history (Puntos y viajes): locator, route, date, fare, price and points."""
    auth.ensure_login(client)
    r = client.page("/puntos-y-viajes", what="Puntos y viajes page")
    params = pageparams.parse(r.text).get("", {})
    ns = params.get("busplusJourneysNamespace") or f"_{B}_"
    payload = client.resource_json("/puntos-y-viajes", B, "JsonGetDetailsFidelityCard", params={
        ns + "dateSince": str(months), ns + "sort": "1" if newest_first else "0", ns + "pag": str(page)})
    from .search import iso_local

    items = []
    for j in (payload or {}).get("journeyList") or []:
        items.append({
            "locator": j.get("locator"), "ticket": j.get("ticket"),
            "from": j.get("originName"), "from_id": j.get("originId"),
            "to": j.get("destinationName"), "to_id": j.get("destinationId"),
            "date": iso_local(None, f"{j.get('departureDataToFilter')} {j.get('arrivalTime') or '00:00'}")[:10]
            if j.get("departureDataToFilter") else None,
            "arrival_time": j.get("arrivalTime"),
            "service": j.get("serviceTypeDesc") or None,
            "price": j.get("price"), "points": j.get("points"), "points_value": j.get("cashPoints"),
            "note": j.get("movDesciption") or j.get("comment") or None,
        })
    upcoming = re.findall(r"locator=([0-9a-z]{7})", str(params.get("busplusNextJourneysViewList") or ""))
    return {"from": payload.get("monthFrom"), "to": payload.get("monthTo"), "page": payload.get("pag"),
            "count": len(items), "upcoming_locators": list(dict.fromkeys(upcoming)), "trips": items}
