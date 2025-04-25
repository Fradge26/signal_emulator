from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional
from typing import TYPE_CHECKING

import numpy as np

from signal_emulator.controller import BaseCollection
from signal_emulator.utilities.utility_functions import time_str_to_timedelta

if TYPE_CHECKING:
    from signal_emulator.emulator import SignalEmulator


@dataclass(eq=False)
class TimePeriod:
    """
    Class to represent a time Period.
    """

    name: str
    index: int
    start_time_str: str
    end_time_str: str
    long_name: Optional[str] = None
    signal_emulator: Optional[SignalEmulator] = None

    def __post_init__(self):
        self.start_time = time_str_to_timedelta(self.start_time_str)
        self.end_time = time_str_to_timedelta(self.end_time_str)

    def get_key(self):
        return self.name

    @property
    def mid_time(self):
        return (self.start_time + self.end_time) / 2

    @staticmethod
    def timedelta_to_string(time_delta):
        hours, remainder = divmod(time_delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    @property
    def total_seconds(self):
        return (self.end_time - self.start_time).total_seconds()


class TimePeriods(BaseCollection):
    """
    Class to represent time periods
    """

    TABLE_NAME = "time_periods"
    ITEM_CLASS = TimePeriod
    WRITE_TO_DATABASE = True

    def __init__(self, periods_data, signal_emulator=None):
        """
        Constructor for Periods class.
        It is a subclass of BaseCollection so serves as a collection of Period objects
        :param periods_data: list of dict containing Period definitions
        """
        super().__init__(item_data=periods_data, signal_emulator=signal_emulator)
        self.active_period_id = None

    @classmethod
    def init_from_arg_list(cls, periods_list, signal_emulator):
        processed_args = []
        for period_record in periods_list:
            processed_args.append(
                {
                    "name": period_record["name"],
                    "index": period_record["number"],
                    "start_time_str": time_str_to_timedelta(period_record["start_time_str"]),
                    "end_time_str": time_str_to_timedelta(period_record["end_time_str"]),
                }
            )
        return cls(processed_args, signal_emulator)

    @property
    def active_period_id(self):
        return self._active_period_id

    @active_period_id.setter
    def active_period_id(self, value):
        self._active_period_id = value

    @property
    def active_period(self):
        return self.data[self._active_period_id]

    def get_periods_for_timedelta(self, target_timedelta: timedelta):
        """
        Function to return a list of Periods that contain target_timedelta
        :param target_timedelta: timedelta
        :return: list of Period objects
        """
        periods_list = []
        for period in self:
            if period.start_time <= target_timedelta <= period.end_time:
                periods_list.append(period)
        return periods_list

    def get_period_id_for_timedelta(self, target_timedelta: timedelta):
        """
        Function to return a list of Periods that contain target_timedelta
        :param target_timedelta: timedelta
        :return: list of Period objects
        """
        for period in self:
            if period.start_time <= target_timedelta <= period.end_time:
                return period.name
        return np.NAN


if __name__ == "__main__":
    periods = TimePeriods(
        [
            {"name": "AM", "index": 1, "start_time_str": "08:00:00", "end_time_str": "09:00:00"},
            {"name": "IP", "index": 2, "start_time_str": "10:00:00", "end_time_str": "16:00:00"},
            {"name": "PM", "index": 3, "start_time_str": "16:00:00", "end_time_str": "19:00:00"},
        ]
    )
