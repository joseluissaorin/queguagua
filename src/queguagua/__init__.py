"""queguagua: ¿qué guagua cojo? Spanish buses from the terminal, JSON first.

Each bus company lives in its own subpackage (`queguagua.alsa` is the first) and shows up as a command
group: `queguagua alsa search Granada Madrid`.
"""

try:
    from importlib.metadata import version as _version

    package_version = _version("queguagua")
except Exception:  # pragma: no cover
    package_version = "0.0.0"
