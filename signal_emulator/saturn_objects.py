from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from signal_emulator.controller import BaseCollection, BaseItem

if TYPE_CHECKING:
    from signal_emulator.emulator import SignalEmulator


@dataclass(eq=False)
class PhaseToSaturnTurn:
    signal_emulator: "SignalEmulator"
    controller_key: str
    phase_ref: str
    turn: int
    saturn_a_node: int
    saturn_b_node: int
    saturn_c_node: int

    def get_key(self):
        return self.controller_key, self.phase_ref, self.saturn_b_node, self.turn


class PhaseToSaturnTurns(BaseCollection):
    ITEM_CLASS = PhaseToSaturnTurn
    TABLE_NAME = "phase_to_saturn_turns"
    WRITE_TO_DATABASE = True

    def __init__(self, signal_emulator, saturn_lookup_file=None):
        super().__init__(item_data=[], signal_emulator=signal_emulator)
        self.signal_emulator = signal_emulator
        if saturn_lookup_file:
            self.load_from_saturn_lookup_file(saturn_lookup_file)

    def load_from_saturn_lookup_file(self, saturn_lookup_file):
        if os.path.exists(saturn_lookup_file):
            self.init_from_saturn_file(saturn_lookup_file)
        else:
            self.signal_emulator.logger.warning(f"SATURN lookup file: {saturn_lookup_file} does not exist")

    def load_from_att_file(self, signal_groups_att_path):
        df = pd.read_csv(signal_groups_att_path, skiprows=28, delimiter=";")
        df.rename(
            columns={
                "$SIGNALGROUP:SCNO": "SCNO",
                "CONCATENATE:LANETURNS\TURN\FROMLINK\LOHAM_FROM_NODE_NO": "FROM_LINK_FROM_NODE",
                "CONCATENATE:LANETURNS\TURN\FROMLINK\LOHAM_TO_NODE_NO": "FROM_LINK_TO_NODE",
                "CONCATENATE:LANETURNS\TURN\TOLINK\LOHAM_FROM_NODE_NO": "TO_LINK_FROM_NODE",
                "CONCATENATE:LANETURNS\TURN\TOLINK\LOHAM_TO_NODE_NO": "TO_LINK_TO_NODE",
            },
            inplace=True,
        )
        node_str_to_list = lambda x: [] if pd.isnull(x) else x.split("|")
        df["FROM_LINK_FROM_NODE"] = df["FROM_LINK_FROM_NODE"].apply(node_str_to_list)
        df["FROM_LINK_TO_NODE"] = df["FROM_LINK_TO_NODE"].apply(node_str_to_list)
        df["TO_LINK_FROM_NODE"] = df["TO_LINK_FROM_NODE"].apply(node_str_to_list)
        df["TO_LINK_TO_NODE"] = df["TO_LINK_TO_NODE"].apply(node_str_to_list)
        for row in df.to_dict(orient="records"):
            self.add_item(row, signal_emulator=self.signal_emulator)

    def init_from_saturn_file(self, saturn_lookup_file):
        with open(saturn_lookup_file, "r") as csvfile:
            csvreader = csv.DictReader(csvfile)
            for row in csvreader:
                self.add_item(row, signal_emulator=self.signal_emulator)

    def get_saturn_b_node(self, controller_number):
        for key, value in self.signal_emulator.phase_to_saturn_turns.data.items():
            if int(key[0].split("/")[1]) == controller_number:
                return value.saturn_b_node
        return ()


