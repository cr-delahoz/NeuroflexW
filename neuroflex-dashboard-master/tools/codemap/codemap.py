"""Punto de entrada: python tools/codemap/codemap.py {scan,report,serve} [opciones]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codemap_core.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
