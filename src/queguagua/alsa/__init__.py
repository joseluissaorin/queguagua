"""queguagua.alsa: ALSA (alsa.es), the first bus company in queguagua."""

try:
    from importlib.metadata import version as _version

    package_version = _version("queguagua")
except Exception:  # pragma: no cover
    package_version = "0.0.0"
