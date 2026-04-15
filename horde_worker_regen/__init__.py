"""The primary package for the reGen worker."""

from pathlib import Path

ASSETS_FOLDER_PATH = Path(__file__).parent / "assets"

__version__ = "10.1.2"

# Load .env file if it exists
from horde_worker_regen.load_env_vars import load_dotenv as _load_dotenv  # noqa: E402

_load_dotenv()
