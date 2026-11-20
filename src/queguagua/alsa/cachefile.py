"""Small files under the cache dir: written atomically, readable only by this user."""

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_atomic(path: Path, text: str | bytes) -> None:
    """Replace `path` with `text` in one step (mode 0600). A cache that can't be written only costs a
    refetch next time, so failures are swallowed."""
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp")  # mode 0600
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8") if isinstance(text, str) else text)
        os.replace(tmp, path)
        tmp = None
    except (OSError, UnicodeError):
        pass
    finally:
        if tmp is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path: Path, data: Any) -> None:
    write_atomic(path, json.dumps(data, ensure_ascii=False))


def remove(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()
