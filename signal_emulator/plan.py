from __future__ import annotations

import os
import re
from copy import copy
from dataclasses import dataclass
from itertools import chain
from typing import List, TYPE_CHECKING

from signal_emulator.controller import BaseCollection
from signal_emulator.enums import PedBitsToStageNumber
from signal_emulator.utilities.utility_functions import txt_file_to_list, clean_site_number

if TYPE_CHECKING:
    from signal_emulator.emulator import SignalEmulator


@dataclass(eq=False)
class Plan:
    site_id: str
    plan_number: int
    name: str
    cycle_time: int
    timeout: int
    signal_emulator: SignalEmulator

    def __post_init__(self):
        self.plan_sequence_items = []
        if self.signal_emulator.streams.site_id_exists(self.site_id):
            stream = self.signal_emulator.streams.get_by_site_id(self.site_id)
            stream.plans.append(self)

    def __repr__(self):
        new_line = "\n"
        return (
            f"site id: {self.site_id} plan number: {self.plan_number} cycle time: {self.cycle_time}{new_line}"
            f"{new_line.join([str(p) for p in self.iter_plan_sequence_items()])}"
        )

    def iter_plan_sequence_items(self, single_double_triple=1):
        sorted_items = sorted(self.plan_sequence_items, key=lambda x: x.get_key())
        return iter(chain.from_iterable([sorted_items] * single_double_triple))

    def get_key(self):
        return self.site_id, self.plan_number

    def get_name_key(self):
        return self.site_id, self.name

    @staticmethod
    def constrain_time_to_cycle_time(time, cycle_time):
        return time % cycle_time

    def validate(self):
        return any(psi.has_f_bits() or psi.has_p_bits() for psi in self.iter_plan_sequence_items())

    def get_interstage_time(self, end_stage, start_stage, modified=True):
        end_phases = self.signal_emulator.stages.get_end_phases(end_stage, start_stage)
        start_phases = self.signal_emulator.stages.get_start_phases(end_stage, start_stage)
        max_interstage_time = 0
        for start_phase in start_phases:
            interstage_time = self.get_max_start_time(
                end_phases, start_phase, end_stage.stage_number, start_stage.stage_number, modified
            )
            max_interstage_time = max(max_interstage_time, interstage_time)
        return max_interstage_time

    def get_max_start_time(self, end_phases, start_phase, end_stage_key, start_stage_key, modified=True):
        time_delta = 0
        for end_phase in end_phases:
            end_phase_delay = self.signal_emulator.phase_delays.get_delay_time_by_stage_and_phase_keys(
                controller_key=end_phase.controller_key,
                end_stage_key=end_stage_key,
                start_stage_key=start_stage_key,
                phase_key=end_phase.phase_ref,
                modified=modified,
            )
            intergreen = self.signal_emulator.intergreens.get_intergreen_time_by_phase_keys(
                controller_key=end_phase.controller_key,
                end_phase_key=end_phase.phase_ref,
                start_phase_key=start_phase.phase_ref,
                modified=modified,
            )
            start_phase_delay = self.signal_emulator.phase_delays.get_delay_time_by_stage_and_phase_keys(
                controller_key=end_phase.controller_key,
                end_stage_key=end_stage_key,
                start_stage_key=start_stage_key,
                phase_key=start_phase.phase_ref,
                modified=modified,
            )
            time_delta = max(time_delta, max(end_phase_delay + intergreen, start_phase_delay))
        return time_delta

    def get_initial_stage_id(self, m37_stages, stream):
        m37_check = len(m37_stages) > 0
        initial_stage_id = None
        for plan_sequence_item in self.iter_plan_sequence_items():
            # self.plan_sequence_items.active_index = plan_sequence_item.index
            stage_id = self.process_plan_sequence_item_initial(plan_sequence_item, m37_check, stream)
            if stage_id:
                initial_stage_id = stage_id
        return stream.controller.controller_key, initial_stage_id

    def get_initial_stage_id_ped(self, m37_stages, stream):
        m37_check = len(m37_stages) > 0
        initial_stage_id = None
        for plan_sequence_item in sorted(self.plan_sequence_items, key=lambda x: len(x.p_bits)):
            # self.plan_sequence_items.active_index = plan_sequence_item.index
            stage_id = self.process_plan_sequence_item_initial(plan_sequence_item, m37_check, stream)
            if stage_id:
                initial_stage_id = stage_id
        return stream.controller.controller_key, initial_stage_id

    def process_plan_sequence_item_initial(self, plan_sequence_item, m37_check, stream):
        new_stage_key = None
        if not stream.active_stage_key:
            for stage in plan_sequence_item.stages_existing_in_stream(stream):
                if stage.m37_exists(self.site_id) or not m37_check:
                    new_stage_key = stage.stage_number
                    break
        else:
            if stream.active_stage.stream_stage_number in plan_sequence_item.stage_numbers:
                new_stage_key = stream.active_stage.stage_number
            else:
                for stage in plan_sequence_item.stages_existing_in_stream(stream):
                    if stage.m37_exists(self.site_id) or not m37_check:
                        new_stage_key = stage.stage_number
                        break
        if new_stage_key:
            stream.active_stage_key = stream.controller.controller_key, new_stage_key
        return new_stage_key

    def get_stage_sequence(
        self, m37_stages, stream, stream_cycle_time=None, cycle_time_factor=None, single_double_triple=None
    ):
        if stream.is_pv_px_mode:
            return self.get_stage_sequence_pv_px(
                m37_stages, stream, stream_cycle_time, cycle_time_factor, single_double_triple
            )
        elif stream.controller.is_pedestrian_controller:
            return self.get_stage_sequence_pedestrian(m37_stages, stream, stream_cycle_time, cycle_time_factor)
        else:
            return self.get_stage_sequence_junction(
                m37_stages, stream, stream_cycle_time, cycle_time_factor, single_double_triple
            )

    def get_stage_sequence_pedestrian(self, m37_stages, stream, stream_cycle_time=None, cycle_time_factor=None):
        stage_sequence = DefaultList(None)
        m37_check = len(m37_stages) > 1
        active_stage = self.signal_emulator.stages.get_by_stream_number_and_stage_number(
            stream.controller_key, stream.stream_number, 1
        )
        stream.active_stage_key = active_stage.controller_key, active_stage.stage_number
        plan_sequence_items = []
        for psi in self.iter_plan_sequence_items():
            if psi.f_bits == ["F2"]:
                plan_sequence_items.append(psi)
                break
        else:
            raise ValueError
        for psi in self.iter_plan_sequence_items():
            if psi.f_bits == ["F1"]:
                plan_sequence_items.append(psi)
                break
        else:
            raise ValueError

        for plan_sequence_item in plan_sequence_items:
            previous_stage_sequence_item = stage_sequence[-1]
            new_stage_sequence_item = self.process_plan_sequence_item_pedestrian(
                plan_sequence_item,
                previous_stage_sequence_item=previous_stage_sequence_item,
                m37_check=m37_check,
                stream=stream,
                stream_cycle_time=stream_cycle_time,
                cycle_time_factor=cycle_time_factor,
            )
            if new_stage_sequence_item:
                if (
                    previous_stage_sequence_item
                    and previous_stage_sequence_item.stage.stage_number != new_stage_sequence_item.stage.stage_number
                ) or not previous_stage_sequence_item:
                    stream.active_stage_key = (
                        stream.controller_key,
                        new_stage_sequence_item.stage.stage_number,
                    )
                    stage_sequence.append(new_stage_sequence_item)
        return stage_sequence

    def get_stage_sequence_pv_px(
        self, m37_stages, stream, stream_cycle_time=None, cycle_time_factor=None, single_double_triple=None
    ):
        stage_sequence = DefaultList(None)
        m37_check = len(m37_stages) > 0
        # set the initial stage number
        stream.active_stage_key = self.get_initial_stage_id_ped(m37_stages, stream)
        for plan_sequence_item in sorted(self.plan_sequence_items, key=lambda x: len(x.p_bits)):
            previous_stage_sequence_item = stage_sequence[-1]
            new_stage_sequence_item = self.process_plan_sequence_item_pvpx(
                plan_sequence_item,
                previous_stage_sequence_item=previous_stage_sequence_item,
                m37_check=m37_check,
                stream=stream,
                stream_cycle_time=stream_cycle_time,
                cycle_time_factor=cycle_time_factor,
                single_double_triple=single_double_triple,
            )
            if new_stage_sequence_item:
                if (
                    previous_stage_sequence_item
                    and previous_stage_sequence_item.stage.stage_number != new_stage_sequence_item.stage.stage_number
                ) or not previous_stage_sequence_item:
                    stream.active_stage_key = (
                        stream.controller_key,
                        new_stage_sequence_item.stage.stage_number,
                    )
                    stage_sequence.append(new_stage_sequence_item)

        # double cycling

        if single_double_triple == 2:
            final_stage_sequence = DefaultList(None)
            controller_cycle_time = int(stream_cycle_time * cycle_time_factor * single_double_triple)
            for stage in stage_sequence:
                final_stage_sequence.append(stage)
            for stage in stage_sequence:
                stage = copy(stage)
                stage.pulse_time = self.constrain_time_to_cycle_time(
                    stage.pulse_time + stream_cycle_time, controller_cycle_time
                )
                final_stage_sequence.append(stage)
        else:
            final_stage_sequence = stage_sequence
        return final_stage_sequence

    def get_stage_sequence_junction(
        self, m37_stages, stream, stream_cycle_time, cycle_time_factor, single_double_triple
    ):
        stage_sequence = DefaultList(None)
        stages_used = set()
        m37_check = len(m37_stages) > 0
        # set the initial stage number
        stream.active_stage_key = self.get_initial_stage_id(m37_stages, stream)
        for plan_sequence_item in self.iter_plan_sequence_items(single_double_triple=single_double_triple):
            # self.plan_sequence_items.active_index = plan_sequence_item.index
            previous_stage_sequence_item = stage_sequence[-1]
            new_stage_sequence_item = self.process_plan_sequence_item(
                plan_sequence_item,
                previous_stage_sequence_item=previous_stage_sequence_item,
                m37_check=m37_check,
                stream=stream,
                stream_cycle_time=stream_cycle_time,
                cycle_time_factor=cycle_time_factor,
                single_double_triple=single_double_triple,
            )
            if new_stage_sequence_item and (
                new_stage_sequence_item.stage.stage_number not in stages_used or single_double_triple > 1
            ):
                if (
                    previous_stage_sequence_item
                    and previous_stage_sequence_item.stage.stage_number != new_stage_sequence_item.stage.stage_number
                ) or not previous_stage_sequence_item:
                    stream.active_stage_key = (
                        stream.controller_key,
                        new_stage_sequence_item.stage.stage_number,
                    )
                    stage_sequence.append(new_stage_sequence_item)
                    stages_used.add(new_stage_sequence_item.stage.stage_number)

        if len(stage_sequence) == 0:
            # todo check this
            stage = self.signal_emulator.stages.get_by_key(self.get_initial_stage_id(m37_stages, stream))
            stage_sequence.append(
                StageSequenceItem(
                    stage=stage,
                    pulse_time=0,
                )
            )

        if m37_check and not m37_stages == set([a.stage.stream_stage_number for a in stage_sequence]):
            self.signal_emulator.logger.warning(
                f"Stream: {stream.site_number} "
                f"Time Period: {self.signal_emulator.time_periods.active_period_id} "
                f"Plan stage sequence: {[a.stage.stream_stage_number for a in stage_sequence]} "
                f"does not match m37 stages: {m37_stages}"
            )
        elif m37_check and m37_stages == set([a.stage.stream_stage_number for a in stage_sequence]):
            self.signal_emulator.logger.info(
                f"Plan stage sequence: "
                f"{[a.stage.stream_stage_number for a in stage_sequence]} matches m37 stages: {m37_stages}"
            )
        if len(stage_sequence) > 1 and stage_sequence[0].stage.stage_number == stage_sequence[-1].stage.stage_number:
            stage_sequence = stage_sequence[:-1]

        self.validate_stage_sequence(stage_sequence, stream.controller)
        # stage_sequence = self.remove_repeated_dd_stages(stage_sequence)
        return stage_sequence

    def validate_stage_sequence(self, stage_sequence, controller):
        for current_ssi, next_ssi in zip(stage_sequence, stage_sequence[1:] + [stage_sequence[0]]):
            if len(stage_sequence) > 1:
                if current_ssi.stage.stage_number == next_ssi.stage.stage_number:
                    self.signal_emulator.logger.warning(
                        f"Plan: {self.site_id} {self.plan_number} has an invalid stage sequence, "
                        f"repeated stage {current_ssi.stage.stage_number}"
                    )
                elif self.signal_emulator.prohibited_stage_moves.is_prohibited_by_stage_keys(
                    controller.controller_key,
                    current_ssi.stage.stage_number,
                    next_ssi.stage.stage_number,
                ):
                    self.signal_emulator.logger.warning(
                        f"Plan: {self.site_id} {self.plan_number} has an invalid stage sequence, "
                        f"prohibited stage move {current_ssi.stage.stage_number} -> {next_ssi.stage.stage_number}"
                    )

    def process_plan_sequence_item_pvpx(
        self,
        plan_sequence_item,
        stream,
        previous_stage_sequence_item=None,
        m37_check=False,
        stream_cycle_time=None,
        cycle_time_factor=None,
        single_double_triple=None,
    ):
        if stream_cycle_time is None:
            stream_cycle_time = self.cycle_time
        if stream.active_stage_key[1] is None:
            # should not get here now
            raise ValueError(
                f"Stream: {stream.controller_key} active stage id should be set before calling this function"
            )
        controller_cycle_time = int(stream_cycle_time * cycle_time_factor * single_double_triple)
        new_stage = stream.active_stage
        if stream.active_stage.stream_stage_number in plan_sequence_item.stage_numbers:
            new_stage = stream.active_stage
        else:
            for stage in plan_sequence_item.stages_existing_in_stream(stream):  # pass stream
                if stage.m37_exists(self.site_id) or not m37_check:
                    new_stage = stage
                    break
        if new_stage.stage_number == stream.active_stage_key[1]:
            return None

        if not previous_stage_sequence_item:
            pulse_time = plan_sequence_item.pulse_time
            road_green_stage = self.signal_emulator.stages.get_by_stream_number_and_stage_number(
                stream.controller_key, stream.stream_number, 1
            )
            not_road_green_stage = self.signal_emulator.stages.get_by_stream_number_and_stage_number(
                stream.controller_key, stream.stream_number, 2
            )
            not_road_green_phase = not_road_green_stage.phases_in_stage[0]
            ped_green_man_time = not_road_green_phase.min_time
            ig_ped = self.get_interstage_time(road_green_stage, not_road_green_stage, modified=False)
            ig_traffic = self.get_interstage_time(not_road_green_stage, road_green_stage, modified=False)
            if not_road_green_stage.m37_exists(self.site_id):
                m37_not_road_green_time = not_road_green_stage.get_m37(self.site_id).total_time
                effective_stage_call_rate = m37_not_road_green_time / (ig_ped + ig_traffic + ped_green_man_time)
            else:
                effective_stage_call_rate = self.get_default_ped_call_rate()
        else:
            road_green_stage = self.signal_emulator.stages.get_by_stream_number_and_stage_number(
                stream.controller_key, stream.stream_number, 1
            )
            not_road_green_stage = self.signal_emulator.stages.get_by_stream_number_and_stage_number(
                stream.controller_key, stream.stream_number, 2
            )
            not_road_green_phase = not_road_green_stage.phases_in_stage[0]
            ped_green_man_time = not_road_green_phase.min_time
            ig_ped = self.get_interstage_time(road_green_stage, not_road_green_stage, modified=False)
            ig_traffic = self.get_interstage_time(not_road_green_stage, road_green_stage, modified=False)
            if not_road_green_stage.m37_exists(self.site_id):
                m37_not_road_green_time = not_road_green_stage.get_m37(self.site_id).total_time
                effective_stage_call_rate = 1
            else:
                m37_not_road_green_time = ig_ped + ig_traffic + ped_green_man_time
                effective_stage_call_rate = self.get_default_ped_call_rate()
            adjustment_factor = ig_traffic / (ped_green_man_time + ig_ped + ig_traffic)
            adjustment_seconds = int(adjustment_factor * m37_not_road_green_time)
            stage_length = round(
                (m37_not_road_green_time - adjustment_seconds) * effective_stage_call_rate * cycle_time_factor
            )
            if new_stage.stream_stage_number == 1 or single_double_triple > 1:
                pulse_time = previous_stage_sequence_item.pulse_time + stage_length
            else:
                raise Exception("should not get here")
        pulse_time = self.constrain_time_to_cycle_time(pulse_time, controller_cycle_time)
        return StageSequenceItem(
            stage=new_stage, pulse_time=pulse_time, effective_stage_call_rate=effective_stage_call_rate
        )

    def process_plan_sequence_item_pedestrian(
        self,
        plan_sequence_item,
        stream,
        previous_stage_sequence_item=None,
        m37_check=False,
        stream_cycle_time=None,
        cycle_time_factor=None,
    ):
        if stream_cycle_time is None:
            stream_cycle_time = self.cycle_time
        if stream.active_stage_key[1] is None:
            # should not get here now
            raise ValueError(
                f"Stream: {stream.controller_key} active stage id should be set before calling this function"
            )
        # cycle_time_factor = controller_cycle_time / stream_cycle_time
        new_stage = stream.active_stage
        if stream.active_stage.stream_stage_number in plan_sequence_item.stage_numbers:
            new_stage = stream.active_stage
        else:
            for stage in plan_sequence_item.stages_existing_in_stream(stream):  # pass stream
                if stage.m37_exists(self.site_id) or not m37_check:
                    new_stage = stage
                    break
        if new_stage.stage_number == stream.active_stage_key[1]:
            return None

        if not previous_stage_sequence_item:
            pulse_time = plan_sequence_item.pulse_time
            road_green_stage = self.signal_emulator.stages.get_by_stream_number_and_stage_number(
                stream.controller_key, stream.stream_number, 1
            )
            not_road_green_stage = self.signal_emulator.stages.get_by_stream_number_and_stage_number(
                stream.controller_key, stream.stream_number, 2
            )
            not_road_green_phase = not_road_green_stage.phases_in_stage[0]
            ped_green_man_time = not_road_green_phase.min_time
            ig_ped = self.get_interstage_time(road_green_stage, not_road_green_stage, modified=False)
            if not_road_green_stage.m37_exists(self.site_id):
                m37_not_road_green_time = not_road_green_stage.get_m37(self.site_id).total_time
                effective_stage_call_rate = m37_not_road_green_time / (ig_ped + ped_green_man_time)
            else:
                effective_stage_call_rate = self.get_default_ped_call_rate()
        else:
            road_green_stage = self.signal_emulator.stages.get_by_stream_number_and_stage_number(
                stream.controller_key, stream.stream_number, 1
            )
            not_road_green_stage = self.signal_emulator.stages.get_by_stream_number_and_stage_number(
                stream.controller_key, stream.stream_number, 2
            )
            not_road_green_phase = not_road_green_stage.phases_in_stage[0]
            ped_green_man_time = not_road_green_phase.min_time
            ig_ped = self.get_interstage_time(road_green_stage, not_road_green_stage, modified=False)
            if not_road_green_stage.m37_exists(self.site_id):
                m37_not_road_green_time = not_road_green_stage.get_m37(self.site_id).total_time
                effective_stage_call_rate = 1
            else:
                m37_not_road_green_time = ig_ped + ped_green_man_time
                effective_stage_call_rate = self.get_default_ped_call_rate()
            stage_length = round(m37_not_road_green_time * effective_stage_call_rate * cycle_time_factor)
            if new_stage.stream_stage_number == 1:
                pulse_time = previous_stage_sequence_item.pulse_time + stage_length
            else:
                raise Exception("should not get here")
        pulse_time = self.constrain_time_to_cycle_time(pulse_time, stream_cycle_time)
        return StageSequenceItem(
            stage=new_stage, pulse_time=pulse_time, effective_stage_call_rate=effective_stage_call_rate
        )

    def process_plan_sequence_item(
        self,
        plan_sequence_item,
        stream,
        previous_stage_sequence_item=None,
        m37_check=False,
        stream_cycle_time=None,
        cycle_time_factor=None,
        single_double_triple=None,
    ):
        if stream_cycle_time is None:
            stream_cycle_time = self.cycle_time
        if stream.active_stage_key[1] is None:
            # should not get here now
            raise ValueError(
                f"Stream: {stream.controller_key} active stage id should be set before calling this function"
            )
        stream_cycle_time_adjusted = int(round(stream_cycle_time * cycle_time_factor, 0))
        controller_cycle_time = stream_cycle_time_adjusted * single_double_triple

        new_stage = stream.active_stage
        if stream.active_stage.stream_stage_number in plan_sequence_item.stage_numbers:
            new_stage = stream.active_stage
        else:
            for stage in plan_sequence_item.stages_existing_in_stream(stream):  # pass stream
                if stage.m37_exists(self.site_id) or not m37_check:
                    new_stage = stage
                    break

        if new_stage.stage_number == stream.active_stage_key[1]:
            return None
        if m37_check and previous_stage_sequence_item:
            pulse_time = previous_stage_sequence_item.pulse_time + round(
                previous_stage_sequence_item.stage.get_m37(self.site_id).total_time * cycle_time_factor
            )
        elif not previous_stage_sequence_item:
            pulse_time = plan_sequence_item.pulse_time
        else:
            if plan_sequence_item.pulse_time > previous_stage_sequence_item.pulse_time:
                green_time = plan_sequence_item.pulse_time - previous_stage_sequence_item.pulse_time
            else:
                green_time = (
                    plan_sequence_item.pulse_time
                    + plan_sequence_item.plan.cycle_time
                    - previous_stage_sequence_item.pulse_time
                )
            pulse_time = previous_stage_sequence_item.pulse_time + green_time
        if not plan_sequence_item.f_bits and not plan_sequence_item.p_bits:
            pulse_time += 2
        elif plan_sequence_item.p_bits == ["PV"]:
            pass
            # pulse_time += 3 # stream.active_stage.

        if stream.is_pv_px_mode and previous_stage_sequence_item:
            ped_stage_trailing_intergreen_time = self.signal_emulator.intergreens.get_intergreen_time_by_phase_keys(
                controller_key=stream.controller.controller_key, end_phase_key="B", start_phase_key="A", modified=True
            )
            if new_stage.stage_number == 1:
                pulse_time -= ped_stage_trailing_intergreen_time
            else:
                pulse_time += ped_stage_trailing_intergreen_time
        pulse_time = self.constrain_time_to_cycle_time(pulse_time, controller_cycle_time)
        return StageSequenceItem(stage=new_stage, pulse_time=pulse_time)

    @staticmethod
    def get_stage_length_from_pulse_times(previous_pulse_time, this_pulse_time, cycle_time):
        if this_pulse_time > previous_pulse_time:
            return this_pulse_time - previous_pulse_time
        else:
            return this_pulse_time + cycle_time - previous_pulse_time

    def remove_repeated_dd_stages(self, stage_sequence):
        stage_nos = set()
        output_stage_sequence = DefaultList(None)
        for stage_sequence_item in stage_sequence:
            if stage_sequence_item.stage.stage_number not in stage_nos:
                output_stage_sequence.append(stage_sequence_item)
            else:
                self.signal_emulator.logger.info(
                    f"controller: {stage_sequence_item.stage.controller_key} "
                    f"has repeated stage: {stage_sequence_item} removed"
                )
            stage_nos.add(stage_sequence_item.stage.stage_number)
        return output_stage_sequence

    def get_default_ped_call_rate(self):
        return self.signal_emulator.plans.DEFAULT_PED_STAGE_CALL_RATE.get(
            self.signal_emulator.time_periods.active_period_id, 1.0
        )


