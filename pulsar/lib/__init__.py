#First try local
try:
    from ._pulsar import *
    hasextensions = True
except ImportError:
    # Try Global
    try:
        from _pulsar import *
        hasextensions = True
    except ImportError:
        hasextensions = False
        from .fallback import *

from . import fallback
