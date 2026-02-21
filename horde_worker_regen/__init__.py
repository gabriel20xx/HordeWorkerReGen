"""The primary package for the reGen worker."""

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv is not installed yet, which is fine during initial import
    # Dependency checking is handled elsewhere during startup
    pass

from pathlib import Path  # noqa: E402

ASSETS_FOLDER_PATH = Path(__file__).parent / "assets"

__version__ = "10.1.2"