class Plans(BaseCollection):
    TABLE_NAME = "plans"
    ITEM_CLASS = Plan
    WRITE_TO_DATABASE = True
    DEFAULT_PED_STAGE_CALL_RATE = {"AM": 0.5, "OP": 0.5, "PM": 0.5}

    def __init__(self, plans_list, signal_emulator=None):
        super().__init__(item_data=plans_list, signal_emulator=signal_emulator)
        self.signal_emulator = signal_emulator
        self.data_by_name = {}
        for plan in self:
            self.data_by_name[plan.get_name_key()] = plan
        self.active_plan_id = None

    @property
    def active_plan_id(self):
        return self._active_plan_id

    @active_plan_id.setter
    def active_plan_id(self, value):
        self._active_plan_id = value

    @property
    def active_plan(self):
        return self.data[self._active_plan_id]

    @classmethod
    def init_from_pln_path(cls, plan_file_path, signal_emulator=None):
        input_plans_list = txt_file_to_list(plan_file_path)
        if len(input_plans_list) == 1:
            return cls([], signal_emulator)
        output_plans_list = []
        plan_data = []
        plan_dict = {}
        site_id = cls.get_site_id_from_pln_path(plan_file_path)
        for row in input_plans_list:
            if cls.is_header_row(row):
                row_split = row.split(" ")
                if "/" in row_split[2]:
                    plan_number = int(row_split[2].split("/")[0])
                else:
                    plan_number = int(row_split[2])
                cycle_time = int(row_split[4].split("/")[0])
                if len(row_split) < 6:
                    timeout = 0
                else:
                    timeout = int(row_split[6])
                plan_data = []
                plan_dict = {
                    "site_id": site_id,
                    "plan_number": plan_number,
                    "cycle_time": cycle_time,
                    "timeout": timeout,
                }
            elif row == "":
                continue
            elif row.startswith("%"):
                plan_dict["name"] = row.replace("% ", "")
            elif not row.startswith((";", "#", "*")):
                plan_data.append(row)
            if row.startswith("*"):
                plan_dict["plan_data"] = plan_data
                if "name" not in plan_dict:
                    plan_dict["name"] = "NONE"
                output_plans_list.append(plan_dict)
        return cls(output_plans_list, signal_emulator)

    def add_from_pln(self, plan_file_path):
        plan_data_list = self.pln_to_list(plan_file_path)
        for plan_data in plan_data_list:
            plan = Plan(signal_emulator=self.signal_emulator, **plan_data)
            self.data[plan.get_key()] = plan

    def pln_to_list(self, plan_file_path):
        input_plans_list = txt_file_to_list(plan_file_path)
        output_plans_list = []
        plan_data = []
        plan_dict = {}
        site_id = self.get_site_id_from_pln_path(plan_file_path)
        for row in input_plans_list:
            if self.is_header_row(row):
                row_split = row.split(" ")
                if "/" in row_split[2]:
                    plan_number = int(row_split[2].split("/")[0])
                else:
                    plan_number = int(row_split[2])
                cycle_time = int(row_split[4].split("/")[0])
                if len(row_split) < 6:
                    timeout = 0
                else:
                    timeout = int(row_split[6])
                plan_data = []
                plan_dict = {
                    "site_id": clean_site_number(site_id),
                    "plan_number": plan_number,
                    "cycle_time": cycle_time,
                    "timeout": timeout,
                }
            elif row == "":
                continue
            elif row.startswith("%"):
                plan_dict["name"] = row.replace("% ", "")
            elif not row.startswith((";", "#", "*")):
                plan_data.append(row)
            if row.startswith("*"):
                plan_dict["plan_data"] = plan_data
                output_plans_list.append(plan_dict)
        return output_plans_list

    @staticmethod
    def get_site_id_from_pln_path(plan_file_path):
        directory, filename = os.path.split(plan_file_path)
        return f"J{filename[1:3]}/{filename[3:6]}"

    @staticmethod
    def is_header_row(row):
        row_upper = row.upper()
        return "PLAN" in row_upper and "CYCLE" in row_upper and row_upper[0] not in {"#", "%"}

    def add_plan(self, site_name, plan_number, name, cycle_time, timeout, data):
        self.data[plan_number] = Plan(site_name, plan_number, name, cycle_time, timeout, data)

    def get_by_name(self, name):
        return self.data_by_name.get(name, None)

    def exists_by_name(self, name):
        return name in self.data_by_name


