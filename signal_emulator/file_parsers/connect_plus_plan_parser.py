import glob
import os
from pathlib import Path

import pandas as pd


class ConnectPlusPlanParser:
    def __init__(self, signal_emulator=None):
        self.signal_emulator = signal_emulator

    @staticmethod
    def plan_file_iterator(config_directory_path):
        for junction_directory in glob.glob(os.path.join(config_directory_path, "*/")):
            clean_directory = Path(junction_directory).as_posix()
            files = glob.glob(os.path.join(clean_directory, "Timing Plans", "*.csv"))
            for file in files:
                yield file

    def parse_plan(self, plan_filepath):
        self.signal_emulator.logger.info(f"Processing Connect Plus timing plan: {plan_filepath}")
        plan_df = pd.read_csv(plan_filepath)
        if len(plan_df.index) == 0:
            return {"plans": [], "plan_sequence_items": []}
        plan_df.rename(columns={"SCN": "site_id", "SCN Description": "site_name"}, inplace=True)
        plan_df["site_id"] = plan_df["site_id"].str.replace(r"(J0)(\d{2})(\d{3})", r"J\2/\3", regex=True)
        plan_df["name"] = plan_df["Description"].str.slice(0, 8).str.replace(r"\s{2,}", " ", regex=True).str.upper()
        plan_df["plan_number"] = plan_df["Description"].str.slice(5, 8).astype(int)
        plan_df["cycle_time"] = plan_df["Description"].str.slice(11, 15).astype(int)
        plan_df["plan_items"] = plan_df["Description"].str.slice(15)
        plan_df["timeout"] = 0
        attrs_dict = {}
        attrs_dict["plans"] = plan_df[["site_id", "plan_number", "cycle_time", "timeout", "name"]].to_dict(
            orient="records"
        )

        plan_df["plan_items"] = plan_df["plan_items"].str.split(",")
        items_df = plan_df.explode("plan_items", ignore_index=True)
        items_df["plan_items"] = items_df["plan_items"].str.strip()
        items_df["plan_items"] = items_df["plan_items"].str.replace(r"[{}]", "", regex=True)
        items_df["plan_items"] = items_df["plan_items"].str.replace(r"S\d{1}", "", regex=True)
        items_df[["bits", "pulse_time"]] = items_df["plan_items"].str.split(" ", n=1, expand=True)
        items_df["f_bits"] = items_df["bits"].str.replace(r"D\d{1}", "", regex=True)
        items_df["f_bits"] = items_df["f_bits"].str.replace(r"[+]", "", regex=True).str.findall("..?")
        items_df["d_bits"] = items_df["bits"].str.replace(r"F\d{1}", "", regex=True)
        items_df["d_bits"] = items_df["d_bits"].str.replace(r"[+]", "", regex=True).str.findall("..?")
        items_df["p_bits"] = items_df["bits"].str.replace(r"[DF]\d{1}", "", regex=True)
        items_df["p_bits"] = items_df["p_bits"].str.replace(r"[+]", "", regex=True).str.findall("..?")
        items_df["pulse_time"] = items_df["pulse_time"].astype(int)
        items_df["nto"] = False
        items_df["scoot_stage"] = ""
        items_df["index"] = items_df.groupby(["plan_number"]).cumcount()
        attrs_dict["plan_sequence_items"] = items_df[
            ["site_id", "plan_number", "index", "pulse_time", "scoot_stage", "f_bits", "d_bits", "p_bits", "nto"]
        ].to_dict(orient="records")

        return attrs_dict
