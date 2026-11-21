import pytest

from queguagua.alsa import search
from queguagua.alsa.errors import UsageError
from fakes import FakeAlsa, journey


def test_iso_local_uses_the_stop_offset():
    # 27/11/2026 01:30 in Madrid is 00:30 UTC
    assert search.iso_local(1795739400000, "27/11/2026 01:30") == "2026-11-27T01:30:00+01:00"
    # Canarias (UTC+0 in winter): same epoch, wall time 00:30
    assert search.iso_local(1795739400000, "27/11/2026 00:30") == "2026-11-27T00:30:00+00:00"


def test_passenger_params_and_validation():
    p = search.Passengers(adults=2, young=1, children=1, babies=1)
    # 2 adults + 1 young + 1 child + 1 baby, as ALSA's own form builds it
    assert p.params() == {"passengerType-1": "2", "passengerType-2": "1", "passengerType-3": "1", "passengerType-4": "1"}
    assert p.seats == 5
    with pytest.raises(UsageError):  # a baby needs an adult, young or senior
        search.Passengers(adults=0, babies=1, children=1).validate()
    assert search.SearchRequest(origin={"id": "1"}, destination={"id": "2"}, departure=None,
                                return_date=object()).travel_type == "RETURN"
    with pytest.raises(UsageError):
        search.Passengers(adults=0).validate()


def test_normalize_journey_fields():
    j = search.normalize_journey(journey(), "I")
    assert j["departure"].startswith("2026-11-27T08:00") and j["duration_minutes"] == 300
    assert j["available"] and j["cheapest"] == 23.28 and j["abono_unico_ok"] and j["double_decker"]
    assert j["fares"][0]["name"] == "SUPER FLEX" and j["pets"] == "available"


def _req(**kw):
    from queguagua.alsa import config, stations

    return search.SearchRequest(origin=stations.resolve("Granada"), destination=stations.resolve("Madrid"),
                                departure=config.parse_date("2026-11-27"), **kw)


def test_run_lists_filters_and_prices_packages():
    fake = FakeAlsa()
    with fake.client() as c:
        out = search.run(c, _req(), search.Filters(after="08:30"), packages=True)
    assert out["count"] == 2 and out["shown"] == 1
    assert out["journeys"][0]["service"] == ["Supra"]
    assert [p["name"] for p in out["journeys"][0]["packages"]] == ["Básica", "Flexible"]
    assert ("GET", "/checkout", "SearchJourneysAction") in fake.calls


def test_invalid_promo_code_is_a_usage_error_with_alsa_message():
    fake = FakeAlsa()
    with fake.client() as c, pytest.raises(UsageError) as e:
        search.run(c, _req(promo_code="BAD"), search.Filters())
    assert "inexistente" in e.value.alsa_message


def test_queue_it_bounce_is_followed_and_request_resent():
    fake = FakeAlsa()
    fake.queue_once = True
    with fake.client() as c:
        out = search.run(c, _req(), search.Filters())
    assert out["count"] == 2
    assert sum(1 for m, p, r in fake.calls if r == "GetJourneyListResource") == 2


def test_parse_date_weekdays():
    from queguagua.alsa import config
    from datetime import date
    viernes = date(2026, 11, 20)  # un viernes
    assert config.parse_date("viernes", now=viernes) == date(2026, 11, 27)
    assert config.parse_date("Friday", now=viernes) == date(2026, 11, 27)
    assert config.parse_date("sábado", now=viernes) == date(2026, 11, 21)
    assert config.parse_date("jueves", now=viernes) == date(2026, 11, 26)
    assert config.parse_date("mañana", now=viernes) == date(2026, 11, 21)


def test_maintenance_page_is_reported():
    import httpx
    import pytest
    from queguagua.alsa.client import AlsaClient
    from queguagua.alsa.errors import MaintenanceError
    html = "<!doctype html><html><head><title>Lo sentimos, en estos momentos estamos realizando mejoras en nuestro sistema - ALSA</title></head><body></body></html>"
    r = httpx.Response(200, text=html, headers={"content-type": "text/html"}, request=httpx.Request("GET", "https://www.alsa.es/"))
    with pytest.raises(MaintenanceError) as e:
        AlsaClient._check_block(object.__new__(AlsaClient), r)
    assert e.value.to_dict()["type"] == "maintenance"
    assert "hint" in e.value.to_dict()