@dataclass(eq=False)
class PlanSequenceItem:
    PED_BITS_TO_STAGE_NUMBERS = {
        "PV": 1,
        "PX": 2,
    }

    site_id: str
    plan_number: int
    index: int
    pulse_time: int
    f_bits: List
    d_bits: List
    p_bits: List
    nto: bool
    scoot_stage: str
    signal_emulator: SignalEmulator

    def __post_init__(self):
        self.plan.plan_sequence_items.append(self)
        if "PV" in self.p_bits and self.signal_emulator.streams.site_id_exists(self.site_id):
            stream = self.signal_emulator.streams.get_by_site_id(self.site_id)
            stream.is_pv_px_mode = True

    def get_key(self):
        return self.site_id, self.plan_number, self.index

    def get_plan_key(self):
        return self.site_id, self.plan_number

    @property
    def plan(self):
        return self.signal_emulator.plans.get_by_key(self.get_plan_key())

    @staticmethod
    def get_commands_from_str(plan_sequence_str):
        delimiter_pattern = r"[.,]"  # Using a regex pattern to match .,
        commands = re.split(delimiter_pattern, plan_sequence_str)
        final_commands = []
        for command in commands:
            command = command.upper()
            if len(command) >= 4:
                for i in range(0, len(command), 2):
                    assert command[i] in {"F", "D"}
                    final_commands.append(command[i : i + 2])
            else:
                final_commands.append(command)
        f_bits, d_bits, p_bits, nto = [], [], [], False
        for command in final_commands:
            if len(command) == 0:
                continue
            elif command[0] == "F":
                f_bits.append(command)
            elif command[0] == "D":
                d_bits.append(command)
            elif command[0] == "P":
                p_bits.append(command)
            elif command == "NTO":
                nto = True
        return f_bits, d_bits, p_bits, nto

    def has_f_bits(self):
        return bool(self.f_bits)

    def has_p_bits(self):
        return bool(self.p_bits)

    def __repr__(self):
        return f"PlanSequenceItem: {self.index=} {self.pulse_time=} {self.f_bits=} {self.d_bits=} {self.p_bits=}"

    @property
    def stage_numbers(self):
        return (
            [int(f[1]) for f in self.f_bits if f[1].isnumeric()]
            + [PedBitsToStageNumber[p].value for p in self.p_bits if p in PedBitsToStageNumber.__members__]
            + ([2] if not self.f_bits and not self.p_bits else [])
        )

    @property
    def stream(self):
        return self.signal_emulator.streams.get_by_site_id(self.site_id)

    @property
    def stages(self):
        # return [self.signal_emulator.stages.get_by_key(stage) for stage in self.stage_numbers]
        return [
            self.signal_emulator.stages.get_by_stream_number_and_stage_number(
                self.stream.controller_key, self.stream.stream_number, stage_number
            )
            for stage_number in self.stage_numbers
            if self.signal_emulator.stages.key_exists_by_stream_number_and_stage_number(
                self.stream.controller_key, self.stream.stream_number, stage_number
            )
        ]

    # def stages_existing_in_stream(self, stream_number):
    #     return [
    #         self.signal_emulator.stages.get_by_stream_number_and_stage_number(
    #             stream_number, stage_number
    #         )
    #         for stage_number in self.stage_numbers
    #         if self.signal_emulator.stages.key_exists_by_stream_number_and_stage_number(
    #             stream_number, stage_number
    #         )
    #     ]

    def stages_existing_in_stream(self, stream):
        existing_stages = [
            stage
            for stage in self.stages
            if self.signal_emulator.stages.key_exists_by_stream_number_and_stage_number(
                stream.controller_key, stream.stream_number, stage.stream_stage_number
            )
        ]
        existing_sorted = sorted(existing_stages, key=lambda x: x.stage_number)
        if stream.active_stage:
            low = [a for a in existing_sorted if a.stage_number < stream.active_stage.stage_number]
            high = [a for a in existing_sorted if a.stage_number > stream.active_stage.stage_number]
            existing_stages_cyclic = high + low
        else:
            existing_stages_cyclic = existing_stages
        return existing_stages_cyclic


