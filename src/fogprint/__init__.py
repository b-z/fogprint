"""Fogprint: read Fog of World data and make it easy to analyse."""

__version__ = "0.1.0"

from . import geo  # noqa: E402
from .fogmap import FogMap  # noqa: E402
from .sources import Source, inspect, locate, pick_default  # noqa: E402

__all__ = ["geo", "FogMap", "Source", "inspect", "locate", "pick_default", "__version__"]
