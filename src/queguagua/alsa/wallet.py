"""Apple Wallet passes (.pkpass) for your ALSA tickets.

ALSA hands out its own pass only on the confirmation page, right after buying: GetWalletResource reads the
purchase kept in the server session and answers 500 once it's gone. Neither the email (a PDF only) nor the
ticket lookup offers it. So `buy` saves ALSA's pass at once, and for any ticket the CLI can build the pass
itself from the ticket lookup (/info): the boarding QR the driver scans, stops, times, seat and platform.

A pass Wallet accepts is signed with a Pass Type ID certificate from an Apple developer account. Put in
`<config>/wallet/` (`queguagua alsa wallet --help` prints the folder):
- pass.pem: the Pass Type ID certificate (its subject names the pass type and the team);
- pass.key: its private key;
- wwdr.pem: Apple's WWDR G4 intermediate (https://www.apple.com/certificateauthority/AppleWWDRCAG4.cer).
Signing runs `openssl smime`, which macOS and Linux have.
"""

import hashlib
import json
import re
import shutil
import struct
import subprocess
import tempfile
import zipfile
import zlib
from datetime import datetime, timedelta
from pathlib import Path

from . import config, manage
from .client import AlsaClient
from .errors import ApiShapeError, UsageError

CREAM = (250, 246, 238)
ULTRAMARINE = (35, 47, 140)
INK = (110, 102, 92)


def signing_dir() -> Path:
    return config.config_dir() / "wallet"


# ---- the pass --------------------------------------------------------------------------------------------


def _stop(stop_id: str | None, raw: str | None) -> tuple[str, str]:
    """(city, stop) for a stop id, from the station catalogue; ALSA's ticket shouts and drops accents."""
    from . import stations

    try:
        entries = stations._entries(stations._cached() or stations._shipped())
    except Exception:  # noqa: BLE001 - the catalogue only makes names nicer
        entries = []
    by_id = {e["id"]: e for e in entries}
    e = by_id.get(str(stop_id or ""))
    if e:
        city = e.get("province") or ""
        group = by_id.get(e.get("in_group") or "")
        if group:
            city = re.sub(r"\s*\(Todas las paradas\)\s*$", "", group["name"]) or city
        name = e["name"]
        if city and stations.fold(name).startswith(stations.fold(city) + " "):
            name = name[len(city):].strip()
        return city or name, name
    title = (raw or "").title()
    return title, title


