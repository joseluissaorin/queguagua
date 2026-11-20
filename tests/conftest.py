import sys
from pathlib import Path

import httpx
import pytest

from queguagua.alsa import config

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def no_real_network(request, monkeypatch):
    """Offline tests never reach ALSA: every request must go through a MockTransport."""
    if request.node.get_closest_marker("live"):
        return

    def refuse(self, req):
        raise AssertionError(f"a test tried to reach the real network ({req.url.host})")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path_factory, monkeypatch):
    """No test reads or writes the real session, keychain-backed login or caches."""
    monkeypatch.setenv(config.CACHE_ENV, str(tmp_path_factory.mktemp("cache")))
    monkeypatch.setenv(config.CONFIG_ENV, str(tmp_path_factory.mktemp("config")))
    monkeypatch.delenv("ALSA_USER", raising=False)
    monkeypatch.delenv("ALSA_PASSWORD", raising=False)
    from queguagua.alsa import secrets

    monkeypatch.setattr(secrets, "keychain_account", lambda: None)
    monkeypatch.setattr(secrets, "keychain_password", lambda account: None)
