import csv
import gzip
import os
import re
from collections import defaultdict
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from itertools import chain

from signal_emulator.enums import Cell
from signal_emulator.utilities.utility_functions import list_to_csv


class SignalEventParser:
    """
    Class to represent SAD file parser. SAD files are read, processed and exported as M37 format
    """

    def __init__(self):
        """
        Constructor for SADParser
        """
        self.site_states = defaultdict(lambda: "PRE")
        self.controller_events = defaultdict(list)
        self.m37_time_by_site = defaultdict(lambda: M37Time())
        self.m37s = []

    def process_signal_event_folder(self, signal_event_folder, output_folder="resources/M37/converted_from_sad"):
        """
        Method to process a folder containing SAD files. Folder and sub folders are searched
        :param signal_event_folder: Signal event folder
        :return: None
        """
        files_by_area = defaultdict(lambda: defaultdict(list))
        for root, dirs, files in os.walk(signal_event_folder):
            for file in files:
                if file.endswith(".csv"):
                    area = Cell[file[15:19]]
                    date = CustomDatetime.strptime(file[:9], "%b%d%Y")
                    file_path = os.path.join(root, file)
                    files_by_area[area][date].append(file_path)

        csv_files_by_area = defaultdict(dict)
        for area, dates in files_by_area.items():
            for date, files in dates.items():
                files_by_area[area][date] = sorted(
                    files, key=lambda s: datetime.strptime(os.path.basename(s)[:14], "%b%d%Y_%H%M")
                )
                csv_files_by_area[area][date] = self.get_csv_file_objects_from_paths(files)

        for area, dates in csv_files_by_area.items():
            for date, files in dates.items():
                self.process_sad_file(area, files, date, output_folder)

    @staticmethod
    def get_csv_file_objects_from_paths(csv_files_paths):
        """
        Function to return a list of file objects from csv paths
        :param csv_files_paths: list of csv file paths
        :return: list file objects
        """
        csv_file_objects = []
        for file_path in csv_files_paths:
            if file_path.endswith(".gz"):
                csv_file_objects.append(gzip.open(file_path, "rt", encoding="utf-8"))
            else:
                csv_file_objects.append(open(file_path, "r", newline=""))
        return csv_file_objects

    def process_zipped_sad_file(self, sad_path):
        """
        Method to process a zipped SAD file
        :param sad_path: SAD path
        :return: None
        """
        sad_datetime = self.get_datetime_from_sad_path(sad_path)
        cell = self.get_cell_from_sad_path(sad_path)
        with gzip.open(sad_path, "rt", encoding="utf-8") as gz_file:
            csv_reader = csv.reader(gz_file)
            self.process_sad_file(cell, csv_reader, sad_datetime)

    def process_sad_file(self, cell, file_objects, sad_datetime, output_folder):
        """
        Method to process SAD file
        :param cell: UTC Cell
        :param file_objects: list containing file objects for the day
        :param sad_datetime: date
        :return: None
        """
        t3 = datetime.now()

        previous_timestamp = defaultdict(lambda: None)
        # chain the csv readers together so that 5 minute chunks of data is read as a continuous stream
        csv_reader = chain(*[csv.reader(file_object) for file_object in file_objects])
        # for line in csv_reader:
        t55 = datetime.now()
        all_lines = [line for line in csv_reader]
        print("to list", datetime.now() - t55)
        num_lines = len(all_lines)
        for i in range(num_lines):
            line = all_lines[i]
            previous_line = all_lines[i - 1] if i > 0 else None
            next_line = all_lines[i + 1] if i < num_lines - 1 else None
            if self.is_data_line(line):
                if self.line_is_error(line, previous_line, next_line):
                    continue
                stage_id = f"G{line[6]}"
                site_id = line[0]
                event_time = CustomDatetime.strptime(line[1].strip(), "%Y-%m-%d %H:%M:%S")
                # print(event_time, site_id, stage_id)
                if previous_timestamp[site_id] and timedelta(minutes=5) < event_time - previous_timestamp[site_id]:
                    self.site_states[site_id] = "PRE"
                    self.m37_time_by_site[site_id] = M37Time()
                    aa = 55
                if self.is_new_state(site_id, stage_id):
                    if self.site_states[site_id] == "PRE" and stage_id != "G0":
                        continue

                    # if self.m37_time_by_site[site_id].interstage_time is None:
                    if self.m37_time_by_site[site_id].interstage_start_time is None:
                        self.m37_time_by_site[site_id] = M37Time()
                        self.m37_time_by_site[site_id].node_id = site_id
                        self.m37_time_by_site[site_id].site_id = site_id
                        self.m37_time_by_site[site_id].interstage_start_time = event_time

                    elif self.m37_time_by_site[site_id].stage_start_time is None:
                        self.m37_time_by_site[site_id].stage_start_time = event_time
                        self.m37_time_by_site[site_id].utc_stage_id = stage_id

                    elif self.m37_time_by_site[site_id].stage_end_time is None:
                        self.m37_time_by_site[site_id].stage_end_time = event_time
                        self.m37_time_by_site[site_id].timestamp = event_time
                        self.controller_events[site_id].append(self.m37_time_by_site[site_id])
                        self.m37_time_by_site[site_id] = M37Time()
                        self.m37_time_by_site[site_id].node_id = site_id
                        self.m37_time_by_site[site_id].site_id = site_id
                        self.m37_time_by_site[site_id].interstage_start_time = event_time

                    self.site_states[site_id] = stage_id

                previous_timestamp[site_id] = event_time
        t4 = datetime.now()
        print("processing", t4 - t3)
        print(len(self.controller_events))
        self.process_controller_events()
        self.write_m37_to_csv(os.path.join(output_folder, f"M37_{sad_datetime.strftime('%Y%m%d')}_{cell.name}.csv"))
        # close the file objects!
        for file_obj in file_objects:
            file_obj.close()

    @staticmethod
    def line_is_error(line, previous_line, next_line):
        """
        Function to determine if the line is erroneous and should be ignored. Lines with Interstage of 1 second time and
        no stage change between the previous and next line are identified as an error.
        :param line: current line
        :param previous_line: previous line
        :param next_line: next line
        :return: bool, True if is error
        """
        if line[13] == "1" and line[6] == "0" and previous_line[6] == next_line[6]:
            return True
        return line[12] == "1" and (line[13] == "1" or line[13] == "301")

    @staticmethod
    def get_site_id(line):
        """
        Function to get the site id
        :param line: SAD file line
        :return: Site id
        """
        site_type = "J" if line[2] == " JUN" else "P"
        return f"{site_type}{line[0].strip()}"

    @staticmethod
    def get_datetime_from_sad_path(sad_path):
        """
        Function to get the Datetime from SAD path. A custom datetime class is used so that the datetime object
        is formatted as required when writing to csv
        :param sad_path: SAD path
        :return: CustomDatetime
        """
        filename = os.path.basename(sad_path)
        filename_parts = filename.split(".")
        return CustomDatetime.strptime(filename_parts[0][:9], "%b%d%Y")

    @staticmethod
    def get_cell_from_sad_path(sad_path) -> Cell:
        """
        Function to get the UTC area from the SAD file path
        :param sad_path: SAD file path
        :return: Area Enum
        """
        filename = os.path.basename(sad_path)
        filename_parts = filename.split(".")
        return Cell[filename_parts[0][-5:]]

    def process_controller_events(self):
        """
        Method to process controller events
        :return: None
        """
        for site, m37_times in self.controller_events.items():
            for m37_time in m37_times:
                if m37_time.utc_stage_id == "GX":
                    # The PG stage
                    self.m37s.append(
                        M37(
                            timestamp=m37_time.stage_start_time + timedelta(seconds=1),
                            message_id="M37",
                            node_id=m37_time.node_id,
                            site_id=m37_time.site_id,
                            utc_stage_id="PG",
                            length=(m37_time.stage_start_time - m37_time.interstage_start_time).total_seconds(),
                            green_time=(m37_time.stage_start_time - m37_time.interstage_start_time).total_seconds(),
                            interstage_time=0,
                        )
                    )
                    # The GX stage
                    self.m37s.append(
                        M37(
                            timestamp=m37_time.timestamp + timedelta(seconds=1),
                            message_id="M37",
                            node_id=m37_time.node_id,
                            site_id=m37_time.site_id,
                            utc_stage_id="GX",
                            length=(m37_time.stage_end_time - m37_time.stage_start_time).total_seconds(),
                            green_time=(m37_time.stage_end_time - m37_time.stage_start_time).total_seconds(),
                            interstage_time=0,
                        )
                    )
                else:
                    self.m37s.append(
                        M37(
                            timestamp=m37_time.timestamp + timedelta(seconds=1),
                            message_id="M37",
                            node_id=m37_time.node_id,
                            site_id=m37_time.site_id,
                            utc_stage_id=m37_time.utc_stage_id,
                            length=(m37_time.stage_end_time - m37_time.interstage_start_time).total_seconds(),
                            green_time=(m37_time.stage_end_time - m37_time.stage_start_time).total_seconds(),
                            interstage_time=(
                                m37_time.stage_start_time - m37_time.interstage_start_time
                            ).total_seconds(),
                        )
                    )
        self.m37s = sorted(self.m37s, key=lambda x: (x.timestamp, x.site_id))

    def process_unzipped_sad_file(self, sad_path):
        """
        Method to process an unzipped SAD file
        :param sad_path: SAD path
        :return: None
        """
        sad_datetime = self.get_datetime_from_sad_path(sad_path)
        area = self.get_cell_from_sad_path(sad_path)
        self.process_sad_file(area, [open(sad_path, "r")], sad_datetime)

    @staticmethod
    def get_stage_id(stage_string):
        """
        Function to format the stage id from the string in SAD file
        :param stage_string: stage string
        :return: extract G formatted stage string
        """
        # regex expression to find G bit strings, if none found return ""
        stages = re.findall(r"(G\S|$)", stage_string)
        return stages[0]

    def is_new_state(self, site_id, stage_id):
        """
        Function to return True if site controller replies with a new stage state
        :param site_id: site id
        :param stage_id: stage id
        :return: boolean, True if new state
        """
        return stage_id != self.site_states[site_id]

    @staticmethod
    def is_data_line(line):
        """
        Function to return if line of SAD file contains data, not a header
        :param line: list of line data
        :return: boolean
        """
        if len(line) < 2:
            return False
        return len(line[0]) == 6 and line[0][2] == "/"

    @staticmethod
    def unzip_file(zip_file_path):
        """
        Function to unzip a zipfile and return the csv data as a list
        :param zip_file_path: zip file path
        :return: list
        """
        # Open the zip file for reading
        t5 = datetime.now()
        with gzip.open(zip_file_path, "rt", encoding="utf-8") as gz_file:
            csv_reader = csv.reader(gz_file)
            t6 = datetime.now()
            # Initialize a list to store the data
            t7 = datetime.now()
            data = []
            # Iterate through the rows in the CSV file and append them to the data list
            for row in csv_reader:
                data.append(row)
            t8 = datetime.now()
            print("unzip", t6 - t5)
            print("to list", t8 - t7)
        return data

    def write_m37_to_csv(self, output_path):
        """
        Write M37 data to csv file
        :param output_path: output csv path
        :return: None
        """
        out_data = []
        m37_fields = fields(self.m37s[0])
        out_data.append([field.name for field in m37_fields])
        sorted_m37s = sorted(self.m37s, key=lambda x: (x.timestamp, x.site_id))

        for m37 in sorted_m37s:
            out_data.append([getattr(m37, field.name) for field in m37_fields])
        list_to_csv(out_data, output_path)