class PlanSequenceItems(BaseCollection):
    TABLE_NAME = "plan_sequence_items"
    ITEM_CLASS = PlanSequenceItem
    WRITE_TO_DATABASE = True

    def __init__(self, item_data, signal_emulator):
        super().__init__(item_data=item_data, signal_emulator=signal_emulator)
        self.active_index = 0

    def __iter__(self):
        return iter(self.data.values())

    def get_active_item(self):
        return self.data[self.active_index]

    def get_next_item(self):
        if self.active_index == len(self.data) - 1:
            next_index = 0
        else:
            next_index = self.active_index + 1
        return self.data[next_index]

    def get_previous_item(self):
        if self.active_index == 0:
            previous_index = len(self.data) - 1
        else:
            previous_index = self.active_index - 1
        return self.data[previous_index]


class StageSequenceItems:
    def __init__(self, controller):
        self.items = []
        self.controller = controller

    def __iter__(self):
        return iter(self.items)

    def add_item(self, stage, pulse_time):
        self.items.append(StageSequenceItem(stage=stage, pulse_time=pulse_time))

    def iter_pairwise(self):
        """
        Iterator to yield each sequence pair in StageSequenceItems
        :return: pair of StageSequenceItem
        """
        for ssi1, ssi2 in zip(self.items, self.items[1:] + self.items[0]):
            yield ssi1, ssi2