def _iso(local: str | None) -> str | None:
    """'2026-11-22T19:30' in Madrid -> '2026-11-22T19:30:00+01:00'."""
    if not local:
        return None
    return datetime.fromisoformat(local).replace(tzinfo=config.MADRID).isoformat()


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def pass_json(ticket: dict, leg: dict, raw_leg: dict, *, pass_type: str, team: str, serial: str) -> dict:
    j = raw_leg.get("journey") or {}
    from_city, from_stop = _stop(leg.get("from_id"), leg.get("from"))
    to_city, to_stop = _stop(leg.get("to_id"), leg.get("to"))
    dep, arr = _iso(leg.get("departure")), _iso(leg.get("arrival"))
    qr = raw_leg.get("qrText") or ""
    time_style = {"timeStyle": "PKDateStyleShort", "dateStyle": "PKDateStyleNone", "ignoresTimeZone": True}
    secondary = [{"key": "date", "label": "FECHA", "value": dep, "dateStyle": "PKDateStyleMedium",
                  "timeStyle": "PKDateStyleNone", "ignoresTimeZone": True}] if dep else []
    if arr:
        secondary.append({"key": "arrival", "label": "LLEGADA", "value": arr, **time_style})
    if leg.get("seat"):
        secondary.append({"key": "seat", "label": "PLAZA", "value": str(leg["seat"])})
    if leg.get("platform"):
        secondary.append({"key": "platform", "label": "DÁRSENA", "value": str(leg["platform"])})
    auxiliary = [{"key": "passenger", "label": "VIAJERO", "value": ticket.get("passenger") or ""},
                 {"key": "locator", "label": "LOCALIZADOR", "value": (ticket.get("locator") or "").upper()}]
    back = [
        {"key": "fromAddress", "label": "Salida", "value": f"{from_stop}. {(j.get('originAddress') or '').title()}"},
        {"key": "toAddress", "label": "Llegada", "value": f"{to_stop}. {(j.get('destinationAddress') or '').title()}"},
    ]
    if leg.get("fare"):
        back.append({"key": "fare", "label": "Tarifa", "value": leg["fare"]})
    if leg.get("service"):
        back.append({"key": "service", "label": "Servicio", "value": leg["service"]})
    notes = [_plain(o.get("description")) for o in raw_leg.get("packageObservationsOther") or []]
    if notes:
        back.append({"key": "conditions", "label": "Condiciones", "value": "\n".join(n for n in notes if n)})
    back.append({"key": "about", "label": "Sobre este pase",
                 "value": "Hecho con queguagua a partir de tu billete de ALSA: el código QR es el del billete. "
                          "El billete válido sigue siendo el de ALSA."})
    p = {
        "formatVersion": 1,
        "passTypeIdentifier": pass_type,
        "teamIdentifier": team,
        "serialNumber": serial,
        "organizationName": "ALSA",
        "description": f"Billete de ALSA de {from_city} a {to_city}",
        "logoText": "ALSA",
        "foregroundColor": "rgb({},{},{})".format(*ULTRAMARINE),
        "backgroundColor": "rgb({},{},{})".format(*CREAM),
        "labelColor": "rgb({},{},{})".format(*INK),
        "boardingPass": {
            "transitType": "PKTransitTypeBus",
            "headerFields": [{"key": "departure", "label": "SALIDA", "value": dep, **time_style}] if dep else [],
            "primaryFields": [{"key": "from", "label": from_stop.upper(), "value": from_city},
                              {"key": "to", "label": to_stop.upper(), "value": to_city}],
            "secondaryFields": secondary,
            "auxiliaryFields": auxiliary,
            "backFields": back,
        },
        "barcodes": [{"format": "PKBarcodeFormatQR", "message": qr,
                      "messageEncoding": "iso-8859-1" if qr.isascii() else "utf-8"}],
    }
    if dep:
        p["relevantDate"] = dep
    if arr:
        p["expirationDate"] = (datetime.fromisoformat(arr) + timedelta(hours=12)).isoformat()
    try:
        p["locations"] = [{"latitude": float(j["originLatitude"]), "longitude": float(j["originLongitude"]),
                           "relevantText": f"Tu guagua a {to_city} sale de {from_stop}"}]
    except (KeyError, TypeError, ValueError):
        pass
    return p


# ---- images ----------------------------------------------------------------------------------------------


def _png(size: int) -> bytes:
    """A square icon: a cream bus on ultramarine, drawn on a grid so it stays crisp at 29, 58 and 87 px."""
    u = size / 29
    px = [[ULTRAMARINE] * size for _ in range(size)]

    def box(x0, y0, x1, y1, colour):
        for y in range(round(y0 * u), round(y1 * u)):
            for x in range(round(x0 * u), round(x1 * u)):
                if 0 <= x < size and 0 <= y < size:
                    px[y][x] = colour

    box(5, 8, 24, 21, CREAM)  # body
    box(7, 10, 12, 14, ULTRAMARINE)  # windows
    box(13, 10, 17, 14, ULTRAMARINE)
    box(18, 10, 22, 14, ULTRAMARINE)
    box(8, 20, 11, 23, CREAM)  # wheels
    box(18, 20, 21, 23, CREAM)
    raw = b"".join(b"\x00" + bytes(c for p in row for c in p) for row in px)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# ---- signing ---------------------------------------------------------------------------------------------


def _signer() -> dict:
    d = signing_dir()
    files = {"pass": d / "pass.pem", "key": d / "pass.key", "wwdr": d / "wwdr.pem"}
    missing = [p.name for p in files.values() if not p.exists()]
    if missing:
        raise UsageError(
            f"building a Wallet pass needs a Pass Type ID certificate from an Apple developer account in {d} "
            f"(missing: {', '.join(missing)}). ALSA's own pass is only offered right after buying; `buy` saves it then.",
            details={"wallet_dir": str(d), "missing": missing})
    if not shutil.which("openssl"):
        raise UsageError("signing a Wallet pass needs the `openssl` command")
    subject = subprocess.run(["openssl", "x509", "-in", str(files["pass"]), "-noout", "-subject", "-nameopt", "RFC2253"],
                             capture_output=True, text=True, check=False).stdout
    uid = re.search(r"UID=([^,\n]+)", subject)
    team = re.search(r"OU=([^,\n]+)", subject)
    if not (uid and team):
        raise UsageError(f"{files['pass']} isn't a Pass Type ID certificate (no pass type or team in its subject)")
    return {**files, "pass_type": uid.group(1).strip(), "team": team.group(1).strip()}


