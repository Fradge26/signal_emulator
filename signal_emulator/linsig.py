import os
import random
from pathlib import Path

from signal_emulator.utilities.utility_functions import list_to_txt


class Linsig:
    HEADERS = {
        "SCHEM": "SCHEM2.15",
        "SVERS": "SVERS2, 3, 6, 0",
        "USRHD": "USRHDTCU1U78637TCU1U78638    1",
    }
    PROBABLY_ZERO = "0"
    LAST_STREAM_NUMBER = "0"

    def __init__(self, signal_emulator, output_directory):
        self.signal_emulator = signal_emulator
        self.output_directory = output_directory

    def export_all_to_lsg_v236(self):
        Path(self.output_directory).mkdir(exist_ok=True, parents=True)

        for controller in self.signal_emulator.controllers:
            for signal_plan in controller.signal_plans:
                self.signal_emulator.logger.info(
                    f"Exporting Signal Plan: {controller.controller_key} {signal_plan.time_period_id} to Linsig file"
                )
                self.export_to_lsg_v236(signal_plan)

    def export_to_lsg_v236(self, signal_plan):
        self.signal_emulator.time_periods.active_period_id = signal_plan.time_period_id
        output_data = ["SCHEM2.15", "SVERS2, 3, 6, 0", "USRHDTCU1U78637TCU1U78638    1"]
        output_data.extend(["TEXT "] * 3)
        output_data.extend([f"TEXT {' - '.join([stream.site_id for stream in signal_plan.signal_plan_streams])}"])
        output_data.extend(["TEXT "] * 3)
        output_data.extend(
            [
                "THEAD    1",
                "TEXT ",
                "LENV     2    1    0    0",
                "PREFS0000100030001000003000050000600000000100000000000000010",
                "PFONT150,0,0,0,400,0,0,0,0,0,0,2,18,Arial,0",
                "PFONT150,0,0,0,400,0,0,0,0,0,0,2,18,Arial,0",
                "PFONT240,0,0,0,400,0,0,0,0,0,0,2,18,Arial,0",
                "PFONT240,0,0,0,400,0,0,0,0,0,0,2,18,Arial,0",
                "LNETW    0    0    0    0   -1   -1   -1   -1   -1   -1   -1   -1",
                "JUNC     0    0    1    2  100    1    0    0    0    0    2    0         0         0         0      "
                "   0    1   -1    0         0         0         0         0",
            ]
        )
        output_data.append(self.get_controller_line(signal_plan))
        for phase in sorted(signal_plan.controller.phases, key=lambda x: x.phase_number):
            output_data.append(self.get_phase_line_1(phase))
            output_data.append(self.get_phase_line_2(phase))

        for stream in signal_plan.controller.streams:
            output_data.append(self.get_stream_line(stream))
            for stage in stream.stages_in_stream_linsig:
                output_data.append(self.get_stage_line(stage))
            output_data.append("ISTLA    0")

        for intergreen in signal_plan.controller.intergreens:
            if intergreen.modified_intergreen_time > 0:
                output_data.append(self.get_intergreen_line(intergreen))

        for phase_delay in signal_plan.controller.phase_delays:
            if (
                phase_delay.modified_delay_time > 0
                and phase_delay.start_stage_key > 0
                and phase_delay.end_stage_key > 0
            ):
                output_data.append(self.get_phase_delay_line(phase_delay))

        output_data.append(self.get_signal_plan_line(signal_plan))
        output_data.append(self.get_signal_plan_name_line())
        for stream_plan in signal_plan.signal_plan_streams:
            output_data.append(self.get_stream_plan_line_1(stream_plan))
            output_data.append("PDTMN   90    0    1")
        output_data.append(self.get_streams_num_line_1(signal_plan))
        for stream_plan in signal_plan.signal_plan_streams:
            output_data.append(self.get_stream_plan_line_2(stream_plan))

        output_data.append(
            f"FLWGP{'1'.rjust(5)}{'0'.rjust(5)}"
            f"{self.signal_emulator.signal_plans.get_first().time_period.start_time_str[:-3]}"
            f"{self.signal_emulator.signal_plans.get_first().time_period.end_time_str[:-3]}"
            f"{'Flow Group 1    0    0'.rjust(90)}"
        )
        output_data.append("FLGPF    1    0")
        output_data.append("FGRFS    0")

        # scenarios
        # changed this to only handle one time period scenario
        output_data.append(f"TIMPD{'1'.rjust(5)}" f"{'1'.rjust(5)}" f"{'1'.rjust(5)}" f"{'1'.rjust(5)}¬")
        output_data.append("REPDS    0    5    0")
        output_data.append("SELEC    0")
        output_data.append("PPGES    2")
        output_data.append("VWPPS    1    0")
        output_data.append("VWPPS    2    0")
        output_data.append("VWPOS   29    0    0  840  400    0    1    0    0    0    0   -1    0    1")
        output_data.append("VWPOS   12    0    0  840  400    0    1    0    0    0    0   -1    0    1")

        temp_str_1, temp_str_2 = "", ""
        temp_count_1, temp_count_2 = 0, 0
        for phase in signal_plan.controller.phases:
            if phase.phase_number < len(signal_plan.controller.phases) / 2:
                temp_str_1 += str(phase.phase_number).rjust(5)
                temp_count_1 += 1
            else:
                temp_str_2 += str(phase.phase_number).rjust(5)
                temp_count_2 += 1
        output_data.append(f"CRTPH{str(temp_count_1).rjust(5)}{temp_str_1}")
        output_data.append(f"CRTPH{str(temp_count_2).rjust(5)}{temp_str_2}")
        output_data.append("FITGR27650    0    0")
        list_to_txt(output_data, self.get_linsig_filepath(signal_plan))

    @staticmethod
    def get_linsig_filename(signal_plan):
        return f"{signal_plan.controller.site_number_filename}_{signal_plan.time_period_id}.lsg"

    def get_linsig_filepath(self, signal_plan):
        return os.path.join(self.output_directory, f"{self.get_linsig_filename(signal_plan)}")

    @staticmethod
    def get_streams_num_line_1(signal_plan):
        return f"SSLES{str(len(signal_plan.signal_plan_streams)).rjust(5)}"

    @staticmethod
    def get_stream_plan_line_2(stream_plan):
        return (
            f"STSLE{str(stream_plan.stream_number).rjust(5)}"
            f"{str(stream_plan.stream_number).rjust(5)}"
            f"{'1'.rjust(5)}"
            f"{'1'.rjust(5)}"
        )

    def get_stream_plan_line_1(self, stream_plan):
        return (
            f"STSEQ{'1'.rjust(5)}"
            f"{str(stream_plan.stream_number).rjust(5)}"
            f"{str(stream_plan.first_stage_time).rjust(5)}"
            f"{str(stream_plan.cycle_time).rjust(5)}"
            f"{str(len(stream_plan.signal_plan_stages)).rjust(5)}"
            f"{''.join([self.get_signal_plan_stage_line(sps) for sps in stream_plan.signal_plan_stages])}"
            f"{str(stream_plan.PROBABLY_ZERO).rjust(5)}"
            f"{str(stream_plan.single_double_triple).rjust(5)}"
            f"{str(len(stream_plan.signal_plan_stages)).rjust(5)}"
        )

    @staticmethod
    def get_signal_plan_stage_line(signal_plan_stage):
        return f"{str(signal_plan_stage.stage_number).rjust(5)}" f"{str(signal_plan_stage.green_length).rjust(5)}"

    @staticmethod
    def get_signal_plan_line(signal_plan):
        return (
            f"SGPLN{'1'.rjust(5)}"
            f"{str(len(signal_plan.signal_plan_streams)).rjust(5)}"
            f"{str(signal_plan.PROBABLY_ZERO).rjust(5)}"
            f"{str(signal_plan.PROBABLY_ZERO).rjust(5)}"
            f"{str(signal_plan.cycle_time).rjust(5)}"
        )

    @staticmethod
    def get_signal_plan_name_line():
        # signal plan number always 1, as we only include 1 signal plan per file
        return f"SGPLD{'1'.rjust(50)}"

    def get_phase_delay_line(self, phase_delay):
        return (
            f"PDELY{str(phase_delay.end_stage.stream_number_linsig).rjust(5)}"
            f"{str(phase_delay.end_stage.stage_number).rjust(5)}"
            f"{str(phase_delay.start_stage.stage_number).rjust(5)}"
            f"{str(phase_delay.phase.phase_number).rjust(5)}"
            f"{str(phase_delay.modified_delay_time).rjust(5)}"
            f"{self.get_losing_phase_delay_string(phase_delay.phase_delay_type, phase_delay.is_absolute)}"
        )

    @staticmethod
    def get_losing_phase_delay_string(phase_delay_type, is_absolute):
        return f"    {'1' if phase_delay_type == 'losing' or is_absolute else '0'}3548{random.randint(1000, 9999)}"

    @staticmethod
    def get_intergreen_line(intergreen):
        return (
            f"INGRN{str(intergreen.end_phase.phase_number).rjust(5)}"
            f"{str(intergreen.start_phase.phase_number).rjust(5)}{str(intergreen.modified_intergreen_time).rjust(5)}"
        )

    @staticmethod
    def get_stage_line(stage):
        return (
            f"STAGE{str(stage.stage_number).rjust(5)}"
            f"{str(len(stage.phase_keys_in_stage)).rjust(5)}"
            f"{''.join([str(phase.phase_number).rjust(5) for phase in stage.phases_in_stage])}"
        )

    def get_stream_line(self, stream):
        return (
            f"SSTRM{str(stream.stream_number_linsig).rjust(5)}"
            f"{str(stream.num_stages_in_stream_linsig).rjust(5)}"
            f"{self.PROBABLY_ZERO.rjust(5)}"
            f"{str(stream.num_phases_in_stream_linsig).rjust(5)}"
            f"{''.join([str(phase.phase_number).rjust(5) for phase in stream.phases_in_stream])}"
            f"{self.LAST_STREAM_NUMBER.rjust(5)}"
        )

    @staticmethod
    def get_controller_line(signal_plan):
        phase_delay_count = len(
            [
                p
                for p in signal_plan.controller.phase_delays
                if p.delay_time > 0 and p.start_stage_key > 0 and p.end_stage_key > 0
            ]
        )
        return (
            f"CNTLR    0{str(len(signal_plan.controller.phases)).rjust(5)}"
            f"{str(len(signal_plan.signal_plan_streams)).rjust(5)}"
            f"{str(len(signal_plan.controller.intergreens)).rjust(5)}"
            f"{str(phase_delay_count).rjust(5)}"
            f"    1    1    1    1   -1   -1    1    0"
        )

    @staticmethod
    def get_phase_line_1(phase):
        return (
            f"PHASE{str(phase.phase_number).rjust(5)}"
            f"{str(phase.linsig_phase_type.value).rjust(5)}"
            f"{str(phase.min_time).rjust(5)}"
            f"{str(phase.associated_phase_number).rjust(5)}"
            f"{str(phase.text).rjust(80)}"
            f"{str(phase.termination_type).rjust(5)}"
        )

    def get_phase_line_2(self, phase):
        a, b, c, d = self.phase_number_to_vector(phase.phase_number)
        return f"VECT  LONG{a.rjust(10)}{b.rjust(10)}{c.rjust(10)}{d.rjust(10)}"

    @staticmethod
    def phase_number_to_vector(phase_number):
        q, m = divmod(phase_number - 1, 10)
        return list(map(str, [m * 100, q * 200, (m + 1) * 100, q * 200 + 100]))
