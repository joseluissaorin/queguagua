"""Wallet passes: what goes on the pass, how it's signed and packed, and what `buy` saves after buying."""

import hashlib
import io
import json
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path

import pytest

from queguagua.alsa import config, purchase, wallet

RAW_LEG = {
    "qrText": "ALSA*1abcdef*155*9084*20261122*1930*24",
    "journey": {"originId": "155", "originName": "MADRID ESTACION SUR", "destinationId": "9084",
                "destinationName": "GRANADA ESTACIÓN DE AUTOBÚS", "originAddress": "ESTACION SUR, MADRID",
                "destinationAddress": "AVENIDA JUAN PABLO II 33, GRANADA", "originLatitude": "40.3950",
                "originLongitude": "-3.6782", "departureDateStrGeneral": "22/11/2026", "departureTime": "19:30",
                "arrivalDateStrGeneral": "23/11/2026", "arrivalTime": "00:30", "serviceType": "Normal",
                "fareName": "Superflexible Abono Único"},
    "bus": {"assignedSeatNumber": "24", "platform": "37", "statusCode": 0},
    "packageObservationsOther": [{"description": "<p>Cambios y anulaciones permitidos hasta 2h antes</p>"}],
}


def _pass():
    from queguagua.alsa import manage

    leg = manage._leg(RAW_LEG)
    return wallet.pass_json({"locator": "1abcdef", "passenger": "Ana Pérez"}, leg, RAW_LEG,
                            pass_type="pass.es.example", team="TEAM123", serial="alsa-1abcdef-1-o0")


def test_the_pass_carries_the_boarding_qr_and_the_trip():
    p = _pass()
    bp = p["boardingPass"]
    assert p["barcodes"][0] == {"format": "PKBarcodeFormatQR", "message": RAW_LEG["qrText"],
                                "messageEncoding": "iso-8859-1"}
    assert bp["transitType"] == "PKTransitTypeBus"
    assert [(f["label"], f["value"]) for f in bp["primaryFields"]] == [
        ("ESTACIÓN SUR", "Madrid"), ("ESTACIÓN DE AUTOBUSES", "Granada")]  # the catalogue's names, accents and all
    fields = {f["key"]: f["value"] for f in bp["secondaryFields"] + bp["auxiliaryFields"] + bp["headerFields"]}
    assert fields["departure"] == "2026-11-22T19:30:00+01:00"
    assert fields["arrival"] == "2026-11-23T00:30:00+01:00"
    assert (fields["seat"], fields["platform"], fields["locator"]) == ("24", "37", "1ABCDEF")
    assert p["relevantDate"] == "2026-11-22T19:30:00+01:00"
    assert p["locations"][0]["latitude"] == pytest.approx(40.395)
    assert "Cambios y anulaciones" in next(f["value"] for f in bp["backFields"] if f["key"] == "conditions")


def test_icons_are_real_pngs_of_the_right_size():
    for size in (29, 58, 87):
        png = wallet._png(size)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", png[16:24]) == (size, size)


def _self_signed(folder: Path) -> None:
    def cert(name: str, subj: str) -> None:
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                        "-subj", subj, "-keyout", str(folder / f"{name}.key"), "-out", str(folder / f"{name}.pem")],
                       check=True, capture_output=True)

    folder.mkdir(parents=True)
    cert("pass", "/UID=pass.es.example/CN=Pass Type ID: pass.es.example/OU=TEAM123/O=Test/C=ES")
    cert("wwdr", "/CN=Test WWDR/O=Test/C=ES")


@pytest.mark.skipif(not shutil.which("openssl"), reason="needs openssl")
def test_a_signed_pkpass_with_a_matching_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv(config.CONFIG_ENV, str(tmp_path))
    _self_signed(tmp_path / "wallet")
    signer = wallet._signer()
    assert (signer["pass_type"], signer["team"]) == ("pass.es.example", "TEAM123")  # read from the certificate
    data = wallet.package(_pass(), signer)
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    assert {"pass.json", "manifest.json", "signature", "icon.png", "icon@2x.png", "icon@3x.png"} <= names
    manifest = json.loads(z.read("manifest.json"))
    assert all(hashlib.sha1(z.read(n)).hexdigest() == h for n, h in manifest.items())
    (tmp_path / "m.json").write_bytes(z.read("manifest.json"))
    (tmp_path / "sig").write_bytes(z.read("signature"))
    r = subprocess.run(["openssl", "smime", "-verify", "-binary", "-inform", "DER", "-noverify",
                        "-in", str(tmp_path / "sig"), "-content", str(tmp_path / "m.json"), "-out", "/dev/null"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_without_a_certificate_it_says_what_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv(config.CONFIG_ENV, str(tmp_path))
    with pytest.raises(Exception) as e:
        wallet._signer()
    assert "pass.pem" in str(e.value) and "right after buying" in str(e.value)


def test_buy_saves_the_pdf_and_alsas_pass_and_never_fails_for_them(tmp_path, monkeypatch):
    saved = {}
    monkeypatch.setattr(purchase.confirmation, "download_pdf",
                        lambda client, url, dest: saved.setdefault("pdf", Path(dest)).write_bytes(b"%PDF") or 4)
    monkeypatch.setattr(wallet, "save_official", lambda client, url, n, dest: [str(dest)])
    out = {"status": "confirmed", "locator": "1abcdef", "ticket_pdf_url": "u", "wallet_pass_url": "w",
           "wallet_passes": [{"index": 0}]}
    files = purchase.save_tickets(None, out, tmp_path)
    assert files == {"pdf": str(tmp_path / "alsa-1abcdef.pdf"), "wallet": [str(tmp_path / "alsa-1abcdef.pkpass")],
                     "wallet_by": "ALSA"}

    def boom(*a, **k):
        raise RuntimeError("ALSA is still issuing it")

    monkeypatch.setattr(purchase.confirmation, "download_pdf", boom)
    monkeypatch.setattr(wallet, "save_official", lambda *a: [])
    monkeypatch.setattr(wallet, "build", boom)
    files = purchase.save_tickets(None, out, tmp_path)
    assert files == {"later": ["queguagua alsa pdf 1abcdef", "queguagua alsa wallet 1abcdef"]}
