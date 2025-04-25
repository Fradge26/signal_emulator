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


class SADParser:
    """
    Class to represent SAD file parser. SAD files are read, processed and exported as M37 format
    """

    def __init__(self):
        """
        Constructor for SADParser
        """
        self.site_states = defaultdict(lambda: "PRE")
        self.controller_events = defaultdict(list)
        self.m37s = []

    def process_zipped_sad_folder(self, sad_folder):
        """
        Method to process a folder containing SAD files. Folder and sub folders are searched
        :param sad_folder: SAD folder
        :return: None
        """
        files_by_area = defaultdict(lambda: defaultdict(list))
        for root, dirs, files in os.walk(sad_folder):
            for file in files:
                if file.endswith(".gz"):
                    area = Cell[file[15:20]]
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
                self.process_sad_file(area, files, date)

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

    def process_sad_file(self, cell, file_objects, sad_datetime):
        """
        Method to process SAD file
        :param cell: UTC Cell
        :param file_objects: list containing file objects for the day
        :param sad_datetime: date
        :return: None
        """
        t3 = datetime.now()
        # chain the csv readers together so that 5 minute chunks of data is read as a continuous stream
        csv_reader = chain(*[csv.reader(file_object) for file_object in file_objects])
        for line in csv_reader:
            if self.is_data_line(line):
                stage_id = self.get_stage_id(line[5])
                site_id = self.get_site_id(line)
                if self.is_new_state(site_id, stage_id):
                    if self.site_states[site_id] == "PRE" and stage_id != "" or self.is_stage_id_error(line[5]):
                        continue
                    t = datetime.strptime(line[1].strip(), "%H:%M:%S")
                    delta = timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)

                    self.controller_events[site_id].append(
                        ControllerEvent(site=site_id, stage=stage_id, timestamp=sad_datetime + delta)
                    )
                    self.site_states[site_id] = stage_id
        t4 = datetime.now()
        print("processing", t4 - t3)
        print(len(self.controller_events))
        self.process_controller_events()
        self.write_m37_to_csv(f"resources/M37/converted_from_sad/M37_{sad_datetime.strftime('%Y%m%d')}_{cell.name}.csv")
        # close the file objects!
        for file_obj in file_objects:
            file_obj.close()

    @staticmethod
    def is_stage_id_error(stage_string):
        error = re.findall("(& G\w& G)", stage_string)
        return bool(error)

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
        for site, events in self.controller_events.items():
            for i in range(0, len(events) - 2, 2):
                this_interstage = events[i]
                this_stage = events[i + 1]
                next_interstage = events[i + 2]
                self.m37s.append(
                    M37(
                        timestamp=this_stage.timestamp,
                        node_id=site,
                        site_id=site,
                        message_id="M37",
                        utc_stage_id=this_stage.stage,
                        length=int((next_interstage.timestamp - this_interstage.timestamp).total_seconds()),
                        green_time=int((next_interstage.timestamp - this_stage.timestamp).total_seconds()),
                        interstage_time=int((this_stage.timestamp - this_interstage.timestamp).total_seconds()),
                    )
                )

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
        sorted_m37s = sorted(self.m37s, key=lambda x: (x.timestamp, x.site_number))

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


@dataclass
class ControllerEvent:
    """
    Dataclass for a controller event
    """

    site: str
    stage: str
    timestamp: CustomDatetime


@dataclass
class M37:
    """
    Dataclass for an M37 file row
    """

    timestamp: CustomDatetime
    message_id: str
    node_id: str
    site_id: str
    utc_stage_id: str
    length: int
    green_time: int
    interstage_time: int


if __name__ == "__main__":
    sp = SADParser()
    t1 = datetime.now()
    sp.process_zipped_sad_folder("resources/OTU")
    # sp.process_unzipped_sad_file("resources\OTU\JAN012023_0000_CNTRA.txt\JAN012023_0000_CNTRA.txt")
    t2 = datetime.now()
    print("total", t2 - t1)
