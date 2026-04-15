"""The primary package for the reGen worker."""

import os
from pathlib import Path

ASSETS_FOLDER_PATH = Path(__file__).parent / "assets"

__version__ = "10.1.2"

# Load .env file if it exists (simple native implementation)
_env_file = Path(".env")
if _env_file.exists():
    with open(_env_file, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _, _value = _line.partition("=")
            _key = _key.strip()
            _value = _value.strip()
            if _value and _value[0] in ('"', "'") and len(_value) >= 2 and _value[-1] == _value[0]:
                _value = _value[1:-1]
            os.environ.setdefault(_key, _value)
