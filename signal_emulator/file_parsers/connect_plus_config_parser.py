import pdfplumber
from pathlib import Path
from signal_emulator.utilities.utility_functions import str_to_int
import os
import glob
from collections import defaultdict
import re


class ConnectPlusConfigParser:
    TELENT_PHASE_TYPE_DICT = {
        "FP": "P",
        "G": "F",
        "L": "F",
        "NP": "P",
        "P": "P",
        "PP": "P",
        "PT": "P",
        "T": "T",
        "W": "P",
    }
    MOTUS_APPEARANCE_TYPE_DICT = {"ALWAYS APPEARS": 0, "IF DEMANDED AT START OF STAGE": 0}
    MOTUS_TERMINATION_TYPE_DICT = {"AT END OF STAGE": 0, "END OF MINIMUM GREEN": 0}
    SWARCO_PHASE_TYPE_DICT = {
        "802 T: vehicle": "T",
        "802 T: Vehicle": "T",
        "811 PU: puffin": "P",
        "812 TN: toucan near side": "P",
        "813 TF: toucan far side": "P",
        "813 TF: Toucan far side": "P",
        "813 TF: Toucan pedestrian": "P",
        "814 PD: intersection pedestrian": "P",
        "814 PD: Intersection pedestrian": "P",
        "815 W: warden box": "P",
        "T": "T",
        "P": "P",
        "0: Dummy": "D",
        "Dummy": "D",
    }
    APPEARANCE_TYPE_DICT = {"Always": 0, "Demand before interstage": 1, "Demand during interstage or stage": 1}
    TERMINATION_TYPE_DICT = {"At end of stage": 0, "When minimum timer expires": 0}
    SIEMENS_PHASE_TYPE_DICT = {"UK Traffic": "T", "UK Far Side Pedestrian": "P", "UK Near Side Pedestrian": "P"}

    def __init__(self, signal_emulator=None):
        self.signal_emulator = signal_emulator

    def config_file_iterator(self, config_directory_path):
        for junction_directory in glob.glob(os.path.join(config_directory_path, "*/")):
            clean_directory = Path(junction_directory).as_posix()
            if clean_directory[-3:] == "OLD":
                continue
            pdf_files = glob.glob(os.path.join(clean_directory, "Configuration File", "*.pdf"))
            if len(pdf_files) > 1:
                self.signal_emulator.logger.warning(
                    f"Check directory, contains more than 1 pdf files: {clean_directory}"
                )
            elif len(pdf_files) == 0:
                self.signal_emulator.logger.warning(f"Check directory, contains 0 pdf files: {clean_directory}")
            else:
                yield Path(pdf_files[0]).as_posix()

    def get_config_type(self, config_path):
        with pdfplumber.open(config_path) as pdf:
            page = pdf.pages[0]
            page_txt = page.extract_text()
            if page_txt == "":
                page = pdf.pages[1]
                page_txt = page.extract_text()
            if "Administration Streams, Stages, Phases Control" in page_txt:
                self.signal_emulator.logger.info(f"Check config: {config_path}, probably SIEMENS double page format")
                return "SIEMENS DOUBLE PAGE"
            elif "Project data" in page_txt and "Database file" in page_txt:
                return "SWARCO"
            elif "General Specifications" in page_txt and "Signal Company Use Only" in page_txt:
                return "SIEMENS"
            elif "Stage and Stream Allocation F009" in page_txt:
                return "MOTUS"
            elif "Telent traffic controller configuration forms" in page_txt:
                return "TELENT"
            else:
                self.signal_emulator.logger.info(f"Check config: {config_path}, probably MOTUS")

    def get_telent_phases_in_stages(self, pdf):
        page = self.get_page(pdf, "Stage data", 1)
        all_tables = page.find_tables()
        phases_in_stages = []
        stage_offset = 0
        for table in all_tables:
            table_data = table.extract()
            if table_data[0][0][:-1] == "Stream ":
                for i, row in enumerate(table_data[2:]):
                    for phase_ref in row[1].split(","):
                        if phase_ref != "":
                            phases_in_stages.append(
                                {"stage_number": str_to_int(row[0]) + stage_offset, "phase_ref": phase_ref}
                            )
                    if i == len(table_data[2:]) - 1:
                        stage_offset += str_to_int(row[0]) + 1
        return phases_in_stages

    def get_motus_phases_in_stages(self, pdf):
        page = self.get_page(pdf, "Stage and Stream Allocation", 1)
        if page is None:
            page = self.get_page(pdf, "Streams, Stages, Phases Control")
        all_tables = page.find_tables()
        phases_table = all_tables[0]
        phases_table_data = phases_table.extract()
        current_stream = ""
        for i, row in enumerate(phases_table_data):
            if row[0]:
                current_stream = int(row[0].replace("\nmaertS", ""))
            phases_table_data[i][0] = current_stream
            if row[1]:
                phases_table_data[i][1] = i - 1

        table_rects_1 = [
            a
            for a in page.objects["rect"]
            if a["non_stroking_color"] != (0, 0, 0) and int(a["width"]) in {23, 24} and int(a["height"]) == 11
        ]
        phases_in_stages = []
        for rect in table_rects_1:
            cell_i, cell_j = self.get_cell_index_containing_rect(phases_table, rect)
            phase_in_stage = {"stage_number": phases_table_data[cell_i][1], "phase_ref": phases_table_data[0][cell_j]}
            if phase_in_stage not in phases_in_stages:
                phases_in_stages.append(phase_in_stage)
        return sorted(phases_in_stages, key=lambda x: x["stage_number"])

    def get_telent_stages_in_streams(self, pdf):
        page = self.get_page(pdf, "Stage data", 1)
        all_tables = page.find_tables()
        stages_in_streams = []
        stage_offset = 0
        for table in all_tables:
            table_data = table.extract()
            if table_data[0][0][:-1] == "Stream ":
                stream_number = int(table_data[0][0][-1])
                for i, row in enumerate(table_data[2:]):
                    stages_in_streams.append(
                        {"stage_number": str_to_int(row[0]) + stage_offset, "stream_number": stream_number}
                    )
                    if i == len(table_data[2:]) - 1:
                        stage_offset += str_to_int(row[0]) + 1
        return stages_in_streams

    def get_motus_stages_in_streams(self, pdf):
        page = self.get_page(pdf, "Stage and Stream Allocation", 1)
        if page is None:
            page = self.get_page(pdf, "Streams, Stages, Phases Control")
        all_tables = page.find_tables()
        phases_table = all_tables[0]
        phases_table_data = phases_table.extract()
        current_stream = ""
        stages_in_streams = []
        for i, row in enumerate(phases_table_data[1:]):
            if row[0]:
                current_stream = int(row[0].replace("\nmaertS", ""))
            phases_table_data[i][0] = current_stream
            stages_in_streams.append({"stream_number": current_stream, "stage_number": i})
        return stages_in_streams

    def get_phases_in_stages(self, pdf):
        page = self.get_page(pdf, "Phases, Stages and Streams")
        if page is None:
            page = self.get_page(pdf, "Streams, Stages, Phases Control")
        page_txt_list = page.extract_text().split("\n")
        num_phases = int(self.get_text_after_substrings(page_txt_list, "Total Number of Phases"))
        num_stages = self.get_text_between_substrings(
            page_txt_list, "Current Number of stages", "Number of Switched Signs"
        )
        if not num_stages:
            num_stages = self.get_text_before_substrings(page_txt_list, "Number of Switched Signs")
        num_stages = int(num_stages)
        num_table_cells = (num_phases + 1) * (num_stages + 1)

        page = self.get_page(pdf, "Phases in Stages")
        all_table = page.find_tables()
        for table in all_table:
            if len(table.cells) == num_table_cells:
                phases_table = table
                break
        else:
            print("ahhhh")
        table_rects_1 = [
            a
            for a in page.objects["rect"]
            if int(a["width"]) == 10
            or int(a["width"]) == 12
            or (int(a["width"]) == 7 and a["stroking_color"] == (1, 0, 0))
        ]
        phases_table_data = phases_table.extract()
        phases_in_stages = []
        for rect in table_rects_1:
            cell_i, cell_j = self.get_cell_index_containing_rect(phases_table, rect)
            phase_in_stage = {
                "stage_number": int(phases_table_data[cell_i][0]),
                "phase_ref": phases_table_data[0][cell_j],
            }
            if phase_in_stage not in phases_in_stages:
                phases_in_stages.append(phase_in_stage)
        return sorted(phases_in_stages, key=lambda x: x["stage_number"])

    def get_cell_index_containing_rect(self, phases_table, rect):
        i, j = None, None
        xs = [a[0] for a in rect["pts"]]
        ys = [a[1] for a in rect["pts"]]
        x_mean = sum(xs) / len(xs)
        y_mean = sum(ys) / len(ys)
        for i, j, cell in self.table_cell_iterator(phases_table):
            if self.is_point_in_rectangle(x_mean, y_mean, cell):
                break
        return i, j

    def table_cell_iterator(self, table):
        for i, row in enumerate(table.rows):
            for j, cell in enumerate(row.cells):
                if cell and len(cell) == 4:
                    yield i, j, cell

    @staticmethod
    def is_point_in_rectangle(px, py, rect):
        """
        Check if a point (px, py) is inside a rectangle.

        Parameters:
        px, py: float
            Coordinates of the point.
        rect: tuple
            A tuple (x1, y1, x2, y2) representing the rectangle,
            where (x1, y1) is one corner and (x2, y2) is the opposite corner.

        Returns:
        bool
            True if the point is inside the rectangle, False otherwise.
        """
        x1, y1, x2, y2 = rect
        # Determine the left, right, top, and bottom boundaries of the rectangle
        left = min(x1, x2)
        right = max(x1, x2)
        top = min(y1, y2)
        bottom = max(y1, y2)
        # Check if the point is within the rectangle
        return left <= px <= right and top <= py <= bottom

    def get_tables(self, pdf_path):
        # Open the PDF file
        table_dict = {}
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                # Extract tables on the page
                page_text_list = page.extract_text().split("\n")
                tables = page.extract_tables()
                table_name_index = None
                unknown_count = 0
                for table in tables:
                    if table_name_index:
                        page_text_list = page_text_list[table_name_index + 1 :]
                    table_name, table_name_index, unknown_count = self.get_table_name(
                        table[0], page_text_list, unknown_count
                    )
                    if table_name in table_dict:
                        for i in range(1, 100):
                            if f"{table_name}_{i}" not in table_dict:
                                table_name = f"{table_name}_{i}"
                                break
                        else:
                            raise ValueError

                    table_dict[table_name] = table
        if "PHASES - TYPES" in table_dict:
            table_dict["TYPES"] = table_dict["PHASES - TYPES"]
        return table_dict

    def get_table_name(self, table_first_row, page_text_list, unknown_count):
        table_first_row_text = self.get_first_row_text(table_first_row)
        if table_first_row_text == "Configuration Notes":
            return "Configuration Notes", 0, unknown_count
        for i, row in enumerate(page_text_list):
            if table_first_row_text == row or table_first_row_text.strip() == row:
                break
        else:
            unknown_count += 1
            return f"UNKNOWN_{unknown_count}", 0, unknown_count
        return page_text_list[i - 1].upper(), i, unknown_count

    def get_first_row_text(self, table_first_row):
        table_first_row = [a for a in table_first_row if a]
        crlf_count = self.max_substring_occurrences(table_first_row, "\n")
        if crlf_count == 0:
            return " ".join(table_first_row)
        else:
            return " ".join(a.split("\n")[0] for a in table_first_row if a.count("\n") == crlf_count)

    @staticmethod
    def max_substring_occurrences(strings, substring):
        max_count = 0
        for string in strings:
            if string:
                count = string.count(substring)
                if count > max_count:
                    max_count = count
        return max_count

    def parse_telent_config_pdf(self, config_pdf_path, signal_emulator=None):
        self.signal_emulator.logger.info(f"Processing TELENT config: {config_pdf_path}")
        controller_key = self.get_controller_key_from_path(config_pdf_path)
        processed_args = {}
        with pdfplumber.open(config_pdf_path) as pdf:
            phases_in_stages = self.get_telent_phases_in_stages(pdf)
            stages_in_streams = self.get_telent_stages_in_streams(pdf)
            phase_records = self.phase_telent_data_factory(pdf, controller_key)
            processed_args["controllers"] = self.controller_telent_data_factory(pdf, controller_key)
            processed_args["streams"] = self.stream_siemens_data_factory(stages_in_streams, controller_key)
            processed_args["phases"] = phase_records
            processed_args["stages"] = self.stage_siemens_data_factory(
                stages_in_streams, phases_in_stages, phase_records, controller_key
            )
            processed_args["intergreens"] = self.intergreen_telent_data_factory(pdf, controller_key)
            processed_args["phase_delays"] = []
        return processed_args

    def parse_motus150_config_pdf(self, config_pdf_path, signal_emulator=None):
        self.signal_emulator.logger.info(f"Processing MOTUS config: {config_pdf_path}")
        controller_key = self.get_controller_key_from_path(config_pdf_path)
        processed_args = {}
        with pdfplumber.open(config_pdf_path) as pdf:
            phases_in_stages = self.get_motus150_phases_in_stages(pdf)
            stages_in_streams = self.get_motus150_stages_in_streams(pdf)
            phase_records = self.phase_motus150_data_factory(pdf, controller_key)
            processed_args["controllers"] = self.controller_motus150_data_factory(pdf, controller_key)
            processed_args["streams"] = self.stream_siemens_data_factory(stages_in_streams, controller_key)
            processed_args["phases"] = phase_records
            processed_args["stages"] = self.stage_siemens_data_factory(
                stages_in_streams, phases_in_stages, phase_records, controller_key
            )
            processed_args["intergreens"] = self.intergreen_motus150_data_factory(pdf, controller_key)
            processed_args["phase_delays"] = self.phase_delay_motus150_data_factory(pdf, controller_key)
        return processed_args

    def parse_motus_config_pdf(self, config_pdf_path, signal_emulator=None):
        self.signal_emulator.logger.info(f"Processing MOTUS config: {config_pdf_path}")
        controller_key = self.get_controller_key_from_path(config_pdf_path)
        processed_args = {}
        with pdfplumber.open(config_pdf_path) as pdf:
            phases_in_stages = self.get_motus_phases_in_stages(pdf)
            stages_in_streams = self.get_motus_stages_in_streams(pdf)
            phase_records = self.phase_motus_data_factory(pdf, controller_key)
            processed_args["controllers"] = self.controller_motus_data_factory(pdf, controller_key)
            processed_args["streams"] = self.stream_siemens_data_factory(stages_in_streams, controller_key)
            processed_args["phases"] = phase_records
            processed_args["stages"] = self.stage_siemens_data_factory(
                stages_in_streams, phases_in_stages, phase_records, controller_key
            )
            processed_args["intergreens"] = self.intergreen_motus_data_factory(pdf, controller_key)
            processed_args["phase_delays"] = self.phase_delay_motus_data_factory(pdf, controller_key)
        return processed_args

    def parse_siemens_config_pdf(self, config_pdf_path, signal_emulator=None):
        self.signal_emulator.logger.info(f"Processing SIEMENS config: {config_pdf_path}")
        controller_key = self.get_controller_key_from_path(config_pdf_path)
        processed_args = {}
        with pdfplumber.open(config_pdf_path) as pdf:
            phases_in_stages = self.get_phases_in_stages(pdf)
            stages_in_streams = self.get_stages_in_streams(pdf, phases_in_stages)
            phase_records = self.phase_siemens_data_factory(pdf, controller_key)
            processed_args["controllers"] = self.controller_siemens_data_factory(pdf, controller_key)
            processed_args["streams"] = self.stream_siemens_data_factory(stages_in_streams, controller_key)
            processed_args["phases"] = phase_records
            processed_args["stages"] = self.stage_siemens_data_factory(
                stages_in_streams, phases_in_stages, phase_records, controller_key
            )
            processed_args["intergreens"] = self.intergreen_siemens_data_factory(pdf, controller_key)
            processed_args["phase_delays"] = self.phase_delay_siemens_data_factory(pdf, controller_key)
        return processed_args

    def parse_swarco_config_pdf(self, config_pdf_path, signal_emulator=None):
        self.signal_emulator.logger.info(f"Processing SWARCO config: {config_pdf_path}")
        table_dict = self.get_tables(config_pdf_path)
        controller_key = self.get_controller_key_from_path(config_pdf_path)
        processed_args = {}
        processed_args["controllers"] = self.controller_swarco_data_factory(
            table_dict["PROJECT DATA"], table_dict.get("CONFIGURATION NOTES"), config_pdf_path
        )
        processed_args["streams"] = self.stream_swarco_data_factory(table_dict["STREAM"], controller_key)
        processed_args["phases"] = self.phase_swarco_data_factory(
            table_dict["TYPES"], table_dict["CONDITIONS"], table_dict["TIMINGS"], controller_key
        )
        processed_args["stages"] = self.stage_swarco_data_factory(
            table_dict["STAGE"], table_dict["PHASES IN STAGES"], controller_key
        )
        processed_args["intergreens"] = self.intergreen_swarco_data_factory(
            table_dict["INTERGREEN TIMES"], controller_key
        )
        processed_args["phase_delays"] = self.phase_delay_swarco_data_factory(
            table_dict.get("PHASE DELAYS"), controller_key
        )
        processed_args["prohibited_stage_moves"] = self.prohibited_stage_move_swarco_data_factory(
            table_dict["MOVE SETS"], table_dict, controller_key
        )
        return processed_args

    def controller_swarco_data_factory(self, project_data, configuration_notes, config_pdf_path):
        project_data_dict = {a[0]: a[1] for a in project_data}
        controller_records = [
            {
                "controller_key": self.get_controller_key_from_path(config_pdf_path),
                "controller_type": project_data_dict["Controller type"],
                "x_coord": 0,
                "y_coord": 0,
                "address": self.get_address(project_data_dict),
                "spec_issue_no": self.get_config_version(configuration_notes),
                "is_pedestrian_controller": False,
            }
        ]
        return controller_records

    @staticmethod
    def get_controller_key_from_path(config_pdf_path):
        cp_code = Path(config_pdf_path).parts[-3].split(" - ")[0]
        our_code = f"J{cp_code[2:4]}/{cp_code[4:6]}0"
        return our_code

    @staticmethod
    def get_address(project_data_dict):
        return (
            f'{project_data_dict["Street2"]}, {project_data_dict["Street1"]}, '
            f'{project_data_dict["City"]}, {project_data_dict["Country"]}'
        )

    def get_config_version(self, configuration_notes):
        if not configuration_notes:
            return "NA"
        else:
            return configuration_notes[-1][0].split("\n")[-1]

    def stream_swarco_data_factory(self, stream_data, controller_key):
        stream_records = []
        for stream_record in stream_data[1:]:
            this_stream_number = str_to_int(stream_record[0])
            stream_records.append(
                {
                    "controller_key": controller_key,
                    "stream_number": this_stream_number,
                    "site_number": f"{controller_key[:-1]}{this_stream_number}",
                }
            )
        return stream_records

    def stream_siemens_data_factory(self, stream_data, controller_key):
        stream_numbers = {a["stream_number"] for a in stream_data}
        stream_records = []
        for stream_number in stream_numbers:
            stream_records.append(
                {
                    "controller_key": controller_key,
                    "stream_number": stream_number,
                    "site_number": f"{controller_key[:-1]}{stream_number}",
                }
            )
        return stream_records

    def phase_swarco_data_factory(self, phase_types, phase_conditions, phase_timings, controller_key):
        phase_conditions = self.remove_new_lines(phase_conditions)
        phase_timings = self.remove_new_lines(phase_timings)
        phase_types = self.remove_new_lines(phase_types)
        phase_records = []
        col_offset = 1 if phase_types[0][0] == "ID" else 0
        phase_conditions_dict = {a[0 + col_offset]: a for a in phase_conditions}
        phase_timings_dict = {a[0 + col_offset]: a for a in phase_timings}
        for phase_record in phase_types[1:]:
            this_phase_ref = phase_record[0 + col_offset]
            phase_records.append(
                {
                    "controller_key": controller_key,
                    "phase_ref": this_phase_ref,
                    "min_time": str_to_int(phase_timings_dict.get(this_phase_ref, [0, 0, 0])[2 + col_offset]),
                    "phase_type_str": self.SWARCO_PHASE_TYPE_DICT[phase_record[3 + col_offset]],
                    "text": phase_record[2 + col_offset],
                    "associated_phase_ref": "" if phase_record[4 + col_offset] == "-" else phase_record[4 + col_offset],
                    "appearance_type_int": self.APPEARANCE_TYPE_DICT[
                        phase_conditions_dict[this_phase_ref][2 + col_offset]
                    ],
                    "termination_type_int": self.TERMINATION_TYPE_DICT[
                        phase_conditions_dict[this_phase_ref][3 + col_offset]
                    ],
                }
            )
        return phase_records

    def stage_swarco_data_factory(self, stage_data, phases_in_stages_data, controller_key):
        phases_in_stages_dict = {
            a[0]: [phases_in_stages_data[0][i + 1] for i, b in enumerate(a[1:]) if b == "X"]
            for a in phases_in_stages_data[1:]
        }
        stage_records = []
        previous_stage = None
        stream_stage_number = 1
        for stage in stage_data[1:]:
            if previous_stage and previous_stage[2] != stage[2]:
                stream_stage_number = 1
            elif previous_stage and previous_stage[2] == stage[2]:
                stream_stage_number += 1
            stage_records.append(
                {
                    "controller_key": controller_key,
                    "stream_number": str_to_int(stage[2]),
                    "stage_number": str_to_int(stage[0]),
                    "stream_stage_number": stream_stage_number,
                    "stage_name": stage[1],
                    "phase_keys_in_stage": phases_in_stages_dict[stage[0]],
                }
            )
            previous_stage = stage
        return stage_records

    def intergreen_swarco_data_factory(self, intergreen_times_data, controller_key):
        intergreen_records = []
        for i, intergreen_row in enumerate(intergreen_times_data[1:]):
            end_phase_key = intergreen_times_data[i + 1][0]
            for j, intergreen_record in enumerate(intergreen_row[1:]):
                start_phase_key = intergreen_times_data[0][j + 1]
                if intergreen_record != "":
                    intergreen_records.append(
                        {
                            "controller_key": controller_key,
                            "end_phase_key": end_phase_key,
                            "start_phase_key": start_phase_key,
                            "intergreen_time": str_to_int(intergreen_record),
                        }
                    )
        return intergreen_records

    def phase_delay_swarco_data_factory(self, phase_delays_data, controller_key):
        if not phase_delays_data or phase_delays_data[0][0] == "Streams":
            return []
        else:
            phase_delay_records = []
            for phase_delay in phase_delays_data[1:]:
                phase_delay_records.append(
                    {
                        "controller_key": controller_key,
                        "phase_ref": phase_delay[1],
                        "end_stage_key": str_to_int(phase_delay[2]),
                        "start_stage_key": str_to_int(phase_delay[3]),
                        "delay_time": str_to_int(phase_delay[4]),
                        "is_absolute": True,
                    }
                )
            return phase_delay_records

    def prohibited_stage_move_swarco_data_factory(self, move_sets_data, table_dict, controller_key):
        for move_set in move_sets_data:
            if move_set[0] == "Urban Traffic Control (UTC)":
                set_number = move_set[1]
                break
        else:
            set_number = 1

        utc_move_set_data = table_dict[f"SET {set_number}"]
        prohibited_stage_move_records = []
        for i, move_set_row in enumerate(utc_move_set_data[1:]):
            end_stage_key = utc_move_set_data[i + 1][0]
            for j, move_set_record in enumerate(move_set_row[1:]):
                start_stage_key = utc_move_set_data[0][j + 1]
                if move_set_record == "-":
                    prohibited_stage_move_records.append(
                        {
                            "controller_key": controller_key,
                            "end_stage_key": str_to_int(end_stage_key),
                            "start_stage_key": str_to_int(start_stage_key),
                            "prohibited": True,
                            "ignore": False,
                            "via_stage_key": False,
                        }
                    )
        return prohibited_stage_move_records

    def get_page(self, pdf, find_str, start_page=0):
        for page in pdf.pages[start_page:]:
            page_txt = page.extract_text()
            if find_str in page_txt:
                return page
        else:
            return None

    def get_stages_in_streams(self, pdf, phases_in_stages):
        page = self.get_page(pdf, "Phases, Stages and Streams")
        if not page:
            page = self.get_page(pdf, "Streams, Stages, Phases Control")
        page_txt_list = page.extract_text().split("\n")
        num_streams = int(self.get_text_after_substrings(page_txt_list, "Current Number of Streams"))
        num_stages = int(
            self.get_text_before_substrings(page_txt_list, "Number of Switched Signs", "Current Number of stages")
        )
        num_table_cells = (num_streams + 1) * (num_stages + 1)
        num_table_cells_alt = (num_streams + 1) * num_stages
        page = self.get_page(pdf, "Stages in Streams")
        tables = page.find_tables()
        for table in tables:
            if len(table.rows) == num_streams + 1 and num_stages + 1 <= len(table.rows[0].cells) <= num_stages + 2:
                stages_table = table
                break
        else:
            for table in tables:
                if len(table.cells) == num_table_cells_alt:
                    stages_table = table
                    break
            else:
                raise ValueError
        table_rects_1 = [a for a in page.objects["rect"] if int(a["width"]) == 10 or int(a["width"]) == 12]
        stages_table_data = stages_table.extract()
        stages_in_streams = []
        for rect in table_rects_1:
            cell_i, cell_j = self.get_cell_index_containing_rect(stages_table, rect)
            stage_num = "".join(ch for ch in stages_table_data[0][cell_j] if ch.isdigit())
            stage_in_stream = {"stream_number": int(stages_table_data[cell_i][0]) + 1, "stage_number": int(stage_num)}
            if stage_in_stream not in stages_in_streams:
                stages_in_streams.append(stage_in_stream)
        stages_in_streams = sorted(stages_in_streams, key=lambda x: x["stream_number"])
        stages_in_streams_dict = {s["stage_number"]: s for s in stages_in_streams}
        for phase_in_stage in phases_in_stages:
            if phase_in_stage["stage_number"] not in stages_in_streams_dict.keys():
                stage_number = phase_in_stage["stage_number"]
                stage_in_stream = {
                    "stream_number": stages_in_streams_dict.get(stage_number - 1)["stream_number"],
                    "stage_number": stage_number,
                }
                stages_in_streams.append(stage_in_stream)
                stages_in_streams_dict[stage_number] = stage_in_stream
                self.signal_emulator.logger.info(f"Stage in stream added from phases in stages: {stage_in_stream}")

        return stages_in_streams

    def phase_telent_data_factory(self, pdf, controller_key):
        page = self.get_page(pdf, "Phase data 1", 1)
        tables = page.find_tables()
        phases_table = tables[0]
        phases_table_data = phases_table.extract()
        phase_tncs = []
        for phase in phases_table_data[2:]:
            phase_tncs.append(
                {
                    "controller_key": controller_key,
                    "phase_ref": phase[0],
                    "min_time": 0,
                    "text": phase[1],
                    "phase_type_str": self.TELENT_PHASE_TYPE_DICT[phase[2]],
                    "appearance_type_int": str_to_int(phase[3]),
                    "termination_type_int": str_to_int(phase[5]),
                    "associated_phase_ref": phase[4] if phase[4] else phase[6],
                }
            )
        return phase_tncs

    def phase_motus_data_factory(self, pdf, controller_key):
        page = self.get_page(pdf, "Phase and Stage Allocation", 1)
        tables = page.find_tables()
        phases_table = tables[0]
        phases_table_data = phases_table.extract()
        phase_tncs = []
        previous_phase_ref = "@"
        phase_ref_offset = 0
        for phase in phases_table_data[1:]:
            if phase[0] == "":
                phase_ref = chr(ord(previous_phase_ref) + 1)
                phase_ref_offset += 1
            else:
                phase_ref = chr(ord(phase[0]) + phase_ref_offset)
            phase_tncs.append(
                {
                    "controller_key": controller_key,
                    "phase_ref": phase_ref,
                    "min_time": str_to_int(phase[6]),
                    "text": phase[1],
                    "phase_type_str": self.get_motus_phase_type(phase[1], phase[2]),
                    "appearance_type_int": self.MOTUS_APPEARANCE_TYPE_DICT[phase[3].replace("\n", " ").upper()],
                    "termination_type_int": self.MOTUS_TERMINATION_TYPE_DICT[phase[4].replace("\n", " ").upper()],
                    "associated_phase_ref": None if phase[5] == "-" else phase[5],
                }
            )
            previous_phase_ref = phase_ref
        return phase_tncs

    def phase_siemens_data_factory(self, pdf, controller_key):
        page = self.get_page(pdf, "Phase Type and Conditions")
        page_txt = page.extract_text().split("\n")
        i = 0
        phase_tncs = []
        for i, row in enumerate(page_txt):
            if "Phase Title Type Type Type Phase" in row:
                break

        for row in page_txt[i + 1 : -4]:
            row_split = row.split("-")
            last_word = row.split()[-1]
            if len(last_word) == 1:
                associated_phase = last_word
            else:
                associated_phase = None
            phase_tncs.append(
                {
                    "controller_key": controller_key,
                    "phase_ref": row[0],
                    "min_time": 0,
                    "text": row_split[0][2:-3],
                    "phase_type_str": self.get_siemens_phase_type(row),
                    "appearance_type_int": str_to_int(row_split[1].split()[-2]),
                    "termination_type_int": str_to_int(row_split[1].split()[-1]),
                    "associated_phase_ref": associated_phase,
                }
            )
        return phase_tncs

    def get_siemens_phase_type(self, row):
        if "UK Traffic" in row:
            return "T"
        elif "UK Far Side Pedestrian" in row:
            return "P"
        elif "UK Near Side Pedestrian" in row:
            return "P"
        elif "UK GreenArrow" in row:
            return "D"
        else:
            raise ValueError

    def get_motus_phase_type(self, title, phase_type):
        if "dummy" in title.lower():
            return "D"
        elif phase_type == "UK TN":
            return "P"
        elif phase_type == "UK Traffic":
            return "T"
        else:
            raise ValueError

    def intergreen_telent_data_factory(self, pdf, controller_key):
        page = self.get_page(pdf, "Minimum intergreen durations", 1)
        intergreens_table = page.find_tables()[0]
        intergreens_table_data = intergreens_table.extract()[1:]
        intergreen_records = []
        for i, row in enumerate(intergreens_table_data[1:]):
            for j, cell in enumerate(row[1:]):
                if cell and cell != "":
                    intergreen_records.append(
                        {
                            "controller_key": controller_key,
                            "end_phase_key": intergreens_table_data[i + 1][0],
                            "start_phase_key": intergreens_table_data[0][j + 1],
                            "intergreen_time": str_to_int(cell),
                        }
                    )
        return intergreen_records

    def intergreen_motus_data_factory(self, pdf, controller_key):
        page = self.get_page(pdf, "Intergreen Table F006", 3)
        intergreens_table = page.find_tables()[-1]
        intergreens_table_data = intergreens_table.extract()
        intergreen_records = []
        for i, row in enumerate(intergreens_table_data[1:]):
            for j, cell in enumerate(row[1:]):
                if cell and cell != "":
                    intergreen_records.append(
                        {
                            "controller_key": controller_key,
                            "end_phase_key": intergreens_table_data[i + 1][0],
                            "start_phase_key": intergreens_table_data[0][j + 1],
                            "intergreen_time": str_to_int(cell),
                        }
                    )
        return intergreen_records

    def intergreen_siemens_data_factory(self, pdf, controller_key):
        page = self.get_page(pdf, "Phase Intergreen Times")
        intergreens_table = page.find_tables()[-1]
        intergreens_table_data = intergreens_table.extract()
        if "Note: On a Stand" in intergreens_table_data[0][0] and "PAR)" in intergreens_table_data[1][0]:
            intergreens_table_data = intergreens_table_data[2:]
        intergreen_records = []
        for i, row in enumerate(intergreens_table_data[1:]):
            for j, cell in enumerate(row[1:]):
                if cell != "":
                    intergreen_records.append(
                        {
                            "controller_key": controller_key,
                            "end_phase_key": intergreens_table_data[i + 1][0],
                            "start_phase_key": intergreens_table_data[0][j + 1],
                            "intergreen_time": str_to_int(cell),
                        }
                    )
        return intergreen_records

    def phase_delay_motus_data_factory(self, pdf, controller_key):
        page = self.get_page(pdf, "5 Phase Delays", 3)
        if not page:
            return []
        page_txt = page.extract_text()
        if "There are none" in page_txt:
            return []
        else:
            raise NotImplementedError
        i = 0
        phase_delays = []
        for i, row in enumerate(page_txt):
            if row == "Phase from Stage Stage Seconds Phase from Stage Stage Seconds":
                break

        for row in page_txt[i + 1 : -1]:
            row_split = row.split(" ")
            if len(row_split) > 4:
                phase_delays.append(
                    {
                        "controller_key": controller_key,
                        "phase_ref": row_split[1],
                        "end_stage_key": str_to_int(row_split[2]),
                        "start_stage_key": str_to_int(row_split[3]),
                        "delay_time": str_to_int(row_split[4]),
                        "is_absolute": True,
                    }
                )
            if len(row_split) > 8:
                phase_delays.append(
                    {
                        "controller_key": controller_key,
                        "phase_ref": row_split[6],
                        "end_stage_key": row_split[7],
                        "start_stage_key": row_split[8],
                        "delay_time": row_split[9],
                        "is_absolute": True,
                    }
                )
        return phase_delays

    def phase_delay_siemens_data_factory(self, pdf, controller_key):
        page = self.get_page(pdf, "Phase Delays 0-29")
        if not page:
            return []
        page_txt = page.extract_text().split("\n")
        i = 0
        phase_delays = []
        for i, row in enumerate(page_txt):
            if row == "Phase from Stage Stage Seconds Phase from Stage Stage Seconds":
                break

        for row in page_txt[i + 1 : -1]:
            row_split = row.split(" ")
            if len(row_split) > 4:
                phase_delays.append(
                    {
                        "controller_key": controller_key,
                        "phase_ref": row_split[1],
                        "end_stage_key": str_to_int(row_split[2]),
                        "start_stage_key": str_to_int(row_split[3]),
                        "delay_time": str_to_int(row_split[4]),
                        "is_absolute": True,
                    }
                )
            if len(row_split) > 8:
                phase_delays.append(
                    {
                        "controller_key": controller_key,
                        "phase_ref": row_split[6],
                        "end_stage_key": row_split[7],
                        "start_stage_key": row_split[8],
                        "delay_time": row_split[9],
                        "is_absolute": True,
                    }
                )
        return phase_delays

    def controller_telent_data_factory(self, pdf, controller_key):
        page = self.get_page(pdf, "Telent traffic controller configuration forms")
        page_txt_list = page.extract_text().split("\n")
        controller_records = [
            {
                "controller_key": controller_key,
                "controller_type": "TELENT",
                "x_coord": 0,
                "y_coord": 0,
                "address": self.get_text_after_substrings(page_txt_list, "Intersection description: "),
                "spec_issue_no": self.get_text_between_substrings(page_txt_list, "Issue: ", "Configuration engineer"),
                "is_pedestrian_controller": False,
            }
        ]
        return controller_records

    def controller_motus_data_factory(self, pdf, controller_key):
        page = self.get_page(pdf, "Junction Information", 1)
        page_txt = page.extract_text()
        controller_records = [
            {
                "controller_key": controller_key,
                "controller_type": "MOTUS",
                "x_coord": 0,
                "y_coord": 0,
                "address": "",
                "spec_issue_no": "",
                "is_pedestrian_controller": False,
            }
        ]
        return controller_records

    def controller_siemens_data_factory(self, pdf, controller_key):
        page = self.get_page(pdf, "Administration")
        page_txt = page.extract_text()
        page_txt_list = page_txt.split("\n")
        controller_records = [
            {
                "controller_key": controller_key,
                "controller_type": self.get_text_between_substrings(page_txt_list, "Hardware", "Firmware"),
                "x_coord": 0,
                "y_coord": 0,
                "address": self.get_text_after_substrings(page_txt_list, "Intersection", ": "),
                "spec_issue_no": self.get_text_after_substrings(page_txt_list, "Issue"),
                "is_pedestrian_controller": False,
            }
        ]
        return controller_records

    def get_text_between_substrings(self, page_txt_list, substring_1, substring_2):
        for line in page_txt_list:
            start_index = line.find(substring_1)
            end_index = line.find(substring_2)
            if start_index != -1 and end_index != -1:
                # Get the text between the substrings (excluding the substrings themselves)
                result = line[start_index + len(substring_1) : end_index].strip()
                return result

    def get_text_after_substrings(self, page_txt_list, substring, strip_substring=None):
        for line in page_txt_list:
            index = line.find(substring)
            if index != -1:
                # Get the text between the substrings (excluding the substrings themselves)
                result = line[index + len(substring) :].strip()
                if strip_substring:
                    return result.replace(strip_substring, "")
                else:
                    return result

    def get_text_before_substrings(self, page_txt_list, substring, strip_substring=None):
        for line in page_txt_list:
            index = line.find(substring)
            if index != -1:
                # Get the text between the substrings (excluding the substrings themselves)
                result = line[:index].strip()
                if strip_substring:
                    return result.replace(strip_substring, "")
                else:
                    return result

    def phase_siemens_data_factory_old(self, phase_type_and_conditions, controller_key):
        phase_records = []
        for phase in phase_type_and_conditions:
            phase_records.append(
                {
                    "controller_key": controller_key,
                    "phase_ref": phase["phase_ref"],
                    "min_time": 0,
                    "phase_type_str": phase["type"],
                    "text": phase["phase_name"],
                    "associated_phase_ref": phase["associated phase"],
                    "appearance_type_int": phase["appearance type"],
                    "termination_type_int": phase["termination type"],
                }
            )
        return phase_records

    def stage_siemens_data_factory(self, stages_in_streams, phases_in_stages, phase_records, controller_key):
        phase_records_dict = {a["phase_ref"]: a for a in phase_records}
        if not any([a["stage_number"] == 0 for a in stages_in_streams]):
            stages_in_streams.insert(0, {"stage_number": 0, "stream_number": 1})

        phases_in_stages_dict = defaultdict(list)
        for phase_in_stage in phases_in_stages:
            phases_in_stages_dict[phase_in_stage["stage_number"]].append(phase_in_stage["phase_ref"])
        stage_records = []
        stream_stage_number = 0
        previous_stage = None
        for stage in stages_in_streams:
            if previous_stage and previous_stage["stream_number"] != stage["stream_number"]:
                stream_stage_number = 0
            elif previous_stage and previous_stage["stream_number"] == stage["stream_number"]:
                stream_stage_number += 1

            if stream_stage_number == 0:
                phases_in_stage = phases_in_stages_dict[stage["stage_number"]]
                for phase_key in phases_in_stage:
                    phase_record = phase_records_dict[phase_key]
                    if phase_record["phase_type_str"] != "D" and "dummy" not in phase_record["text"].lower():
                        stream_stage_number = 1

            stage_records.append(
                {
                    "controller_key": controller_key,
                    "stream_number": str_to_int(stage["stream_number"]),
                    "stage_number": str_to_int(stage["stage_number"]),
                    "stream_stage_number": stream_stage_number,
                    "stage_name": f'Stage {stage["stage_number"]}',
                    "phase_keys_in_stage": phases_in_stages_dict[stage["stage_number"]],
                }
            )
            previous_stage = stage
        for stage in stage_records:
            if stage["stream_stage_number"] == 0:
                for phase_key in stage["phase_keys_in_stage"]:
                    phase_record = phase_records_dict[phase_key]
                    if phase_record["phase_type_str"] != "D" and "dummy" not in phase_record["text"].lower():
                        self.signal_emulator.logger.warning(
                            f"Stage definition error likely: {controller_key} - {stage}"
                        )
        return stage_records

    def remove_new_lines(self, phase_conditions):
        return [[s.replace("\n", " ") for s in row] for row in phase_conditions]


if __name__ == "__main__":
    pdf_path = r"D:\gitworks\signal_emulator\signal_emulator\resources\connect_plus\J05111x - M25 J2 - South\Configuration File\M25_J2_cont1_R12.pdf"
    cpcp = ConnectPlusConfigParser()
    tables = cpcp.parse_siemens_config_pdf(pdf_path)
