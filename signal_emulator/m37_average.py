from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from signal_emulator.controller import BaseCollection
from signal_emulator.enums import M37StageToStageNumber
from signal_emulator.time_period import TimePeriods
from signal_emulator.utilities.utility_functions import clean_site_number, find_files_with_extension

if TYPE_CHECKING:
    from signal_emulator.emulator import SignalEmulator


@dataclass(eq=False)
class M37Average:
    """
    Class to represent M37 signal timing information for one node, site and stage combination
    """

    signal_emulator: SignalEmulator
    node_id: str
    site_id: str
    utc_stage_id: str
    stage_number: int
    period_id: str
    green_time: int
    interstage_time: int
    cycle_time: int

    def __repr__(self):
        return f"M37: {self.site_id=} {self.utc_stage_id=} {self.green_time=} {self.interstage_time=}"

    def get_key(self):
        return self.site_id, self.stage_number, self.period_id

    @staticmethod
    def clean_site_id(site_id):
        return site_id.replace("P", "J")

    @property
    def total_time(self):
        return self.green_time + self.interstage_time


class M37Averages(BaseCollection):
    """
    Class to represent a collection of M37 objects
    """

    TABLE_NAME = "m37_averages"
    ITEM_CLASS = M37Average
    WRITE_TO_DATABASE = True
    COLUMN_DTYPES = {"FinalGreenTime": int, "final_interstage_time": int, "scoot_cycle_time": int}
    CSV_COLUMN_RENAME = {
        "UtcDateTimestamp": "timestamp",
        "MessageId": "message_id",
        "UtcStageId": "utc_stage_id",
        "Length": "length",
        "NodeId": "node_id",
        "SiteId": "site_id",
        "Gn": "green_time",
        "Ig": "intergreen_time",
    }

    COLUMN_LIMITS = [(0, 8), (13, 16), (18, 26), (28, 35), (41, 43), (47, 50), (55, 58), (67, 70)]
    COLUMN_NAMES = [
        "timestamp",
        "message_id",
        "node_id",
        "site_id",
        "utc_stage_id",
        "intergreen_time",
        "green_time",
        "length",
    ]
    HEADER_ROWS = [0, 1]

    def __init__(
        self,
        m37_path,
        periods,
        source_type="averaged",
        export_to_csv_path=None,
        signal_emulator=None,
    ):
        """

        :param m37_path: directory to load M37 data from
        :param periods: parent SignalEmulator object
        """
        super().__init__(item_data=[], signal_emulator=signal_emulator)
        if signal_emulator.load_from_postgres:
            return
        assert source_type in ("averaged", "raw", None)
        self.periods = periods
        if source_type is None:
            self.m37_df = pd.DataFrame()
        elif source_type == "raw":
            self.m37_data = self.load_all_m37_in_directory_df(m37_path)
            self.m37_df = self.calculate_average_signal_timings()
        elif source_type == "averaged":
            self.m37_df = pd.read_csv(
                m37_path,
                dtype=self.COLUMN_DTYPES,
            )
        self.data = {}
        for row in self.m37_df.to_dict(orient="records"):
            m37 = M37Average(**row, signal_emulator=signal_emulator)
            self.data[m37.get_key()] = m37

        if export_to_csv_path:
            self.write_to_csv(export_to_csv_path)

    def get_cycle_time_by_site_id_and_period_id(self, site_id, period_id):
        for stage_id, stage_number in M37StageToStageNumber.__members__.items():
            if self.key_exists((site_id, stage_number, period_id)):
                return self.get_by_key((site_id, stage_number, period_id)).cycle_time
        else:
            return None

    def calculate_average_signal_timings(self):
        """
        Function to return a DataFrame of averaged M37 signal timings
        :return: DataFrame of M37 timings
        """
        m37_all = pd.DataFrame()
        for period in self.periods:
            # filter M37s to the time bounds of the time Period
            m37_filtered = self.m37_data.between_time(start_time=period.start_time_str, end_time=period.end_time_str)
            # Group by NodeId, site_id and utc_stage_id
            m37_grouped_node_site_stage = m37_filtered.groupby(["node_id", "site_id", "utc_stage_id"])
            # aggregate to get the number of occurrences, average green time and total green times
            m37 = m37_grouped_node_site_stage.agg(
                occurrences=("intergreen_time", "count"),
                interstage_total=("intergreen_time", "sum"),
                interstage_average=("intergreen_time", "mean"),
                green_total=("green_time", "sum"),
                green_average=("green_time", "mean"),
            )
            m37["start_timestamp"] = period.start_time
            m37["end_timestamp"] = period.end_time
            m37["period_id"] = period.name
            m37["stage_total"] = m37["green_total"] + m37["interstage_total"]
            m37_cycles = m37_grouped_node_site_stage.size().groupby(["node_id", "site_id"]).agg(cycles="max")
            m37 = m37.merge(m37_cycles, left_index=True, right_index=True, how="outer")
            total_times = m37.groupby(["node_id", "site_id"]).agg(total_time=("stage_total", "sum"))
            total_times["coverage"] = total_times["total_time"] / period.total_seconds
            m37 = m37.merge(total_times, left_index=True, right_index=True, how="outer")
            # Calculate the proportion og stage occurrences to the total number of cycles
            m37["occurrence_factor"] = m37["occurrences"] / m37["cycles"]
            # Apply occurrence factor to the green times and interstage times
            m37["adjusted_green_average"] = m37["green_average"] * m37["occurrence_factor"]
            m37["adjusted_interstage_average"] = m37["interstage_average"] * m37["occurrence_factor"]
            m37_cycle_time = m37.groupby(["node_id", "site_id"]).agg(
                adjusted_green_average_sum=("adjusted_green_average", "sum"),
                adjusted_interstage_average_sum=("adjusted_interstage_average", "sum"),
            )
            # sum the adjusted green times and interstage times to get the cycle time
            m37_cycle_time["m37_cycle_time"] = (
                m37_cycle_time["adjusted_green_average_sum"] + m37_cycle_time["adjusted_interstage_average_sum"]
            )
            m37 = m37.merge(
                m37_cycle_time["m37_cycle_time"],
                left_index=True,
                right_index=True,
                how="outer",
            )

            m37.reset_index(inplace=True)
            m37.set_index("node_id", inplace=True)
            m16_cycle_times = self.signal_emulator.m16s.m16_average_df
            m16_cycle_times = m16_cycle_times[m16_cycle_times["time_period_id"] == period.name]
            m16_cycle_times.set_index("node_id", inplace=True)
            m37 = m37.join(m16_cycle_times[["node_cycle_time", "single_double_triple", "cycle_time_independent"]])
            if len(m37[m37["node_cycle_time"].isna()]) > 0:
                self.signal_emulator.logger.warning(
                    f"M16 ids not matched in M16s for nodes: "
                    f'{m37[m37["node_cycle_time"].isna()]["site_id"].unique()}'
                )
                m37.dropna(inplace=True)

            # factor green times and interstage times to match the SCOOT cycle time
            m37["scoot_green_time"] = m37["node_cycle_time"] / m37["m37_cycle_time"] * m37["adjusted_green_average"]
            m37["scoot_interstage_time"] = (
                m37["node_cycle_time"] / m37["m37_cycle_time"] * m37["adjusted_interstage_average"]
            )
            m37.reset_index(inplace=True)
            m37.set_index(["node_id", "site_id", "utc_stage_id"], inplace=True)
            # unstack the utc_stage_id from the row index to a column so that the stage times can be rounded together
            m37_unstack = m37[["scoot_green_time", "scoot_interstage_time"]].unstack(level=2)

            # apply rounding function that rounds times to whole seconds,
            # while maintaining the total (cycle time)
            m37_unstack = m37_unstack.apply(lambda x: self.rounding_function(x), axis=1)
            m37_stack = m37_unstack.stack()
            m37_stack.rename(
                columns={
                    "scoot_green_time": "final_green_time",
                    "scoot_interstage_time": "final_interstage_time",
                },
                inplace=True,
            )
            m37 = m37.merge(m37_stack, left_index=True, right_index=True, how="outer")
            m37.reset_index(inplace=True)
            m37_all = pd.concat([m37_all, m37], ignore_index=True)

            print(m37_all[m37_all["final_green_time"].isna()])

            m37_all["green_time"] = m37_all["final_green_time"].astype(int)
            m37_all["interstage_time"] = m37_all["final_interstage_time"].astype(int)
            m37_all["cycle_time"] = m37_all["node_cycle_time"].astype(int)
        m37_all["stage_number"] = m37_all["utc_stage_id"].apply(self.map_utc_stage_id_to_number)
        m37_all["site_id"] = m37_all["site_id"].apply(lambda x: clean_site_number(x))
        m37_all = m37_all[
            [
                "node_id",
                "site_id",
                "utc_stage_id",
                "stage_number",
                "period_id",
                "green_time",
                "interstage_time",
                "cycle_time",
            ]
        ]
        return m37_all

    @staticmethod
    def map_utc_stage_id_to_number(utc_stage_id):
        return M37StageToStageNumber[utc_stage_id].value

    @staticmethod
    def rounding_function(original_series):
        """
        Rounding function that rounds a set of values to whole seconds while maintaining
        the original total
        :param original_series:
        :return: Series of rounded values
        """

        def custom_round(value):
            """
            custom rounding function that ignores NaNs
            :param value: value
            :return: rounded value or NaN
            """

            if pd.notna(value):
                return round(value)
            else:
                return value

        # Calculate the original total sum
        original_total = int(round(original_series.sum(), 4))
        # Round the values
        rounded_series = original_series.apply(custom_round)
        rounded_total = int(rounded_series.sum())
        # Calculate the difference between rounded total and original total
        difference = original_total - rounded_total
        # Identify the indices with the largest differences
        indices_largest_diff = (original_series - rounded_series).abs().nlargest(int(abs(difference))).index
        # Adjust values at identified indices
        for index in indices_largest_diff:
            if difference > 0:
                rounded_series.at[index] += 1
            elif difference < 0:
                rounded_series.at[index] -= 1
        return rounded_series

    def load_all_m37_in_directory_df(self, directory_path):
        """
        Method to load all M37 files found in directory
        :param directory_path: path to directory
        :return: DataFrame of M37 data
        """
        m37_all_df = pd.DataFrame()
        file_paths = find_files_with_extension(directory_path, "csv")
        for file_path in file_paths:
            m37_df = pd.read_csv(file_path)
            m37_df.rename(columns=self.CSV_COLUMN_RENAME)
            m37_all_df = pd.concat([m37_all_df, m37_df], ignore_index=True)
        file_paths = find_files_with_extension(directory_path, "lsg")
        for file_path in file_paths:
            m37_df = self.read_m37_lsg_file_to_df(file_path)
            m37_all_df = pd.concat([m37_all_df, m37_df], ignore_index=True)
        m37_all_df["timestamp"] = pd.to_datetime(m37_all_df["timestamp"])
        m37_all_df.set_index("timestamp", inplace=True)
        return m37_all_df

    def read_m37_lsg_file_to_df(self, file_path):
        m37_df = pd.read_fwf(
            file_path,
            colspecs=self.COLUMN_LIMITS,
            skiprows=self.HEADER_ROWS,
            names=self.COLUMN_NAMES,
        )
        m37_df = m37_df[m37_df["message_id"] == "M37"]
        m37_df["green_time"] = m37_df["green_time"].astype(int)
        m37_df["length"] = m37_df["length"].astype(int)
        m37_df["intergreen_time"] = m37_df["intergreen_time"].astype(int)
        return m37_df


if __name__ == "__main__":
    m37_averages = M37Averages(
        m37_path="../signal_emulator/resources/M37/raw",
        source_type="raw",
        periods=TimePeriods(
            [
                {"name": "AM", "start_time_str": "08:00:00", "end_time_str": "09:00:00", "index": 0},
                {"name": "OP", "start_time_str": "10:00:00", "end_time_str": "16:00:00", "index": 1},
                {"name": "PM", "start_time_str": "16:00:00", "end_time_str": "19:00:00", "index": 2},
            ]
        ),
    )
