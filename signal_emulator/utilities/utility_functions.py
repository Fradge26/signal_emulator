import csv
import glob
import json
from datetime import datetime, timedelta, time


def load_json_to_dict(json_file_path) -> dict:
    """
    Function to load a json file to a dict
    :param json_file_path: json file path
    :return: dict
    """
    with open(json_file_path, "r") as json_file:
        json_data = json.load(json_file)
    return json_data


def dict_to_json_file(data, output_file_path):
    """
    Function to write a dict to json file
    :param data: dict data
    :param output_file_path: output file path
    :return: None
    """
    with open(output_file_path, "w") as json_file:
        json.dump(data, json_file, indent=4)


def txt_file_to_list(txt_file_path) -> list:
    """
    Function to read a text file to list
    :param txt_file_path: text file path
    :return: 1D list
    """
    my_file = open(txt_file_path, "r")
    data = my_file.read()
    data = data.split("\n")
    return data


def csv_file_to_list(csv_file_path) -> list:
    """
    Function to read a csv file to list
    :param csv_file_path: csv file path
    :return: 2D list
    """
    data_2d_list = []
    with open(csv_file_path, "r") as csv_file:
        csv_reader = csv.reader(csv_file)
        for row in csv_reader:
            data_2d_list.append(row)
    return data_2d_list


def time_string_to_seconds(time_str, time_format="%H:%M:%S") -> float:
    """
    Function to calculate total seconds from time string
    :param time_str:
    :param time_format: time format, as used by datetime strptime
    :return: total seconds
    """
    time_obj = datetime.strptime(time_str, time_format)
    total_seconds = timedelta(
        hours=time_obj.hour, minutes=time_obj.minute, seconds=time_obj.second
    ).total_seconds()
    return total_seconds


def time_str_to_timedelta(time_str) -> timedelta:
    """
    Function to convert a time string in format hh:mm:ss to timedelta
    :param time_str: time string
    :return: timedelta
    """
    hours, minutes, seconds = map(int, time_str.split(":"))
    timedelta_obj = timedelta(hours=hours, minutes=minutes, seconds=seconds)
    return timedelta_obj


def time_str_to_time(time_str) -> time:
    """
    Function to convert a time string in format hh:mm:ss to timedelta
    :param time_str: time string
    :return: timedelta
    """
    hours, minutes, seconds = map(int, time_str.split(":"))
    time_obj = time(hour=hours, minute=minutes, second=seconds)
    return time_obj


def list_to_csv(data, output_path, delimiter=","):
    """
    Function to write a 2D list to csv
    :param data: list of data to write
    :param output_path: output file path
    :param delimiter: file delimiter
    :return: None
    """
    # Open the CSV file in write mode
    with open(output_path, "w", newline="") as csvfile:
        # Create a CSV writer object
        csv_writer = csv.writer(csvfile, delimiter=delimiter)
        # Write each row of the 2D list to the CSV file
        for row in data:
            csv_writer.writerow(row)


def list_to_txt(data, file_path):
    """
    Method to write a list to text file
    :param data: list data
    :param file_path: output file path
    :return: None
    """
    with open(file_path, "w") as file:
        # Iterate through the list and write each element to the file
        for row in data:
            file.write(str(row) + "\n")


def str_to_int(value) -> int | float | None:
    """
    Function to convert numeric strings to int or float
    :param value: value
    :return: int or float
    """
    if isinstance(value, int):
        return value
    elif isinstance(value, float):
        return int(value)
    elif isinstance(value, str):
        value = value.strip()
        if value == "":
            return 0
        elif value.isnumeric():
            return int(value)
    elif value is None:
        return None
    else:
        raise ValueError


def clean_stage_name(value) -> str:
    """
    Function to clean the stage name from timing sheet csv
    :param value: stage name
    :return: cleaned stage name
    """
    return value.strip().replace("\\t", "").replace("\\", "").replace("&apos", "")


def clean_site_number(site_number) -> str:
    """
    Function to clean the site number from timing sheet csv
    :param site_number: site number string
    :return: cleaned site number
    """
    parts = site_number.split("/")
    if parts[0].isnumeric():
        parts[0] = f"J{parts[0]}"
    elif parts[0][0].isalpha():
        parts[0] = f"J{parts[0][1:]}"
    return f"{parts[0]}/{parts[1][-3:]}"


def read_fixed_width_file(file_path, column_widths):
    """
    Function to read a text file with fixed width columns
    :param file_path: file path
    :param column_widths: column widths
    :return: list
    """
    data = []  # This list will store the data
    with open(file_path, "r") as file:
        lines = file.read().splitlines()  # Read lines from the file
        for line in lines:
            start = 0
            row = []
            # Split each line into columns based on the column widths
            for width in column_widths:
                end = start + width
                row.append(line[start:end].strip())  # Remove leading/trailing spaces
                start = end
            data.append(row)  # Add the row to the data list
    return data


def filter_lines_after(data, search_string, column_index=0) -> list:
    """
    Function to slice list up until line containing search string is found
    :param data: list data
    :param search_string: search string
    :param column_index: column index to search in
    :return: list
    """
    for i, line in enumerate(data):
        if search_string in line[column_index]:
            return data[:i]
    else:
        return data

def filter_lines_after_double_slash(data) -> list:
    """
    Function to slice list up until line containing search string is found
    :param data: list data
    :return: list
    """
    for i, line in enumerate(data):
        if line[0].count("/") == 2:
            return data[:i]
    else:
        return data


def filter_pja_file(data, search_string, column_index=0) -> list:
    """
    Function to filter a PJA file.
    Lines are filtered, then blank lines are removed
    :param data: list data
    :param search_string: search string
    :param column_index: column index
    :return: list
    """
    filtered_data = filter_lines_after(data, search_string, column_index)
    filtered_data = filter_lines_after_double_slash(filtered_data)
    return [a for a in filtered_data if a[1] != ""]


def find_files_with_extension(directory, extension):
    """
    function return all files in subdirectories with extension
    :param directory: base directory
    :param extension: extension
    :return: list of file paths
    """
    pattern = f"{directory}/**/*.{extension}"
    files = glob.glob(pattern, recursive=True)
    return files
