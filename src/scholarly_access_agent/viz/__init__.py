"""Vega-Lite charts from a topic folder's data files, each written as a small standalone HTML page plus its spec.

  scholarly-access-agent viz figure   TOPIC --spec figs/NAME.fig.json [-o figs/NAME.html]
  scholarly-access-agent viz effects  TOPIC --quantity REGEX [--unit U] [--band LO,HI --band-label TEXT]
  scholarly-access-agent viz adoption TOPIC [--id N]
  scholarly-access-agent viz timeline TOPIC

Each run writes figs/<name>.html (embed in a report with ![caption](figs/<name>.html)) and figs/<name>.vl.json.
"""
from __future__ import annotations

from .cli import main

__all__ = ["main"]
