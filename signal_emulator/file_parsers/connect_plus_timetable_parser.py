import glob
import os
from pathlib import Path

import pandas as pd


class ConnectPlusTimetableParser:
    def __init__(self, signal_emulator=None):
        self.signal_emulator = signal_emulator

    @staticmethod
    def timetable_file_iterator(config_directory_path):
        for junction_directory in glob.glob(os.path.join(config_directory_path, "*/")):
            clean_directory = Path(junction_directory).as_posix()
            files = glob.glob(os.path.join(clean_directory, "Timetables", "*.csv"))
            for file in files:
                yield file

    @staticmethod
    def get_site_number_from_filename(filepath):
        site_id = Path(filepath).parts[-1].split()[1]
        our_code = f"J{site_id[2:4]}/{site_id[4:6]}0"
        return our_code

    def parse_timetable(self, timetable_filepath):
        self.signal_emulator.logger.info(f"Processing Connect Plus timetable: {timetable_filepath}")
        site_number = self.get_site_number_from_filename(timetable_filepath)
        pja_list = []
        tt_df = pd.read_csv(timetable_filepath)
        tt_df["timestamp"] = pd.to_datetime(tt_df["Time"], format="%H:%M:%S")
        tt_df["timestamp"] = pd.to_timedelta(tt_df["Time"])
        tt_df["timestamp"] = tt_df["timestamp"].fillna(method="ffill")
        tt_df = tt_df[tt_df["Command"].str.contains("PLAN")]
        for tp in self.signal_emulator.time_periods:
            # Step 1: Filter rows where 'timestamp' is less than x
            filtered = tt_df[tt_df["timestamp"] < tp.mid_time]
            # Step 2: Get the row immediately after the max 'timestamp' that is less than x
            if not filtered.empty:
                max_timestamp = filtered["timestamp"].max()
                plan_row = tt_df[tt_df["timestamp"] == max_timestamp].iloc[0]  # Get the first row after
                plan_number = int(plan_row["Parameters"].split()[1])
                pja_list.append(
                    {
                        "site_number": site_number,
                        "subgroup": "",
                        "region": "",
                        "wat": f"SC{plan_number}",
                        "control": f"SC{plan_number}",
                        "ctv": "",
                        "sco": "",
                        "status": "",
                        "period": tp.name,
                        "cell": "",
                    }
                )
        return pja_list
