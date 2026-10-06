"""Invoked with Python isolated mode from the self-contained app bundle."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from erasure.desktop import main  # noqa: E402

main()
