"""Your bookings after buying: look one up, get the PDF or the boarding QR, cancel it.

- Lookup (no login): POST /info resource `jsonGetTicketDataResourceCommand` {"localizador", "documentNumber"}
  -> one entry per passenger with legs (times, stops, seat, platform, bus plate, live status) and the
  boarding QR text.
- Change and cancel go through "Cambios y anulaciones" (AmendmentPortlet): `searchTicketAction` with the
  locator and the passenger's document renders the tickets; each cancellable one carries a checksum.
  `checkVoidPermissions` previews the fee, the void form cancels. A ticket can only be managed a few
  minutes after it's issued.
"""

import json
import re
from pathlib import Path
from typing import Any

from . import auth, cachefile, pageparams
from .client import AlsaClient
from .errors import ApiShapeError, UsageError

A = "AmendmentPortlet_WAR_Alsaportlet"
AMEND_PATH = "/gestion-de-billetes/cambios-y-anulaciones"
STATUS = {0: "no_info", 1: "at_platform", 2: "boarding", 3: "last_call", 4: "on_route", 5: "finished"}


def _document(client: AlsaClient, document: str | None) -> str:
    if document:
        return document.strip().upper()
    u = auth.ensure_login(client, required=False)
    if u and u.get("documentNumber"):
        return u["documentNumber"]
    raise UsageError("pass the passenger's document (--document), or log in to use yours")


def _info_urls(client: AlsaClient) -> dict:
    r = client.page("/info", what="ticket info page")
    urls = {k: v for ns in pageparams.parse(r.text).values() for k, v in ns.items()
            if isinstance(v, str) and "TicketData" in v}
    if "jsonGetTicketDataURL" not in urls:
        raise ApiShapeError("no ticket lookup endpoint on alsa.es/info")
    return urls


def _leg(l: dict) -> dict:
    j, b = l.get("journey") or {}, l.get("bus") or {}

    def dt(date_s, time_s):
        m = re.match(r"(\d{2})/(\d{2})/(\d{4})", date_s or "")
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}T{time_s}" if m and time_s else None

    return {
        "from": j.get("originName"), "from_id": j.get("originId"), "from_address": j.get("originAddress"),
        "to": j.get("destinationName"), "to_id": j.get("destinationId"), "to_address": j.get("destinationAddress"),
        "departure": dt(j.get("departureDateStrGeneral"), j.get("departureTime")),
        "arrival": dt(j.get("arrivalDateStrGeneral"), j.get("arrivalTime")),
        "service": j.get("serviceType"), "fare": j.get("fareName"),
        "seat": b.get("assignedSeatNumber"), "bus": b.get("busNumber"), "plate": b.get("plateNumber") or None,
        "platform": b.get("platform") or b.get("platformRange") or None,
        "status": STATUS.get(b.get("statusCode"), b.get("statusCode")), "status_text": b.get("statusDescription"),
        "real_time": bool(b.get("isRealTime")),
        "qr": l.get("qrText") or None,
        "package": [re.sub(r"<[^>]+>", " ", o.get("description") or "").strip()
                    for o in l.get("packageObservationsOther") or []],
    }


def lookup(client: AlsaClient, locator: str, document: str | None = None, *, qr: bool = False) -> dict:
    doc = _document(client, document)
    urls = _info_urls(client)
    r = client.resource("/info", "", "jsonGetTicketDataResourceCommand", url=urls["jsonGetTicketDataURL"],
                        json_body={"localizador": locator.strip().lower(), "documentNumber": doc})
    if r.status_code == 404:
        raise UsageError("ALSA has no booking with that locator and document")
    if r.status_code != 200:
        raise ApiShapeError("the ticket lookup failed", status=r.status_code)
    data = r.json()
    tickets = []
    for t in data or []:
        item = {
            "locator": t.get("locator"), "passenger": t.get("paxFullName"), "document": t.get("paxDocumentNumber"),
            "trip": (t.get("travelType") or "").lower(),
            "outward": [_leg(l) for l in t.get("outwardLegsData") or []],
            "return": [_leg(l) for l in t.get("returnLegsData") or []],
            "extras": [x.get("name") for x in (t.get("outwardExtraServices") or []) + (t.get("returnExtraServices") or [])],
        }
        if not qr:
            for leg in item["outward"] + item["return"]:
                leg.pop("qr", None)
        tickets.append(item)
    return {"locator": locator.lower(), "count": len(tickets), "tickets": tickets}


# ---- amendment (change / cancel) ----------------------------------------------------------------------


def amendment_page(client: AlsaClient, locator: str, document: str) -> str:
    client.page(AMEND_PATH, what="cambios y anulaciones page")
    r = client.action(AMEND_PATH, A, "searchTicketAction", method="POST", form={
        f"_{A}_searchType": "1", f"_{A}_locator": locator.strip().lower(), f"_{A}_nif": document,
        f"_{A}_digits": "", f"_{A}_personalid": "", f"_{A}_creditfindby": "1", f"_{A}_searchdate": "",
        f"_{A}_ccard": "", f"_{A}_niforpassport2": "", f"_{A}_walletFindBy": "1", f"_{A}_searchdate2": ""})
    if "portalRuntimeErrorMsg" in r.text and "Num. billete" not in r.text:
        raise UsageError("ALSA didn't find that booking for that document (Cambios y anulaciones)")
    return r.text


