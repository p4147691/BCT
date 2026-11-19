"""Compatibility alias; implementation is independent of the BCT application."""
import sys
from bct_maintenance import service_runtime as _implementation
sys.modules[__name__] = _implementation
