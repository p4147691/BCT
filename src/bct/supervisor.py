"""Compatibility module and entrypoint for existing installations."""
import sys
from bct_maintenance import supervisor as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
else:
    sys.modules[__name__] = _implementation