def manage_view(client: AlsaClient, locator: str, document: str | None = None) -> dict:
    """What ALSA lets you do with each ticket of a booking right now."""
    doc = _document(client, document)
    html = amendment_page(client, locator, doc)
    body = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    numbers = list(dict.fromkeys(re.findall(r"Num\. billete\s*(?:<[^>]+>\s*)*([0-9-]{8,})", body)))
    rows = _options(html)
    out: dict[str, Any] = {
        "locator": locator.lower(),
        "tickets": [{"ticket": i + 1, "number": numbers[i] if i < len(numbers) else None,
                     "can_cancel": "void" in r, "can_change": "change" in r, "can_change_holder": "holder" in r}
                    for i, r in enumerate(rows)] or [{"ticket": i + 1, "number": n, "can_cancel": False,
                                                       "can_change": False, "can_change_holder": False}
                                                      for i, n in enumerate(numbers)],
        "cancelled": "Anulado" in body,
        "pdf_available": "AjaxGetTicketPdf" in html,
    }
    if "esperar unos instantes" in body:
        out["notice"] = "ALSA needs a few minutes after issuing or changing a ticket before it can be managed."
    return out


def download_pdf(client: AlsaClient, locator: str, document: str | None, dest: Path) -> dict:
    doc = _document(client, document)
    html = amendment_page(client, locator, doc)
    links = [m.replace("&amp;", "&") for m in re.findall(r'href="([^"]*AjaxGetTicketPdf[^"]*)"', html)]
    if not links:
        raise UsageError("no ticket PDF offered for that booking")
    r = client.send("GET", links[0], what="ticket PDF", headers={"Accept": "application/pdf,*/*"})
    if r.status_code != 200 or not r.content.startswith(b"%PDF"):
        raise ApiShapeError("ALSA didn't return a PDF", status=r.status_code)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return {"locator": locator.lower(), "saved": str(dest), "bytes": len(r.content)}


# ---- cancel ------------------------------------------------------------------------------------------

_OPTION = re.compile(r'<a class="(?:amendment-option )?(void|change)[^"]*" href="([^"]+)"')


def _options(html: str) -> list[dict]:
    """One entry per ticket row: its checksum/position and the links ALSA offers (void, change, holder)."""
    seen: dict[str, dict] = {}
    for kind, href in _OPTION.findall(html):
        href = href.replace("&amp;", "&")
        m = re.search(r"javax\.portlet\.action=(\w+)", href)
        action = m.group(1) if m else kind
        pos = re.search(r"_pos=(\d*)", href)
        key = (re.search(r"checksum=([^&]+)", href) or re.search(r"(.*)", href)).group(1)
        row = seen.setdefault(key, {"pos": int(pos.group(1)) if pos and pos.group(1) else 0})
        if action.startswith("voidTicket"):
            row["void"] = href
        elif action == "changeTicketAction":
            row["change"] = href
        elif action == "changeHolderAction":
            row["holder"] = href
    rows = list(seen.values())
    rows.sort(key=lambda r: r["pos"])
    return rows


def _money(text: str, label: str) -> float | None:
    m = re.search(re.escape(label) + r"\s*:?\s*(?:<[^>]+>\s*)*(-?[0-9]+(?:[.,][0-9]+)?)", text)
    return float(m.group(1).replace(",", ".")) if m else None


def cancel(client: AlsaClient, locator: str, document: str | None = None, *, ticket: int = 1,
           confirm: bool = False) -> dict:
    """Preview (default) or confirm the cancellation of one ticket of a booking."""
    doc = _document(client, document)
    html = amendment_page(client, locator, doc)
    rows = _options(html)
    if not rows:
        if "esperar unos instantes" in html:
            raise UsageError("ALSA needs a few minutes after issuing (or changing) a ticket before it can be "
                             "cancelled; try again shortly")
        raise UsageError("ALSA offers no cancellation for that booking (already cancelled, travelled, or "
                         "past the deadline)")
    if ticket < 1 or ticket > len(rows):
        raise UsageError(f"that booking has {len(rows)} ticket(s)")
    row = rows[ticket - 1]
    if "void" not in row:
        raise UsageError("that ticket can't be cancelled online")
    r = client.send("GET", row["void"], what="voidTicketAction", headers={"Accept": "text/html"})
    page = r.text
    m = re.search(r'id="confirmVoidBtn"[^>]*data-href="([^"]+)"', page, re.S)
    body = re.sub(r"<script.*?</script>", "", page, flags=re.S)
    preview = {
        "locator": locator.lower(), "ticket": ticket, "tickets_in_booking": len(rows),
        "ticket_price": _money(body, "Precio del billete"),
        "extras": _money(body, "Importe servicios adicionales"),
        "fee": _money(body, "Precio del recargo"),
        "management_cost": _money(body, "Costes de gestión"),
        "insurance": _money(body, "Importe seguro"),
        "refund": _money(body, "Importe a devolver"),
        "points_refund": _money(body, "Puntos a devolver"),
    }
    if not m:
        raise UsageError("ALSA didn't offer to confirm this cancellation", details={"preview": preview})
    if not confirm:
        preview["status"] = "previewed"
        preview["next"] = "Nothing was cancelled. Re-run with --yes to cancel this ticket."
        return preview
    href = m.group(1).replace("&amp;", "&")
    done = client.send("GET", href, what="cancellationTicketAction", headers={"Accept": "text/html"}, retry=False)
    ok = "La anulación ha finalizado con éxito" in done.text
    preview["status"] = "cancelled" if ok else "unknown"
    if not ok:
        preview["notice"] = "ALSA didn't show its success message; check `alsa ticket` and your email."
    return preview