class StageSequenceItem:
    def __init__(self, stage, pulse_time, effective_stage_call_rate=1):
        self.stage = stage
        self.pulse_time = pulse_time
        self.effective_stage_call_rate = effective_stage_call_rate

    def __repr__(self):
        return f"StageSequenceItem: {self.stage.stage_number=} {self.pulse_time=}"


class DefaultList(list):
    def __init__(self, default_value):
        super().__init__()
        self.default_value = default_value

    def __getitem__(self, index):
        if isinstance(index, slice):
            # Handle slicing
            start, stop, step = index.start, index.stop, index.step
            start = self._handle_negative_index(start)
            stop = self._handle_negative_index(stop)
            return self._get_sliced_list(start, stop, step)
        elif isinstance(index, int):
            # Handle single-item indexing
            index = self._handle_negative_index(index)
            if 0 <= index < len(self):
                return super().__getitem__(index)
        return self.default_value

    def _handle_negative_index(self, index):
        if index is None:
            return None
        if index < 0:
            index += len(self)
        return index

    def _get_sliced_list(self, start, stop, step):
        return super().__getitem__(slice(start, stop, step))

    def iter_pairwise(self):
        """
        Iterator to yield pairs of values from the sequence
        :return: pair of List items
        """
        for ssi1, ssi2 in zip(self, self[1:] + [self[0]]):
            yield ssi1, ssi2

    def iter_previous_current_next(self):
        """
        Iterator to yield previous current and next values from the sequence
        :return: previous current and next values
        """
        for previous_ssi, this_ssi, next_ssi in zip([self[-1]] + self[:-1], self, self[1:] + [self[0]]):
            yield previous_ssi, this_ssi, next_ssi


if __name__ == "__main__":
    plan_file = Plans.init_from_pln_path("resources/plans/j01039.pln")
