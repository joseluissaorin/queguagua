"""Paths, time zone and fixed values shared by every module."""

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = "https://www.alsa.es"
MADRID = ZoneInfo("Europe/Madrid")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/157.0.0.0 Safari/537.36"
)
TIMEOUT = 25.0

CACHE_ENV = "ALSA_CACHE_DIR"
CONFIG_ENV = "ALSA_CONFIG_DIR"

# Keychain item (macOS `security`) holding the Alsa Plus password; its account is the login email/DNI.
KEYCHAIN_SERVICE = "queguagua-alsa"

PURCHASE_PORTLET = "com_babel_alsa_espania_purchase_web_PurchasePortlet"
JOURNEY_SEARCH_PORTLET = "com_babel_alsa_espania_journeysearch_web_JourneySearchPortlet_INSTANCE_21651890"
LOGIN_PORTLET = "com_babel_alsa_alsaplus_AlsaplusAuthLoginPortlet_INSTANCE_linkMenuLoginForm"

MAX_PASSENGERS = 20


def cache_dir() -> Path:
    if os.environ.get(CACHE_ENV):
        return Path(os.environ[CACHE_ENV])
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "queguagua" / "alsa"


def config_dir() -> Path:
    if os.environ.get(CONFIG_ENV):
        return Path(os.environ[CONFIG_ENV])
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "queguagua" / "alsa"


def today() -> date:
    return datetime.now(MADRID).date()


def parse_date(value: str) -> date:
    """YYYY-MM-DD, DD/MM/YYYY, `today`, `tomorrow`, `hoy` or `mañana`."""
    from .errors import UsageError

    v = value.strip().lower()
    if v in ("today", "hoy"):
        return today()
    if v in ("tomorrow", "mañana", "manana"):
        return today() + timedelta(days=1)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    raise UsageError(f"bad date {value!r}: use YYYY-MM-DD, DD/MM/YYYY, today or tomorrow")


def alsa_date(d: date) -> str:
    return d.strftime("%d/%m/%Y")