def _sign(manifest: bytes, s: dict) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        m, sig = Path(tmp) / "manifest.json", Path(tmp) / "signature"
        m.write_bytes(manifest)
        r = subprocess.run(["openssl", "smime", "-binary", "-sign", "-certfile", str(s["wwdr"]),
                            "-signer", str(s["pass"]), "-inkey", str(s["key"]), "-in", str(m),
                            "-out", str(sig), "-outform", "DER"], capture_output=True, text=True, check=False)
        if r.returncode != 0 or not sig.exists():
            raise UsageError("openssl couldn't sign the Wallet pass", details={"openssl": r.stderr.strip()[-300:]})
        return sig.read_bytes()


def package(pass_dict: dict, signer: dict) -> bytes:
    files = {"pass.json": json.dumps(pass_dict, ensure_ascii=False, indent=1).encode("utf-8"),
             "icon.png": _png(29), "icon@2x.png": _png(58), "icon@3x.png": _png(87)}
    manifest = json.dumps({k: hashlib.sha1(v).hexdigest() for k, v in files.items()}, indent=1).encode()
    files["manifest.json"] = manifest
    files["signature"] = _sign(manifest, signer)
    buf = tempfile.SpooledTemporaryFile()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    buf.seek(0)
    return buf.read()


# ---- commands --------------------------------------------------------------------------------------------


def _raw_tickets(client: AlsaClient, locator: str, document: str | None) -> list[dict]:
    doc = manage._document(client, document)
    urls = manage._info_urls(client)
    r = client.resource("/info", "", "jsonGetTicketDataResourceCommand", url=urls["jsonGetTicketDataURL"],
                        json_body={"localizador": locator.strip().lower(), "documentNumber": doc})
    if r.status_code == 404:
        raise UsageError("ALSA has no booking with that locator and document")
    if r.status_code != 200:
        raise ApiShapeError("the ticket lookup failed", status=r.status_code)
    return r.json() or []


def build(client: AlsaClient, locator: str, document: str | None, dest: Path) -> dict:
    """One .pkpass per passenger and leg. `dest` is a file for one pass, or the base name for several."""
    signer = _signer()
    loc = locator.strip().lower()
    items = []
    for t in _raw_tickets(client, loc, document):
        ticket = {"locator": t.get("locator") or loc, "passenger": t.get("paxFullName")}
        for way in ("outwardLegsData", "returnLegsData"):
            for i, raw in enumerate(t.get(way) or []):
                items.append((ticket, manage._leg(raw), raw, f"alsa-{loc}-{t.get('paxSequential', 0)}-{way[:1]}{i}"))
    if not items:
        raise UsageError("that booking has no journeys to put in Wallet")
    if not all(raw.get("qrText") for _, _, raw, _ in items):
        raise UsageError("ALSA's ticket lookup gave no boarding QR for this booking; use the PDF")
    saved = []
    for n, (ticket, leg, raw, serial) in enumerate(items, 1):
        path = dest if len(items) == 1 else dest.with_name(f"{dest.stem}-{n}{dest.suffix}")
        data = package(pass_json(ticket, leg, raw, pass_type=signer["pass_type"], team=signer["team"],
                                 serial=serial), signer)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        saved.append({"saved": str(path), "from": leg.get("from"), "to": leg.get("to"),
                      "departure": leg.get("departure"), "seat": leg.get("seat")})
    return {"locator": loc, "passes": saved, "made_by": "queguagua"}


def save_official(client: AlsaClient, wallet_url: str, count: int, dest: Path) -> list[str]:
    """ALSA's own passes, from the confirmation page's GetWalletResource (only while the purchase is fresh)."""
    p = config.PURCHASE_PORTLET
    saved = []
    for i in range(count):
        for param in (f"walletIndex={i}", f"_{p}_walletIndex={i}"):
            r = client.http.get(f"{wallet_url}&{param}", headers={"Accept": "application/vnd.apple.pkpass,*/*"})
            if r.status_code == 200 and r.content[:2] == b"PK":
                path = dest if count == 1 else dest.with_name(f"{dest.stem}-{i + 1}{dest.suffix}")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(r.content)
                saved.append(str(path))
                break
    return saved
