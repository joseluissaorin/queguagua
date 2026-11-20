import json

from typer.testing import CliRunner

from queguagua.alsa import cli
from fakes import FakeAlsa

runner = CliRunner()


def test_search_prints_json(monkeypatch):
    fake = FakeAlsa()
    monkeypatch.setattr(cli, "make_client", fake.client)
    r = runner.invoke(cli.app, ["search", "Granada", "Madrid", "-d", "2026-11-27"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["count"] == 2 and out["journeys"][0]["cheapest"] == 23.28


def test_unknown_stop_exit_2(monkeypatch):
    fake = FakeAlsa()
    monkeypatch.setattr(cli, "make_client", fake.client)
    r = runner.invoke(cli.app, ["search", "Xyzzyville", "Madrid"])
    assert r.exit_code == 2
    assert json.loads(r.stderr)["error"]["type"] == "usage"


def test_login_with_wrong_password_is_auth_error(monkeypatch):
    fake = FakeAlsa()
    monkeypatch.setattr(cli, "make_client", fake.client)
    r = runner.invoke(cli.app, ["login", "--user", "test@example.com", "--password-stdin"], input="wrong\n")
    assert r.exit_code == 3
    assert json.loads(r.stderr)["error"]["alsa_message"] == "Contraseña incorrecta."


def test_login_then_whoami(monkeypatch):
    fake = FakeAlsa()
    monkeypatch.setattr(cli, "make_client", fake.client)
    r = runner.invoke(cli.app, ["login", "--user", "test@example.com", "--password-stdin"], input="right\n")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["status"] == "logged_in" and out["account"]["level"] == "Plata"


def test_stations_offline():
    r = runner.invoke(cli.app, ["stations", "oviedo", "--limit", "1"])
    assert r.exit_code == 0
    assert json.loads(r.stdout)["stations"][0]["name"].lower().startswith("oviedo")


def test_top_level_groups_companies():
    from queguagua import cli as top

    r = runner.invoke(top.app, ["empresas"])
    assert r.exit_code == 0
    assert json.loads(r.stdout)["companies"][0]["id"] == "alsa"
    r = runner.invoke(top.app, ["alsa", "stations", "granada", "--limit", "1"])
    assert r.exit_code == 0 and json.loads(r.stdout)["stations"][0]["id"] == "99084"