class SaturnCollection(BaseCollection):
    OUTPUT_VERSON = "v1"
    OUTPUT_HEADER = "* LoHAN P6 RGS Printout" + " " + OUTPUT_VERSON + "\n* " + str(date.today()) + "\n\n"
    COLUMNS = {}
    SATURN_TABLE_NAME = None
    # List of field lengths for a SATURN type-1 record
    SATURN_TYPE1_FIELD_LENS = [5, 5, 5, 5, 5, 5, 5, 5, 5]

    def __init__(self, item_data, signal_emulator, output_directory):
        super().__init__(item_data=item_data)
        self.signal_emulator = signal_emulator
        self.output_directory = output_directory

    def export_to_rgs_files(self, time_periods=None):
        if time_periods is None:
            time_periods = self.signal_emulator.time_periods.get_all()
        for time_period in time_periods:
            self.export_to_rgs_file(time_period)

    def export_to_rgs_file(self, time_period, output_path=None):
        if not output_path:
            output_path = os.path.join(
                self.output_directory,
                f"LoHAMP6_SignalGroupData_{self.OUTPUT_VERSON}_{time_period.name}.rgs",
            )
        Path(output_path).parent.mkdir(exist_ok=True, parents=True)
        with open(output_path, "w") as rgs_file:
            # Print the SATURN file header
            rgs_file.write(self.OUTPUT_HEADER)

            # Get a list of all distinct controllers for time period
            controllers = []
            for item in self:
                if item.time_period_id == time_period.name:
                    if item.signal_controller_number not in controllers:
                        controllers.append(item.signal_controller_number)

            # Iterate all distinct controllers for time period
            for controller_number in controllers:
                # Identify the cycle time of the current controller
                cycle_time = self._get_cycle_time(controller_number, time_period.name)
                # Get all distinct node-b's for the current controller and iterate (each will have it's own SATURN rec-1)
                node_bs = self._get_controller_saturn_nodes(controller_number)
                for node_b in node_bs:
                    # Iterate through cycle period second-by-second
                    cycle_seconds_phases = []
                    for t in range(0, cycle_time):
                        # For each second, check if a phase is set for current t
                        # If phase is set, add it to list for current second
                        phases_in_second = self._get_phases_in_second(controller_number, node_b, time_period, t)
                        cycle_seconds_phases.append(phases_in_second)

                    # Adjust list where phases wrap-around from end to start
                    cycle_seconds_phases = self._post_process_cycle_seconds_phases(cycle_seconds_phases)

                    # To store phases assoicated with previous second
                    last_phases_in_second = []
                    # To store last non-intergreen phases
                    last_non_intergreen = []
                    # To store list of phases being constructed to add to SATURN type-3 record
                    rec_3_list = []
                    # Stage duration
                    stage_duration = 0
                    # The initial intergreen (if present), summed to final intergreen
                    initial_intergreen = None
                    # Last intergreen, ready to add to next SATURN type-3 record
                    intergreen = 0

                    # Loop through all phases per second
                    for i, phases_in_second in enumerate(cycle_seconds_phases):
                        # Determine if a new SATURN type-3 record should be built
                        if (
                            # Current second's phases are different from previous second
                            phases_in_second != last_phases_in_second
                            # and we have passed at least one second with phases set
                            and last_non_intergreen != []
                            # and we are not currently in an intergreen (need to reach next phase to determine full intergreen period)
                            and phases_in_second != []
                            # or it is the last second
                        ) or i == len(cycle_seconds_phases) - 1:
                            if i == len(cycle_seconds_phases) - 1:
                                # If it is the last record, add the initial pre-phase intergreen time
                                intergreen += initial_intergreen if initial_intergreen is not None else 0
                                # If we finish on an intergreen, add an extra second as it hasn't yet been counted
                                intergreen += 1 if phases_in_second == [] else 0
                                # If we finish on a stage, add an extra second as it hasn't yet been counted
                                if phases_in_second != []:
                                    stage_duration += 1
                            # Append attributes to list of controllers SATURN type-3 record
                            if rec_3_list != [] and rec_3_list[-1][1] != 0:
                                # Test if previous stage had matching phases with non-zero intergreen (to mark previous intergreen negative)
                                if self._test_stages_negative_intergreen(rec_3_list[-1], last_non_intergreen):
                                    rec_3_list[-1][1] = 0 - rec_3_list[-1][1]
                                # Test if only a single stage (e.g zebra crossing), so mark current intergreen negative
                                if self._test_zebra_negative_intergreen(cycle_seconds_phases):
                                    intergreen = 0 - intergreen
                            rec_3_list.append([stage_duration, intergreen, last_non_intergreen])

                            # Reset stage duration and intergreen counters after identifying a new record
                            stage_duration = 0
                            intergreen = 0

                        # Keep track of the last second's phases
                        last_phases_in_second = phases_in_second

                        # Keep track of the last non-intergreen record and counters (we write this when the current record changes)
                        if phases_in_second != []:
                            last_non_intergreen = phases_in_second
                            # Stage duration counter can be increased
                            stage_duration += 1
                            if initial_intergreen is None:
                                # Store first intergreen to use on last phase
                                initial_intergreen = intergreen
                                intergreen = 0

                        if phases_in_second == []:
                            # Intergreen counter can be incremented
                            intergreen += 1

                    # Print SATURN header
                    rgs_file.write("* LoHAM P6 Signal. UTC:" + str(controller_number) + "\n")

                    # Process SATURN lines
                    saturn_rec1 = self._format_saturn_line(
                        [
                            node_b,
                            "",
                            3,
                            len(rec_3_list),
                            initial_intergreen if initial_intergreen is not None else 0,
                            cycle_time,
                        ],
                        self.SATURN_TYPE1_FIELD_LENS,
                    )

                    # Print SATURN type-1 record
                    rgs_file.write(saturn_rec1 + "\n")
                    # Print SATURN type-3 records
                    for stage in rec_3_list:
                        saturn_type3_field_lens = [5, 5, 5, 5, 5]
                        for n in range(0, len(stage[2]) * 2):
                            saturn_type3_field_lens.append(5)
                        rgs_file.write(
                            self._break_saturn_string(
                                self._format_saturn_line(
                                    ["", "", stage[0], stage[1], len(stage[2]) * 2]
                                    + [item for sublist in stage[2] for item in sublist],
                                    saturn_type3_field_lens,
                                ),
                                75,
                                25,
                            )
                            + "\n"
                        )
                    rgs_file.write("\n")

        self.signal_emulator.logger.info(f"SATURN {self.SATURN_TABLE_NAME} output to net file: {output_path}")

    # Test if a negative intergreen should be applied due to matching phases between stages and non-zero intergreen
    def _test_stages_negative_intergreen(self, prev_rec, nodes_list_b):
        nodes_list_a = prev_rec[2]
        # If previous intergreen was non-zero
        if prev_rec[1] != 0:
            # Test if there is a matching pair of nodes between last and current stage
            for pair in nodes_list_a:
                if pair in nodes_list_b:
                    return True

    # Test for single stage (eg Zebra crossing) where a negative intergreen should be applied
    def _test_zebra_negative_intergreen(self, cycle_seconds_phases):
        unique_lists = []
        for lst in cycle_seconds_phases:
            if lst and lst not in unique_lists:
                unique_lists.append(lst)

        distinct_stages = len(unique_lists)
        if distinct_stages == 1:
            return True
        else:
            return False

    # Break a sting to match SATURN max line length restrictions
    def _break_saturn_string(self, input_str, max_len, margin_len):
        lines = []
        current_line = ""
        for char in input_str:
            if len(current_line) >= max_len:
                lines.append(current_line)
                current_line = " " * margin_len
            current_line += char
        lines.append(current_line)
        return "\n".join(lines)

    # Append fields to SATURN string, right-aligned within field widths
    def _format_saturn_line(self, fields, field_len):
        formatted_saturn_line = ""
        for i in range(len(fields)):
            formatted_saturn_line += str(fields[i]).rjust(field_len[i])
        return formatted_saturn_line

    # Retrieve the VISUM calculated controller time period
    def _get_cycle_time(self, controller_number, time_period):
        for key, value in self.signal_emulator.visum_signal_controllers.data.items():
            if value.signal_controller_number == controller_number:  # and key[1] == time_period:
                if time_period == "AM":
                    return value.cycle_time_am
                elif time_period == "OP":
                    return value.cycle_time_op
                elif time_period == "PM":
                    return value.cycle_time_pm

    # Test if a a given phase name/controller/node-b exists in the SATURN node mapping
    def _test_in_database(self, controller_number, node_b, phase_name):
        saturn_in_phase = []
        for key in self.signal_emulator.phase_to_saturn_turns.data.keys():
            if int(key[0].replace("/", "")) == controller_number and key[2] == node_b and key[1] == phase_name:
                record = self.signal_emulator.phase_to_saturn_turns.data[key]
                saturn_in_phase.append([record.saturn_a_node, record.saturn_c_node])
        if saturn_in_phase == []:
            return None
        else:
            return saturn_in_phase

    # Get mapped distinct SATURN b-nodes for a given controller
    def _get_controller_saturn_nodes(self, controller_number):
        nodes = []
        for key in self.signal_emulator.phase_to_saturn_turns.data.keys():
            if int(key[0].replace("/", "")) == controller_number:
                record = self.signal_emulator.phase_to_saturn_turns.data[key]
                if record.saturn_b_node not in nodes:
                    nodes.append(record.saturn_b_node)
        return nodes

    # Identify what SATURN phases occur and exist for a given second of a controller/b-node time period
    def _get_phases_in_second(self, controller_number, node_b, time_period, t):
        phases_in_second = []
        for item in self:
            if (
                item.time_period_id == time_period.name
                and item.signal_controller_number == controller_number
                and (
                    (
                        item.green_time_start < item.green_time_end
                        and item.green_time_start <= t
                        and item.green_time_end > t
                    )
                    or (
                        item.green_time_start > item.green_time_end
                        and (item.green_time_start <= t or item.green_time_end > t)
                    )
                )
            ):
                is_in_database = self._test_in_database(controller_number, node_b, item.phase_name)
                if is_in_database is not None:
                    phases_in_second += is_in_database
        return phases_in_second

    # Resolve issues relating to the layout of phases within the stages cycle time
    def _post_process_cycle_seconds_phases(self, cycle_seconds_phases):
        # If a phase has a start_time > start_time, it will wrap around, resolve this
        while (
            cycle_seconds_phases[0] != []
            and cycle_seconds_phases[0] == cycle_seconds_phases[-1]
            and any(x != cycle_seconds_phases[0] for x in cycle_seconds_phases)
        ):
            element = cycle_seconds_phases.pop(0)
            cycle_seconds_phases.append(element)
        return cycle_seconds_phases


