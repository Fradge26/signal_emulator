import os

import pytest

from signal_emulator.emulator import SignalEmulator
from signal_emulator.file_parsers.timing_sheet_parser import TimingSheetParser
from signal_emulator.utilities.utility_functions import load_json_to_dict


@pytest.fixture(scope="module")
def signal_emulator():
    # Perform common setup actions here, if needed
    # This fixture can be reused across multiple test functions
    current_directory = os.path.dirname(os.path.abspath(__file__))
    parent_directory = os.path.dirname(current_directory)
    os.chdir(parent_directory)
    signal_emulator_config = load_json_to_dict(
        json_file_path="tests/resources/signal_emulator_empty_config.json"
    )
    signal_emulator = SignalEmulator(config=signal_emulator_config)
    yield signal_emulator


@pytest.fixture(scope="module")
def timing_sheet_parser():
    """
    Fixture for initialising the Timing Sheet Parser
    :return: Timing Sheet Parser object
    """
    # Perform common setup actions here, if needed
    # This fixture can be reused across multiple test functions
    current_directory = os.path.dirname(os.path.abspath(__file__))
    parent_directory = os.path.dirname(current_directory)
    os.chdir(parent_directory)
    timing_sheet_parser = TimingSheetParser()
    yield timing_sheet_parser


@pytest.mark.usefixtures("timing_sheet_parser")
@pytest.mark.usefixtures("signal_emulator")
@pytest.mark.parametrize(
    "timing_sheet_path, expected_stage_phase_keys",
    [
        (
            "tests/resources/timing_sheets/00_000004_Junc.csv",
            {
                ("J00/004", 0): ["Q"],
                ("J00/004", 1): ["A", "I", "G", "B"],
                ("J00/004", 2): ["A", "J", "I", "H", "G", "C"],
                ("J00/004", 3): ["D", "E", "F", "H"],
                ("J00/004", 4): ["B", "F", "G", "I", "U"],
                ("J00/004", 5): ["D", "V", "I", "H", "F"],
                ("J00/004", 6): ["E", "W", "F", "H", "G"],
                ("J00/004", 7): ["R"],
                ("J00/004", 8): ["M"],
                ("J00/004", 9): ["N"],
                ("J00/004", 10): ["S"],
                ("J00/004", 11): ["K"],
                ("J00/004", 12): ["L"],
                ("J00/004", 13): ["T"],
                ("J00/004", 14): ["O"],
                ("J00/004", 15): ["P"],
            },
        ),
    ],
)
def test_timing_sheet_parser_phases_in_streams(
    timing_sheet_parser, signal_emulator, timing_sheet_path, expected_stage_phase_keys
):
    signal_emulator.load_timing_sheet_csv(timing_sheet_path)
    assert signal_emulator.streams.num_items == 4
    assert signal_emulator.stages.num_items == 16
    assert signal_emulator.phases.num_items == 23
    for stage_key, phase_keys in expected_stage_phase_keys.items():
        stage = signal_emulator.stages.get_by_key(stage_key)
        assert sorted(stage.phase_keys_in_stage) == sorted(phase_keys)

    # test that all phases exist in exactly one stream
    all_stream = []
    for stream in signal_emulator.streams:
        all_stream.extend(stream.phases_in_stream)
    assert set(all_stream) == set(signal_emulator.phases.get_all())


@pytest.mark.usefixtures("timing_sheet_parser")
@pytest.mark.usefixtures("signal_emulator")
@pytest.mark.parametrize(
    "timing_sheet_path, expected_stage_details",
    [
        (
            "tests/resources/timing_sheets/00_000004_Junc.csv",
            {
                ("J00/004", 0): [0, 0, 0],
                ("J00/004", 1): [0, 1, 1],
                ("J00/004", 2): [0, 2, 2],
                ("J00/004", 3): [0, 3, 3],
                ("J00/004", 4): [0, 4, 4],
                ("J00/004", 5): [0, 5, 5],
                ("J00/004", 6): [0, 6, 6],
                ("J00/004", 7): [1, 7, 0],
                ("J00/004", 8): [1, 8, 1],
                ("J00/004", 9): [1, 9, 2],
                ("J00/004", 10): [2, 10, 0],
                ("J00/004", 11): [2, 11, 1],
                ("J00/004", 12): [2, 12, 2],
                ("J00/004", 13): [3, 13, 0],
                ("J00/004", 14): [3, 14, 1],
                ("J00/004", 15): [3, 15, 2],
            },
        ),
        (
            "tests/resources/timing_sheets/05_000078_Junc.csv",
            {
                ("J05/078", 0): [0, 0, 0],
                ("J05/078", 1): [0, 1, 1],
                ("J05/078", 2): [0, 2, 2],
                ("J05/078", 3): [1, 3, 0],
                ("J05/078", 4): [1, 4, 1],
                ("J05/078", 5): [1, 5, 2],
            },
        ),
    ],
)
def test_timing_sheet_parser_stage_numbers(
    timing_sheet_parser, signal_emulator, timing_sheet_path, expected_stage_details
):
    signal_emulator.load_timing_sheet_csv(timing_sheet_path)
    for stage_key, (
        stream_number,
        stage_number,
        stream_stage_number,
    ) in expected_stage_details.items():
        stage = signal_emulator.stages.get_by_key(stage_key)
        assert stage.stream_number == stream_number
        assert stage.stage_number == stage_number
        assert stage.stream_stage_number == stream_stage_number
