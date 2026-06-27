import sys
from pathlib import Path

# Add scripts/ to sys.path so tests can import from the scripts directory
_scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))
