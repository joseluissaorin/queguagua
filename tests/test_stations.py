import pytest

from queguagua.alsa import stations
from queguagua.alsa.errors import UsageError


def test_city_name_prefers_the_group():
    best = stations.search("granada", limit=1)[0]
    assert best["id"] == "99084" and best["group"] is True


def test_accents_and_case_are_ignored():
    assert stations.search("MÁDRID", limit=1)[0]["id"] == "90155"
    assert stations.search("almeria", limit=1)[0]["id"] == "91600"


def test_child_stop_is_findable_and_points_to_its_group():
    sur = stations.search("madrid estacion sur", limit=1)[0]
    assert sur["id"] == "155" and sur["in_group"] == "90155"


def test_id_lookup():
    assert stations.resolve("99084")["name"].startswith("Granada")


def test_unknown_stop_suggests():
    with pytest.raises(UsageError) as e:
        stations.resolve("Granadda")
    assert "Granada" in " ".join(e.value.details["suggestions"])
