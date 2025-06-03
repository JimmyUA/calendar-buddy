"""Simplified stub of dateutil providing parser.isoparse and relativedelta."""
from types import ModuleType
import sys

from . import parser, relativedelta

__all__ = ["parser", "relativedelta"]
