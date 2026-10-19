"""EITAI ELEBOX-HV internal BMS CAN bus decoder."""
from .protocol import BITRATE, Frame, parse_candump_line
from .state import BatteryState, ModuleState

__all__ = ["BITRATE", "Frame", "parse_candump_line", "BatteryState", "ModuleState"]
__version__ = "0.2.0"
