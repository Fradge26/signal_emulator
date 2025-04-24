from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import pandas as pd

from signal_emulator.controller import BaseCollection, BaseItem
from signal_emulator.utilities.utility_functions import find_files_with_extension

if TYPE_CHECKING:
    from signal_emulator.emulator import SignalEmulator


@dataclass(eq=False)
class M16Average(BaseItem):
    region_id: str
    node_id: str
    time_period_id: str
    node_cycle_time: int
    region_cycle_time: int
    ratio: float
    single_double_triple: int
    cycle_time_independent: bool
    signal_emulator: "SignalEmulator"

    def get_key(self):
        return self.node_id, self.time_period_id

    @property
    def time_period(self):
        return self.signal_emulator.time_periods.get_by_key(self.time_period_id)


class M16Averages(BaseCollection):
    """
    Class to represent a collection of M16 objects
    """

    TABLE_NAME = "m16_averages"
    ITEM_CLASS = M16Average
    WRITE_TO_DATABASE = True
    COLUMN_LIMITS = [
        (0, 8),
        (13, 16),
        (18, 26),
        (33, 37),
        (43, 47),
        (54, 58),
        (58, 62),
        (62, 66),
        (66, 70),
        (70, 74),
    ]
    COLUMN_NAMES = [
        "timestamp",
        "message_type",
        "node_id",
        "time_now",
        "node_cycle_time",
        "pulse_time_1",
        "pulse_time_2",
        "pulse_time_3",
        "pulse_time_4",
        "pulse_time_5",
    ]
    COLUMN_DTYPES = {
        "time_now": int,
        "node_cycle_time": int,
        "pulse_time_1": pd.Int64Dtype(),
        "pulse_time_2": pd.Int64Dtype(),
        "pulse_time_3": pd.Int64Dtype(),
        "pulse_time_4": pd.Int64Dtype(),
        "pulse_time_5": pd.Int64Dtype(),
    }
    HEADER_ROWS = [0, 1]

    def __init__(
        self,
        m16_path,
        periods=None,
        source_type="averaged",
        export_to_csv_path=None,
        signal_emulator=None,
    ):
        super().__init__(item_data=[], signal_emulator=signal_emulator)
        if signal_emulator.load_from_postgres:
            return
        assert source_type in ("averaged", "raw", None)
        if not periods and signal_emulator:
            periods = signal_emulator.time_periods
        self.periods = periods
        if source_type is None:
            self.m16_df = pd.DataFrame()
            self.m16_average_df = pd.DataFrame()
        elif source_type == "raw":
            self.m16_raw_df = self.load_all_m16_in_directory_df(m16_path)
            self.m16_average_df = self.calculate_modal_cycle_times()
        elif source_type == "averaged":
            self.m16_average_df = pd.read_csv(
                m16_path,
                dtype=self.COLUMN_DTYPES,
            )
        self.data = {}
        for row in self.m16_average_df.to_dict(orient="records"):
            m16 = M16Average(**row, signal_emulator=signal_emulator)
            self.data[m16.get_key()] = m16
        if export_to_csv_path:
            self.write_to_csv(export_to_csv_path)

    def calculate_modal_cycle_times(self):
        self.m16_raw_df["timedelta"] = self.m16_raw_df["timestamp"].dt.time.apply(lambda x: pd.to_timedelta(str(x)))
        self.m16_raw_df["time_period_id"] = self.m16_raw_df["timedelta"].apply(
            lambda x: self.signal_emulator.time_periods.get_period_id_for_timedelta(x)
        )
        self.m16_raw_df["region_id"] = self.m16_raw_df.apply(
            lambda x: self.get_region_id(x["node_id"], x["time_period_id"]), axis=1
        )

        ct_count = (
            self.m16_raw_df.groupby(["region_id", "node_id", "time_period_id"])["node_cycle_time"]
            .value_counts()
            .reset_index(name="count")
        )
        ct_total_count = (
            ct_count.groupby(["region_id", "node_id", "time_period_id"])["count"].sum().reset_index(name="count_total")
        )
        ct_count = pd.merge(ct_count, ct_total_count, on=["region_id", "node_id", "time_period_id"])
        ct_count["proportion"] = ct_count["count"] / ct_count["count_total"]
        ct_count.to_csv("D:/dump/out.csv")

        # group by region, node and time period, calculate the modal cycle time
        node_id_grouped = (
            self.m16_raw_df.groupby(["region_id", "node_id", "time_period_id"])["node_cycle_time"]
            .apply(lambda x: x.mode().iloc[0])
            .reset_index()
        )
        node_id_grouped_max = (
            node_id_grouped.groupby(["region_id", "time_period_id"])["node_cycle_time"]
            .apply(lambda x: self.get_max_cycle_time(x))
            .reset_index()
        ).rename(columns={"node_cycle_time": "region_cycle_time"})

        merged_df = pd.merge(node_id_grouped, node_id_grouped_max, on=["region_id", "time_period_id"])

        merged_df.sort_values(by=["region_id", "node_id", "time_period_id"])
        merged_df["ratio"] = merged_df["region_cycle_time"] / merged_df["node_cycle_time"]

        # set nodes to double or triple cycle
        merged_df["single_double_triple"] = 1
        merged_df["single_double_triple"][merged_df["ratio"] == 2] = 2
        merged_df["single_double_triple"][merged_df["ratio"] == 3] = 3

        # set the final cycle time, use region_cycle_time unless it is multi cycling
        merged_df["cycle_time_independent"] = False
        merged_df["cycle_time_independent"][
            (merged_df["node_cycle_time"] != merged_df["region_cycle_time"]) & (merged_df["single_double_triple"] == 1)
        ] = True
        return merged_df

    @staticmethod
    def get_max_cycle_time(node_cycle_times):
        """
        Function to set the region cycle time. If node cycle times greater than or equal to 64 seconds exist, then the
        most frequently occurring cycle time is selected, otherwise all node cycle times are selected from.
        :param node_cycle_times: series of cycle times
        :return: region cycle time
        """
        filtered_node_cycle_times = node_cycle_times[node_cycle_times >= 64]
        if len(filtered_node_cycle_times) == 0:
            filtered_node_cycle_times = node_cycle_times
        max_ct = filtered_node_cycle_times.value_counts().idxmax()
        return max_ct

    def get_region_id(self, node_id, time_period_id):
        stream_key = f"J{node_id[1:]}"
        stream = self.signal_emulator.streams.get_by_site_id(stream_key, strict=False)
        if stream and self.signal_emulator.plan_timetables.key_exists((stream.controller_key, time_period_id)):
            region_id = self.signal_emulator.plan_timetables.get_by_key((stream.controller_key, time_period_id)).region
        elif self.signal_emulator.plan_timetables.key_exists((stream_key, time_period_id)):
            region_id = self.signal_emulator.plan_timetables.get_by_key((stream_key, time_period_id)).region
        else:
            region_id = f"{node_id}_NO_GROUP"
        # Region / Group 0 is a temporary group for commissioning, assign composite region_id so that
        # each node can run with independent cycle time
        if region_id in {"R0000", "G0000"}:
            region_id += f"_{node_id}"
        return region_id[1:]

    @staticmethod
    def get_m16_file_date(m16_filepath):
        with open(m16_filepath, "r") as file:
            date_string = file.read(11)
        return datetime.strptime(date_string, "%d-%b-%Y")

    def load_all_m16_in_directory_df(self, directory_path):
        """
        Method to load all M16 files found in directory
        :param directory_path: path to directory
        :return: DataFrame of M16 data
        """
        m16_all_df = pd.DataFrame()
        for file_path in find_files_with_extension(directory_path, "lsg"):
            date = self.get_m16_file_date(file_path)
            m16_df = pd.read_fwf(
                file_path,
                colspecs=self.COLUMN_LIMITS,
                skiprows=self.HEADER_ROWS,
                names=self.COLUMN_NAMES,
                dtypes=self.COLUMN_DTYPES,
            )
            m16_df = m16_df[m16_df["message_type"] == "M16"]
            m16_df["timestamp"] = pd.to_timedelta(m16_df["timestamp"]) + date
            m16_all_df = pd.concat([m16_all_df, m16_df], ignore_index=True)
        return m16_all_df


if __name__ == "__main__":
    m16_parser = M16Averages(m16_path="signal_emulator/resources/M16")
