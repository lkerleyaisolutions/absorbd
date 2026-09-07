"""Make the intake data modules importable from tests.

medication_map.py and symptom_deficiency_map.py live in data/intake/ and are
imported by name (not as a package), so we add that directory to sys.path.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data" / "intake"))
