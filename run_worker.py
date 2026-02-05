"""Entry point for the Horde Worker reGen."""

import sys

try:
    from horde_worker_regen.run_worker import init
except ImportError as e:
    print("=" * 80)
    print("ERROR: Failed to import required modules")
    print("=" * 80)
    print()
    print(f"Import error: {e}")
    print()
    print("This worker requires dependencies to be installed.")
    print()
    print("Please run the worker using one of the provided scripts:")
    print("  - On Linux/Mac:  ./horde-bridge.sh")
    print("  - On Windows:    horde-bridge.cmd")
    print()
    print("These scripts will automatically set up the required environment.")
    print()
    print("If you are developing, install dependencies with:")
    print("  pip install -r requirements.txt")
    print("=" * 80)
    sys.exit(1)

if __name__ == "__main__":
    init()
