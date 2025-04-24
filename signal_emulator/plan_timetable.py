from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from signal_emulator.controller import BaseCollection
from signal_emulator.enums import Cell
from signal_emulator.utilities.utility_functions import read_fixed_width_file, clean_site_number, filter_pja_file

if TYPE_CHECKING:
    from signal_emulator.emulator import SignalEmulator


@dataclass(eq=False)
class PlanTimetable:
    signal_emulator: SignalEmulator
    site_number: str
    subgroup: str
    region: str
    wat: str
    control: str
    ctv: str
    sco: str
    status: str
    period: str
    cell: str

    def __repr__(self):
        return f"PJA: {self.site_number=} {self.period=} {self.wat=}"

    @staticmethod
    def clean_pja_site_number(site_number):
        return f"{site_number[:4]}000{site_number[-3:]}"

    @property
    def site_number_int(self):
        parts = self.site_number.split("/")
        if parts[0][0].isalpha():
            parts[0] = parts[0][1:]
        return int(parts[0]) * 1000 + int(parts[1])

    @property
    def site_number_long(self):
        site_number_parts = self.site_number.split("/")
        return f"{site_number_parts[0]}/000{site_number_parts[1][-3:]}"

    def get_key(self):
        return self.site_number, self.period

    @property
    def wat_plan_number(self):
        if self.wat.startswith("SC"):
            return int(self.wat[2:])
        else:
            return None

    @property
    def wat_plan(self):
        return self.signal_emulator.plans.get_by_key((self.site_number, self.wat_plan_number))

    @property
    def control_plan_number(self):
        if self.control.startswith("SC"):
            return int(self.control[2:])
        else:
            return None

    @property
    def control_plan(self):
        return self.signal_emulator.plans.get_by_key((self.site_number, self.control_plan_number))


class PlanTimetables(BaseCollection):
    PJA_COLUMN_WIDTHS = [10, 10, 7, 7, 7, 7, 5, 50]
    TABLE_NAME = "plan_timetables"
    ITEM_CLASS = PlanTimetable
    WRITE_TO_DATABASE = True

    def __init__(self, signal_emulator, pja_directory_path=None):
        super().__init__(item_data=[], signal_emulator=signal_emulator)
        self.signal_emulator = signal_emulator
        if pja_directory_path:
            self.load_from_pja_directory(pja_directory_path)

    def load_from_pja_directory(self, pja_directory_path):
        for period in self.signal_emulator.time_periods:
            for cell in Cell:
                pja_filepath = os.path.join(pja_directory_path, period.name, f"{cell.name}_{period.name}.txt")
                if os.path.exists(pja_filepath):
                    self.init_from_pja_file(pja_filepath, period, cell)
                else:
                    self.signal_emulator.logger.warning(f"PJA file: {pja_filepath} does not exist")

    def init_from_pja_file(self, pja_filepath, period, cell):
        pja_data = read_fixed_width_file(pja_filepath, self.PJA_COLUMN_WIDTHS)
        filtered_pja_data = filter_pja_file(pja_data, "JUNS")
        for row in filtered_pja_data:
            item_dict = {
                "site_number": clean_site_number(row[0]),
                "subgroup": row[1],
                "region": row[2],
                "wat": row[3],
                "control": row[4],
                "ctv": row[5],
                "sco": row[6],
                "status": row[7].split(),
                "period": period.name,
                "cell": cell.name,
            }
            self.add_item(item_dict, signal_emulator=self.signal_emulator)
