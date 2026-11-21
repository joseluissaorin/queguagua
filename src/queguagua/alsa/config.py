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


WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    "lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2, "jueves": 3, "viernes": 4, "sabado": 5,
    "sábado": 5, "domingo": 6,
}


def parse_date(value: str, *, now: date | None = None) -> date:
    """YYYY-MM-DD, DD/MM/YYYY, `today`, `tomorrow`, `hoy`, `mañana` or a weekday (`friday`, `viernes`):
    the next one after today, so on a Friday `viernes` is a week away."""
    from .errors import UsageError

    v = value.strip().lower()
    base = now or today()
    if v in ("today", "hoy"):
        return base
    if v in ("tomorrow", "mañana", "manana"):
        return base + timedelta(days=1)
    if v in WEEKDAYS:
        return base + timedelta(days=(WEEKDAYS[v] - base.weekday() - 1) % 7 + 1)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    raise UsageError(f"bad date {value!r}: use YYYY-MM-DD, DD/MM/YYYY, today, tomorrow or a weekday")


def alsa_date(d: date) -> str:
    return d.strftime("%d/%m/%Y")