@dataclass(eq=False)
class SaturnSignalGroup(BaseItem):
    signal_controller_number: int
    phase_number: int
    phase_name: str
    green_time_start: int
    green_time_end: int
    time_period_id: str

    def get_key(self):
        return self.signal_controller_number, self.phase_name, self.time_period_id


class SaturnSignalGroups(SaturnCollection):
    ITEM_CLASS = SaturnSignalGroup
    TABLE_NAME = "saturn_signal_groups"
    WRITE_TO_DATABASE = False

    COLUMNS = {
        "SCNO": "signal_controller_number",
        "NO": "phase_number",
        "NAME": "phase_name",
        "GTSTART": "green_time_start",
        "GTEND": "green_time_end",
    }
    SATURN_TABLE_NAME = "SIGNALGROUP"

    def __init__(self, item_data, signal_emulator, output_directory):
        super().__init__(
            item_data=item_data,
            signal_emulator=signal_emulator,
            output_directory=output_directory,
        )
        self.signal_emulator = signal_emulator

    def add_from_phase_timing(self, phase_timing):
        saturn_signal_group = SaturnSignalGroup(
            signal_controller_number=phase_timing.controller.site_number_int,
            phase_number=phase_timing.signal_group_number,
            phase_name=phase_timing.visum_phase_name,
            green_time_start=phase_timing.start_time,
            green_time_end=phase_timing.end_time,
            time_period_id=phase_timing.time_period_id,
        )
        self.data[saturn_signal_group.get_key()] = saturn_signal_group