class CustomDatetime(datetime):
    """
    Custom Datetime class, the __str__ and __repr__ methods have been replaced with the formatting
    required for M37 output files
    """

    def __repr__(self):
        return self.strftime("%Y-%m-%dT%H:%M:%SZ")

    def __str__(self):
        return self.strftime("%Y-%m-%dT%H:%M:%SZ")


class M37Time:
    """
    Class for an M37 times
    """

    def __init__(self):
        self.timestamp = None
        self.message_id = "M37"
        self.node_id = None
        self.site_id = None
        self.utc_stage_id = None
        self.interstage_start_time = None
        self.stage_start_time = None
        self.stage_end_time = None


@dataclass
class M37:
    """
    Dataclass for an M37 file row
    """

    timestamp: CustomDatetime = None
    message_id: str = "M37"
    node_id: str = None
    site_id: str = None
    utc_stage_id: str = None
    length: int = 0
    green_time: int = None
    interstage_time: int = None


if __name__ == "__main__":
    sep = SignalEventParser()
    t1 = datetime.now()
    sep.process_signal_event_folder(r"D:\s3\surface.data.tfl.gov.uk\Control\UTC\SignalEvents\CNTR\2023\05\10test")
    # sp.process_unzipped_sad_file("resources\OTU\JAN012023_0000_CNTRA.txt\JAN012023_0000_CNTRA.txt")
    t2 = datetime.now()
    print("total", t2 - t1)
