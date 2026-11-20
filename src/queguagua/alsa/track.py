"""Localiza tu bus: today's buses on a route and, when ALSA has GPS data, where one of them is.

    POST trackingBusTrayectoAction (origin/destination ids)   -> params["jsonTrackingBus"].navegaliaList
         each leg: service (= search's service_code), flight (expedition), times
    POST trackingBusLocalizadorAction (locator)               -> the buses of a booking
    POST AjaxGetBusServiceTracking date=yyyymmdd&service&flight&legOrigin/DestinationStationId
         -> per bus: GPS position and per stop scheduled / real / estimated times

ALSA's own page says the feature is "en pruebas"; on 20 Nov 2026 the position call returned an empty body
for every bus tried (the website then shows "No disponible el servicio de seguimiento"). We report that
honestly as `live: false`.
"""

import math
import re
from datetime import date
from typing import Any

from . import config, pageparams
from .client import AlsaClient
from .errors import UsageError

T = "TrackingBusPortlet_WAR_Alsaportlet"
PATH = "/a-bordo/localiza-tu-bus"


def _list_from(html: str) -> tuple[Any, dict]:
    params = pageparams.parse(html).get("", {})
    return params.get("jsonTrackingBus"), params


def route_buses(client: AlsaClient, origin_id: str, destination_id: str) -> list[dict]:
    client.page(PATH, what="Localiza tu bus page")
    r = client.action(PATH, T, "trackingBusTrayectoAction", method="POST", form={
        f"_{T}_previousOriginName": origin_id, f"_{T}_originStationId": origin_id,
        f"_{T}_previousDestinationName": destination_id, f"_{T}_destinationStationId": destination_id})
    data, _ = _list_from(r.text)
    out = []
    for j in (data or {}).get("navegaliaList", []) if isinstance(data, dict) else []:
        for leg in j.get("legs") or []:
            out.append({"from": leg.get("legOrigin"), "from_id": leg.get("legOriginId"),
                        "to": leg.get("legDestination"), "to_id": leg.get("legDestinationId"),
                        "date": leg.get("headerDate") or leg.get("departureDate"),
                        "departure": leg.get("departureTime"), "arrival": leg.get("arrivalTime"),
                        "service": leg.get("service"), "expedition": leg.get("flight"),
                        "line": leg.get("serviceDescription"), "service_type": leg.get("serviceType"),
                        "trackable": j.get("canBeSold") != "N"})
    return out


def _deg(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f == 0:
        return None
    return round(math.degrees(f), 6) if abs(f) <= math.pi else f


def position(client: AlsaClient, bus: dict) -> dict:
    d = bus.get("date") or config.alsa_date(config.today())
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d)
    ymd = f"{m.group(3)}{m.group(2)}{m.group(1)}" if m else date.today().strftime("%Y%m%d")
    r = client.resource(PATH, T, "AjaxGetBusServiceTracking", method="POST", params={
        f"_{T}_date": ymd, f"_{T}_service": bus["service"], f"_{T}_flight": bus["expedition"],
        f"_{T}_legOriginStationId": bus["from_id"], f"_{T}_legDestinationStationId": bus["to_id"]}, form={})
    if r.status_code != 200 or not r.content.strip():
        return {"live": False, "notice": "ALSA has no live tracking data for this bus right now "
                                         "(its own page says 'No disponible el servicio de seguimiento')."}
    try:
        data = r.json()
    except ValueError:
        return {"live": False, "notice": "ALSA's tracking answer wasn't JSON"}
    buses = []
    for b in data if isinstance(data, list) else [data]:
        pos = (b.get("buses") or [{}])[0]
        stops = []
        for s in b.get("itinerario") or []:
            stops.append({"stop": s.get("nomPueblo") or s.get("parada"), "scheduled_arrival": s.get("hllegada"),
                          "scheduled_departure": s.get("hsalida"), "real_arrival": s.get("realArrivalTime") or None,
                          "real_departure": s.get("realDepartureTime") or None,
                          "estimated_arrival": s.get("estArrivalTime") or None,
                          "visited": s.get("visitada") == "1"})
        buses.append({"line": b.get("nomLinea"), "bus_numbers": b.get("cartel"),
                      "lat": _deg(pos.get("latitud")), "lon": _deg(pos.get("longitud")), "stops": stops})
    return {"live": bool(buses), "buses": buses}


def find(client: AlsaClient, origin_id: str, destination_id: str, departure: str | None) -> dict:
    buses = route_buses(client, origin_id, destination_id)
    out: dict[str, Any] = {"date": config.today().isoformat(), "count": len(buses), "buses": buses}
    if departure:
        match = [b for b in buses if b["departure"] == departure]
        if not match:
            raise UsageError(f"no bus left at {departure} today on that route (ALSA lists recent departures only)",
                             details={"departures": [b["departure"] for b in buses]})
        out["tracked"] = {**match[0], **position(client, match[0])}
    return out
