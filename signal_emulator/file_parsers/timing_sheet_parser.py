import csv
import os
from collections import defaultdict
from itertools import zip_longest

from signal_emulator.utilities.utility_functions import (
    load_json_to_dict,
    dict_to_json_file,
    clean_site_number,
    str_to_int,
    clean_stage_name,
)


class TimingSheetParser:
    TIMING_SHEET_COLUMN_LOOKUP_PATH = os.path.join(
        os.path.dirname(__file__), "../resources/configs/timing_sheet_column_config.json"
    )
    TIMINGS_KEYS = {"A", "B", "A-B IG", "B-A IG"}
    TRAFFIC_TO_PED_IG_KEYS = {
        ("Red Man", "Red", "A-B IG"),
        ("Red Man", "Red + Amber", "A-B IG"),
        ("Red Man", "Amber", "A-B IG"),
        ("Red Man", "Flashing Amber", "A-B IG"),
        ("Red Man", "Red (Max/Gap)", "A-B IG"),
    }
    # Traffic to ped ig is red man,Amber and red man/red
    PED_TO_TRAFFIC_IG_KEYS = {
        ("Flashing Green Man", "Flashing Amber", "B-A IG"),
        ("Flashing Green Man", "Red", "B-A IG"),
        ("Blackout", "Red", "B-A IG"),
        ("Extended Blackout", "Red", "B-A IG"),
        ("Max Blackout", "Ext Red", "B-A IG"),
        ("Red Man", "Red", "B-A IG"),
        ("Red Man", "Red + Amber", "B-A IG"),
        ("Red + Amber", "", "B-A IG"),
        ("Red Man", "Flashing Amber", "B-A IG"),
        ("Flashing Green Man", "Red", "A-B IG"),
    }

    def __init__(self, signal_emulator=None):
        self.signal_emulator = signal_emulator

    def parse_timing_sheet_csv(self, timing_sheet_csv_path, output_timing_sheet_json=False, signal_emulator=None):
        data_dict = self.timing_sheet_csv_to_dict(timing_sheet_csv_path)
        if output_timing_sheet_json:
            output_timing_sheet_path = timing_sheet_csv_path.replace(".csv", ".json")
            dict_to_json_file(data_dict, output_timing_sheet_path)

        controller_key = clean_site_number(data_dict["Controller"][0]["code"])
        self.signal_emulator.logger.info(f"Processing timing sheet for site: {controller_key}")
        processed_args = {}
        for section, section_data in data_dict.items():
            if section == "Controller":
                processed_args["controllers"] = self.controller_data_factory(
                    section_data[0], data_dict["Site Details"], data_dict.get("Timings")
                )
            elif section == "Streams":
                processed_args["streams"] = self.stream_data_factory(section_data, controller_key)
                processed_args["stages"] = self.stage_data_factory(
                    section_data, data_dict["Stages"], data_dict["Phase Timings"], controller_key
                )
            elif section == "Phase Timings":
                processed_args["phases"] = self.phase_data_factory(
                    section_data,
                    data_dict["Phase type and conditions"],
                    controller_key,
                )
            elif section == "Intergreens":
                processed_args["intergreens"] = self.intergreen_data_factory(section_data, controller_key)
            elif section == "Phase Delays":
                processed_args["phase_delays"] = self.phase_delay_data_factory(section_data, controller_key)
            elif section == "Prohibited Stages":
                processed_args["prohibited_stage_moves"] = self.prohibited_stage_move_data_factory(
                    section_data, controller_key
                )
            elif section == "Timings":
                processed_args["streams"] = self.ped_stream_data_factory(controller_key)
                processed_args["phases"] = self.ped_phase_data_factory(section_data, controller_key)
                processed_args["intergreens"] = self.ped_intergreen_data_factory(section_data, controller_key)
            elif section == "Stages" and "Timings" in data_dict:
                processed_args["stages"] = self.ped_stage_data_factory(section_data, controller_key)
            elif section == "Phase Stage Demand Dependency":
                processed_args["phase_stage_demand_dependencies"] = self.phase_stage_demand_dependency_data_factory(
                    section_data, data_dict["Stages"], controller_key
                )

        return processed_args

    def ped_stream_data_factory(self, controller_key):
        stream_records = [
            {
                "controller_key": controller_key,
                "stream_number": 0,
                "site_number": controller_key,
                "stage_keys_in_stream": [1, 2],
            }
        ]
        return stream_records

    def ped_phase_data_factory(self, timings_data, controller_key):
        phase_records = []
        for timing_record in timings_data:
            if timing_record["min_time"] == "":
                min_time = str_to_int(timing_record["max_time"])
            else:
                min_time = str_to_int(timing_record["min_time"])
            if timing_record["period_change_key"] == "A":
                phase_records.append(
                    {
                        "controller_key": controller_key,
                        "phase_ref": "A",
                        "min_time": min_time,
                        "phase_type_str": "T",
                        "text": "Traffic",
                        "associated_phase_ref": "",
                        "appearance_type_int": 0,
                        "termination_type_int": 0,
                    }
                )
            elif timing_record["period_change_key"] == "B" or timing_record["ped_aspect"] == "Green Man":
                phase_records.append(
                    {
                        "controller_key": controller_key,
                        "phase_ref": "B",
                        "min_time": min_time,
                        "phase_type_str": "P",
                        "text": "Pedestrian",
                        "associated_phase_ref": "",
                        "appearance_type_int": 0,
                        "termination_type_int": 0,
                    }
                )
        return phase_records

    def controller_data_factory(self, controller_data, details_data, timings_data):
        if "/" in controller_data["grid_ref"]:
            x_coord, y_coord = controller_data["grid_ref"].split("/")
        else:
            x_coord, y_coord = 0, 0
        controller_records = [
            {
                "controller_key": clean_site_number(controller_data["code"]),
                "controller_type": controller_data["controller_name"],
                "x_coord": int(x_coord),
                "y_coord": int(y_coord),
                "address": self.get_from_site_details(details_data, "Address"),
                "spec_issue_no": self.get_from_site_details(details_data, "Issue"),
                "is_pedestrian_controller": bool(timings_data),
            }
        ]
        return controller_records

    def stream_data_factory(self, stream_data, controller_key):
        stream_records = []
        stream_numbers = set()
        for stream_record in stream_data:
            this_stream_number = str_to_int(stream_record["stream_number"])
            if this_stream_number not in stream_numbers:
                stream_numbers.add(this_stream_number)
                stream_records.append(
                    {
                        "controller_key": controller_key,
                        "stream_number": this_stream_number,
                        "site_number": clean_site_number(stream_record["site_code"]),
                    }
                )
        return stream_records

    @staticmethod
    def is_numeric(s):
        try:
            int(s)
            return True
        except (ValueError, TypeError):
            return False

    def stage_data_factory(self, stream_data, stage_data, phase_timings, controller_key):
        stages_names_in_streams = {clean_stage_name(a["stage_name"]) for a in stream_data}
        stage_numbers_in_streams = {
            int(clean_stage_name(a["stage_name"]))
            for a in stream_data
            if self.is_numeric(clean_stage_name(a["stage_name"]))
        }
        dd = 55
        if (
            stage_data[0]["stage_name"] not in stages_names_in_streams
            and int(stage_data[0]["stage_number"]) not in stage_numbers_in_streams
        ):
            self.signal_emulator.logger.info(f"Controller: {controller_key}: All red stage assumed with no phases")
            stream_data.insert(
                0,
                {
                    "phase_ref": None,
                    "site_code": stream_data[0]["site_code"],
                    "stage_name": stage_data[0]["stage_name"],
                    "stream_number": stream_data[0]["stream_number"],
                    "x": "X",
                },
            )

        stages_names_in_streams = {clean_stage_name(a["stage_name"]) for a in stream_data}
        stage_name_to_stream_numbers = defaultdict(list)
        for stream in stream_data:
            if stream["stream_number"] not in stage_name_to_stream_numbers[stream["stage_name"]]:
                stage_name_to_stream_numbers[clean_stage_name(stream["stage_name"])].append(stream["stream_number"])

        stage_name_and_stream_to_number = {}
        for stage in stage_data:
            stage_name = clean_stage_name(stage["stage_name"])
            stage_number = stage["stage_number"]
            if stage_name in stages_names_in_streams:
                stream_number = str_to_int(stage_name_to_stream_numbers[stage_name].pop(0))
                stage_name_and_stream_to_number[stage_name, stream_number] = str_to_int(stage["stage_number"])
            elif stage_number in stages_names_in_streams:
                stream_number = str_to_int(stage_name_to_stream_numbers[stage_number].pop(0))
                stage_name_and_stream_to_number[stage_number, stream_number] = str_to_int(stage["stage_number"])

        stream_no_stage_name_list = list(stage_name_and_stream_to_number.keys())
        if "0" not in {a["stage_number"] for a in stage_data}:
            stream_stage_no = 1
        else:
            stream_stage_no = 0
        stage_name_to_stream_stage_number = {
            (stream_no_stage_name_list[0][0], stream_no_stage_name_list[0][1]): stream_stage_no
        }
        stream_stage_no += 1
        for (this_stage_name, this_stream), (next_stage_name, next_stream) in zip(
            stream_no_stage_name_list, stream_no_stage_name_list[1:]
        ):
            if next_stream != this_stream:
                stream_stage_no = 0
            stage_name_to_stream_stage_number[(next_stage_name, next_stream)] = stream_stage_no
            stream_stage_no += 1

        stage_records = []
        stage_numbers = set()
        phases_in_stage = []
        stream_data = sorted(stream_data, key=lambda x: (x["stream_number"], x["stage_name"], x["phase_ref"]))
        for stream_record, next_stream_record in zip_longest(stream_data, stream_data[1:]):
            this_stream_number = str_to_int(stream_record["stream_number"])
            this_stage_name = clean_stage_name(stream_record["stage_name"])
            this_stage_number = stage_name_and_stream_to_number[this_stage_name, this_stream_number]
            if next_stream_record:
                next_stream_number = str_to_int(next_stream_record["stream_number"])
                next_stage_name = clean_stage_name(next_stream_record["stage_name"])
                next_stage_number = stage_name_and_stream_to_number[next_stage_name, next_stream_number]
            else:
                next_stage_number = None

            stream_stage_number = stage_name_to_stream_stage_number[this_stage_name, this_stream_number]
            if stream_record["phase_ref"]:
                phases_in_stage.append(stream_record["phase_ref"])
            if this_stage_number != next_stage_number:
                stage_numbers.add(this_stage_number)
                stage_records.append(
                    {
                        "controller_key": controller_key,
                        "stream_number": this_stream_number,
                        "stage_number": this_stage_number,
                        "stream_stage_number": stream_stage_number,
                        "stage_name": this_stage_name,
                        "phase_keys_in_stage": sorted(phases_in_stage),
                    }
                )
                phases_in_stage = []
        return stage_records

    def phase_data_factory(self, phase_timings, phase_type_and_conditions, controller_key):
        phase_records = []
        phase_type_and_conditions_by_ref = {a["phase_ref"]: a for a in phase_type_and_conditions}
        for phase_record in phase_timings:
            this_phase_ref = phase_record["phase_ref"]
            phase_records.append(
                {
                    "controller_key": controller_key,
                    "phase_ref": phase_record["phase_ref"],
                    "min_time": str_to_int(phase_record["min_time"]),
                    "phase_type_str": phase_record["phase_type"],
                    "text": clean_stage_name(phase_type_and_conditions_by_ref[this_phase_ref]["phase_name"]),
                    "associated_phase_ref": phase_type_and_conditions_by_ref[this_phase_ref]["associated_phase_ref"],
                    "appearance_type_int": str_to_int(
                        phase_type_and_conditions_by_ref[this_phase_ref]["appearance_type"]
                    ),
                    "termination_type_int": str_to_int(
                        phase_type_and_conditions_by_ref[this_phase_ref]["termination_type"]
                    ),
                }
            )
        return phase_records

    def intergreen_data_factory(self, intergreen_data, controller_key):
        intergreen_records = []
        for intergeen_item in intergreen_data:
            intergreen_records.append(
                {
                    "controller_key": controller_key,
                    "end_phase_key": intergeen_item["end_phase_key"],
                    "start_phase_key": intergeen_item["start_phase_key"],
                    "intergreen_time": str_to_int(intergeen_item["intergreen_time"]),
                }
            )
        return intergreen_records

    def phase_delay_data_factory(self, phase_delay_data, controller_key):
        phase_delay_records = []
        for phase_delay_item in phase_delay_data:
            phase_delay_records.append(
                {
                    "controller_key": controller_key,
                    "end_stage_key": str_to_int(phase_delay_item["end_stage_key"]),
                    "start_stage_key": str_to_int(phase_delay_item["start_stage_key"]),
                    "phase_ref": phase_delay_item["phase_ref"],
                    "delay_time": str_to_int(phase_delay_item["delay_time"]),
                    "is_absolute": True,
                }
            )
        return phase_delay_records

    def prohibited_stage_move_data_factory(self, prohibited_stage_move_data, controller_key):
        prohibited_stage_move_records = []
        for prohibited_stage_move_item in prohibited_stage_move_data:
            if prohibited_stage_move_item["value"].isnumeric():
                via_stage_key = str_to_int(prohibited_stage_move_item["value"])
            else:
                via_stage_key = None

            prohibited_stage_move_records.append(
                {
                    "controller_key": controller_key,
                    "end_stage_key": str_to_int(prohibited_stage_move_item["end_stage_key"]),
                    "start_stage_key": str_to_int(prohibited_stage_move_item["start_stage_key"]),
                    "prohibited": prohibited_stage_move_item["value"] == "P",
                    "ignore": prohibited_stage_move_item["value"] == "X",
                    "via_stage_key": via_stage_key,
                }
            )
        return prohibited_stage_move_records

    def get_from_site_details(self, site_details, field_name):
        for detail in site_details:
            if detail["field_name"] == field_name:
                return detail["value"]
        else:
            return ""

    def timing_sheet_csv_to_dict(self, timing_sheet_csv_path):
        column_dict = load_json_to_dict(self.TIMING_SHEET_COLUMN_LOOKUP_PATH)
        with open(timing_sheet_csv_path, newline="") as csv_file:
            data = list(csv.reader(csv_file))
        data_dict = {}
        section_data = []
        section = ""
        for row in data:
            if row == [] or (section == "Linked Sites" and row[0] == "Link Number"):
                continue
            if row[0].endswith("start"):
                section = row[0].replace(" - start", "")
                section_data = []
            elif row[0].endswith("end"):
                data_dict[section] = self.data_to_dict(section_data, column_dict[section])
            else:
                num_cols = len(column_dict[section])
                if len(row) < num_cols:
                    row.extend([""] * (num_cols - len(row)))
                if section == "Timings":
                    row_copy = row.copy()
                    row = []
                    for i in row_copy:
                        if i == "Red A-B IG":
                            row.extend(["Red", "A-B IG"])
                        else:
                            row.append(i)
                    row_copy = row.copy()
                    timing_index = self.get_timing_key_index(row)
                    if timing_index != 2:
                        row[1] = ""
                        row[2] = row_copy[timing_index]
                        row[3] = row_copy[timing_index + 1]
                        row[4] = row_copy[timing_index + 2]
                if num_cols < len(row):
                    if section == "Site Details":
                        row[1] = ", ".join(row[1:])
                    elif section == "Stages":
                        row[1] = " ".join(row[1:])
                    elif section == "Streams":
                        row[2] = " ".join(row[2:-2])
                        row[3] = row[-2]
                        row[4] = row[-1]
                    elif section == "Phase type and conditions":
                        row[1] = " ".join(row[1:-4])
                        row[2] = row[-4]
                        row[3] = row[-3]
                        row[4] = row[-2]
                        row[5] = row[-1]
                    elif section == "Phase Stage Demand Dependency":
                        row[0] = " ".join(row[:-2])
                        row[1] = row[-2]
                        row[2] = row[-1]
                row = [r.strip() for r in row]
                section_data.append(row[:num_cols])
        return data_dict

    def get_timing_key_index(self, row):
        for i, item in enumerate(row):
            if item in self.TIMINGS_KEYS:
                return i
        else:
            return 2

    @staticmethod
    def data_to_dict(data, column_dict):
        output_dict = []
        for d in data:
            output_dict.append({v: d[int(k) - 1] for k, v in column_dict.items() if v != "unused"})
        return output_dict

    def timing_sheet_file_iterator(self, timing_sheet_directory_path, borough_codes):
        for filename in os.listdir(timing_sheet_directory_path):
            if not filename[:2].isnumeric():
                continue
            borough_code = int(filename[:2])
            if borough_codes and borough_code not in borough_codes:
                continue
            timing_sheet_path = os.path.join(timing_sheet_directory_path, filename)
            if os.path.exists(
                os.path.join(timing_sheet_directory_path, "fixed", filename.replace(".csv", "_fixed.csv"))
            ):
                timing_sheet_path = os.path.join(
                    timing_sheet_directory_path, "fixed", filename.replace(".csv", "_fixed.csv")
                )
            if filename.endswith("csv") and os.path.isfile(timing_sheet_path):
                if self.validate_timing_sheet_csv(timing_sheet_path):
                    yield timing_sheet_path

    def validate_timing_sheet_csv(self, timing_sheet_csv_path):
        timing_sheet_dict = self.timing_sheet_csv_to_dict(timing_sheet_csv_path)
        for detail in timing_sheet_dict["Site Details"]:
            if detail["field_name"] == "Controller Type":
                if detail["value"] == "Parallel Stage Stream Site":
                    return False
                else:
                    break
        valid = True
        if "Junc" in timing_sheet_csv_path:
            for section in ["Stages", "Phase Timings", "Streams"]:
                if len(timing_sheet_dict[section]) == 0:
                    self.signal_emulator.logger.warning(
                        f"Timing sheet: {timing_sheet_csv_path} is invalid. Section: {section} contains no data"
                    )
                    valid = False
            return valid
        else:
            for section in ["Timings", "Stages"]:
                if len(timing_sheet_dict[section]) == 0:
                    self.signal_emulator.logger.warning(
                        f"Timing sheet: {timing_sheet_csv_path} is invalid. Section: {section} contains no data"
                    )
                    valid = False
            return valid

    def ped_stage_data_factory(self, section_data, controller_key):
        stage_records = []
        num_stages = len(section_data)
        stage_number = 1
        for section_record in section_data:
            if num_stages == 2 or section_record["stage_number"] in {"1", "2"}:
                stage_records.append(
                    {
                        "controller_key": controller_key,
                        "stream_number": 0,
                        "stage_number": stage_number,
                        "stream_stage_number": stage_number,
                        "stage_name": section_record["stage_name"],
                        "phase_keys_in_stage": [chr(64 + stage_number)],
                    }
                )
                stage_number += 1
        return stage_records

    def ped_intergreen_data_factory(self, section_data, controller_key):
        intergreen_times = defaultdict(lambda: 0)
        for section_record in section_data:
            ped_period = (
                section_record["ped_aspect"],
                section_record["road_aspect"],
                section_record["period_change_key"],
            )
            if ped_period in self.PED_TO_TRAFFIC_IG_KEYS:
                intergreen_times["ped_to_traffic"] += str_to_int(section_record["min_time"])
            elif ped_period in self.TRAFFIC_TO_PED_IG_KEYS:
                intergreen_times["traffic_to_ped"] += str_to_int(section_record["min_time"])

        intergreen_records = [
            {
                "controller_key": controller_key,
                "end_phase_key": "A",
                "start_phase_key": "B",
                "intergreen_time": intergreen_times["traffic_to_ped"],
            },
            {
                "controller_key": controller_key,
                "end_phase_key": "B",
                "start_phase_key": "A",
                "intergreen_time": intergreen_times["ped_to_traffic"],
            },
        ]
        return intergreen_records

    def phase_stage_demand_dependency_data_factory(self, section_data, stage_data, controller_key):
        stage_name_to_number = {
            clean_stage_name(stage["stage_name"]): int(stage["stage_number"]) for stage in stage_data
        }
        stage_number_to_number = {stage["stage_number"]: int(stage["stage_number"]) for stage in stage_data}
        phase_stage_demand_dependency = []

        for section_record in section_data:
            stage_name = clean_stage_name(section_record["stage_name"])
            if stage_name in stage_name_to_number:
                stage_number = stage_name_to_number[stage_name]
            else:
                stage_number = stage_number_to_number[stage_name]
            phase_stage_demand_dependency.append(
                {
                    "controller_key": controller_key,
                    "stage_number": stage_number,
                    "phase_ref": section_record["phase_ref"],
                }
            )
        return phase_stage_demand_dependency


if __name__ == "__main__":
    tsp = TimingSheetParser()
    attrs = tsp.parse_timing_sheet_csv("../resources/timing_sheets/00_000002_Junc.csv")
