import logging
import os
from datetime import datetime

from signal_emulator.controller import (
    Controllers,
    Streams,
    Stages,
    Phases,
    Intergreens,
    PhaseDelays,
    ProhibitedStageMoves,
    BaseCollection,
    PhaseTimings,
    ModifiedIntergreens,
    ModifiedPhaseDelays,
    PhaseStageDemandDependencies
)
from signal_emulator.enums import Cell
from signal_emulator.file_parsers.plan_parser import PlanParser
from signal_emulator.file_parsers.timing_sheet_parser import TimingSheetParser
from signal_emulator.linsig import Linsig
from signal_emulator.m16_average import M16Averages
from signal_emulator.m37_average import M37Averages
from signal_emulator.plan import Plans, PlanSequenceItems
from signal_emulator.plan_timetable import PlanTimetables
from signal_emulator.saturn_objects import PhaseToSaturnTurns, SaturnSignalGroups
from signal_emulator.signal_plan import SignalPlans, SignalPlanStreams, SignalPlanStages
from signal_emulator.time_period import TimePeriods
from signal_emulator.utilities.postgres_connection import PostgresConnection
from signal_emulator.utilities.utility_functions import load_json_to_dict
from signal_emulator.visum_objects import VisumSignalGroups, VisumSignalControllers
from signal_emulator.coordinate_transformer import CoordinateTransformer


class SignalEmulator:
    BASE_DIRECTORY = os.path.dirname(__file__)
    DEFAULT_TIME_PERIODS_PATH = os.path.join(BASE_DIRECTORY, "resources/time_periods/default_time_periods.json")

    def __init__(self, config):
        self.logger = self.setup_logger()
        self.logger.info(f"Starting run of signal_emulator.py")
        if "postgres_connection" in config:
            self.postgres_connection = PostgresConnection(**config["postgres_connection"])
            self.load_from_postgres = config["load_from_postgres"]
        else:
            self.postgres_connection = None
            self.load_from_postgres = False
        self.timing_sheet_parser = TimingSheetParser(self)
        self.osgb36_to_wgs84 = CoordinateTransformer(source_epsg_code=27700, target_epsg_code=4326)
        self.plan_parser = PlanParser()
        self.time_periods = TimePeriods(
            config.get(
                "time_periods",
                load_json_to_dict(self.DEFAULT_TIME_PERIODS_PATH),
            ),
            self,
        )
        self.controllers = Controllers([], self)
        self.streams = Streams([], self)
        self.stages = Stages([], self)
        self.phases = Phases([], self)
        self.phase_stage_demand_dependencies = PhaseStageDemandDependencies([], self)
        self.phases.set_indicative_arrow_phases(self.phases)
        self.intergreens = Intergreens([], self)
        self.modified_intergreens = ModifiedIntergreens([], self)
        self.phase_delays = PhaseDelays([], self)
        self.modified_phase_delays = ModifiedPhaseDelays([], self)
        self.prohibited_stage_moves = ProhibitedStageMoves([], self)
        if config.get("timing_sheet_directory"):
            self.load_timing_sheets_from_directory(
                timing_sheet_directory=config["timing_sheet_directory"],
                borough_codes=config.get("borough_codes")
            )
        self.plans = Plans([], self)
        self.plan_sequence_items = PlanSequenceItems([], self)
        if config.get("plan_directory"):
            self.load_plans_from_cell_directories(config["plan_directory"])
        self.plan_timetables = PlanTimetables(
            signal_emulator=self, pja_directory_path=config.get("PJA_directory", None)
        )
        self.m16s = M16Averages(
            periods=self.time_periods,
            **config.get("M16", {"source_type": None, "m16_path": None}),
            signal_emulator=self,
        )
        self.m37s = M37Averages(
            periods=self.time_periods,
            **config.get("M37", {"source_type": None, "m37_path": None}),
            signal_emulator=self,
        )
        self.signal_plans = SignalPlans([], self)
        self.signal_plan_streams = SignalPlanStreams([], self)
        self.signal_plan_stages = SignalPlanStages([], self)
        self.phase_timings = PhaseTimings([], self)
        self.saturn_signal_groups = SaturnSignalGroups(
            [], self, config.get("output_directory_saturn", None)
        )
        self.visum_signal_groups = VisumSignalGroups(
            [], self, config.get("output_directory_visum", None)
        )
        self.visum_signal_controllers = VisumSignalControllers(
            [],
            self,
            config.get("output_directory_visum", None),
            config.get("sld_pdf_directory"),
            config.get("timing_sheet_pdf_directory")
        )
        self.plan_timetables = PlanTimetables(
            signal_emulator=self, pja_directory_path=config.get("PJA_directory", None)
        )
        self.phase_to_saturn_turns = PhaseToSaturnTurns(
            signal_emulator=self, saturn_lookup_file=config.get("saturn_lookup_file", None)
        )
        self.linsig = Linsig(self, config.get("output_directory_linsig", None))
        self.run_datestamp = f'signal emulator run {datetime.now().strftime("%Y-%m-%d")}'

    @staticmethod
    def setup_logger():
        if not os.path.exists("log"):
            os.makedirs("log")
        logging.basicConfig(
            filename=f"log/{datetime.now().strftime('%Y_%m_%d_%H_%M_%S')}_signal_emulator.log",
            level=logging.INFO,
            format="[%(asctime)s] {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        # set up logging to console
        console = logging.StreamHandler()
        console.setLevel(logging.DEBUG)
        # set a format which is simpler for console use
        formatter = logging.Formatter("%(name)-12s: %(levelname)-8s %(message)s")
        console.setFormatter(formatter)
        # add the handler to the root logger
        logging.getLogger("").addHandler(console)
        return logging.getLogger(__name__)

    def generate_signal_plans(self, ped_only=False):
        """
        Method to generate signal plans from UTC plans and controller spec definitions
        :return: None
        """
        for controller in self.controllers:
            self.logger.info(f"Processing Signal Plans for Controller: {controller.controller_key}")
            if controller.is_parallel():
                self.logger.info(
                    f"Site: {controller.controller_key} is Parallel Stage Stream Site, so it is defined in another Site"
                )
                continue
            for signal_plan_number, time_period in enumerate(self.time_periods, start=1):
                self.time_periods.active_period_id = time_period.get_key()
                stream_plan_dict = self.get_stream_plan_dict(controller)
                if any(stream_plan_dict.values()):
                    if not ped_only or any([s.is_pv_px_mode for s in stream_plan_dict.keys()]):
                        self.signal_plans.add_from_stream_plan_dict(
                            stream_plan_dict, time_period, signal_plan_number
                        )
                else:
                    self.logger.warning(
                        f"Controller: {controller.controller_key} was not processed to signal plans because suitable"
                        f" plans were not found for any stream"
                    )

    def get_stream_plan_dict(self, controller):
        stream_plan_dict = {}
        for stream in controller.streams:
            plan = self.get_best_matching_plan(stream)
            stream_plan_dict[stream] = plan
        return stream_plan_dict

    def get_best_matching_plan(self, stream):
        """
        Function to get the best matching plan for a stream
        :param stream: Stream
        :return: Plan
        """
        pja = self.plan_timetables.get_by_key(
            (stream.site_number, self.time_periods.active_period_id)
        )
        # If Plan exists that is referenced in pJA file then return this Plan
        if pja and pja.control_plan:
            self.logger.info(
                f"Plan: {pja.control_plan.plan_number} {pja.control_plan.name} {pja.control_plan.site_id} selected from PJA file"
            )
            return pja.control_plan
        # Else return best matching plan base on plan name, WAT AM for example
        elif self.get_plan_for_active_period(stream):
            plan = self.get_plan_for_active_period(stream)
            self.logger.info(
                f"Plan: {plan.plan_number} {plan.name} selected by searching for WAT plan for time period: "
                f"{self.time_periods.active_period_id}"
            )
            return plan
        # Else return the first available plan
        non_mins_plans = [p for p in stream.plans if "MINS" not in p.name.upper()]
        if non_mins_plans:
            plan = non_mins_plans[0]
            self.logger.info(
                f"Plan: {plan.plan_number} {plan.name} selected the first available plan"
            )
            return plan
        else:
            return None

    def get_plan_for_active_period(self, stream):
        for plan in stream.plans:
            if plan.name in {
                f"WAT {self.time_periods.active_period_id}",
                f"{self.time_periods.active_period_id}",
            }:
                return plan
        for plan in stream.plans:
            if "WAT" in plan.name and (
                self.time_periods.active_period.name in plan.name or
                self.time_periods.active_period.long_name in plan.name
            ):
                return plan
        for plan in stream.plans:
            if (
                self.time_periods.active_period.name in plan.name or
                self.time_periods.active_period.long_name in plan.name
            ):
                return plan
        return None

    def get_plan_path(self, plan_filename):
        for cell in Cell:
            if os.path.exists(os.path.join("resources", "plans", cell.name, plan_filename)):
                return os.path.join("resources", "plans", cell.name, plan_filename)
        else:
            self.logger.warning(f"plan: {plan_filename} does not exist")
            return None

    def load_timing_sheets_from_directory(self, timing_sheet_directory, borough_codes=None):
        for csv_filepath in self.timing_sheet_parser.timing_sheet_file_iterator(
            timing_sheet_directory, borough_codes
        ):
            self.load_timing_sheet_csv(csv_filepath)

    def load_timing_sheet_csv(self, csv_filepath):
        attrs_dict = self.timing_sheet_parser.parse_timing_sheet_csv(csv_filepath)
        self.controllers.add_items(attrs_dict["controllers"], self)
        self.streams.add_items(attrs_dict["streams"], self)
        self.stages.add_items(attrs_dict["stages"], self)
        self.phases.add_items(attrs_dict["phases"], self)
        self.intergreens.add_items(attrs_dict["intergreens"], self)
        self.phase_delays.add_items(attrs_dict.get("phase_delays", []), self)
        self.phase_delays.remove_invalid()
        self.prohibited_stage_moves.add_items(attrs_dict.get("prohibited_stage_moves", []), self)
        self.phase_stage_demand_dependencies.add_items(attrs_dict.get("phase_stage_demand_dependencies", []), self)
        controller = self.controllers.get_by_key(attrs_dict["controllers"][0]["controller_key"])
        self.phases.set_indicative_arrow_phases(controller.phases)

    def load_plans_from_cell_directories(self, base_directory):
        for cell in Cell:
            cell_directory = os.path.join(base_directory, cell.name)
            if os.path.exists(cell_directory):
                self.load_plans_from_directory(os.path.join(base_directory, cell.name))
            else:
                self.logger.warning(f"Plan directory for cell {cell.name} does not exist")

    def load_plans_from_directory(self, plan_directory):
        for plan_filepath in self.plan_parser.plan_file_iterator(plan_directory):
            self.load_plan_from_pln(plan_filepath)

    def load_plan_from_pln(self, plan_filepath):
        attrs_dict = self.plan_parser.pln_to_attr_dict(plan_filepath)
        self.plans.add_items(attrs_dict["plans"], self)
        self.plan_sequence_items.add_items(attrs_dict["plan_sequence_items"], self)

    def base_collection_iterator(self):
        """
        Yield the BaseCollection subclasses
        :return: BaseCollection class instance
        """
        for attr_name in self.__dict__.keys():
            attr = getattr(self, attr_name)
            if issubclass(attr.__class__, BaseCollection):
                yield attr

    def export_to_database(self, schema=None):
        if not schema:
            schema = self.postgres_connection.schema
            self.postgres_connection.schema = schema
        self.logger.info(f"Exporting signal data to postgres: {self.postgres_connection}")
        self.postgres_connection.create_schema(schema)
        for collection in self.base_collection_iterator():
            if collection.WRITE_TO_DATABASE:
                collection.write_to_database(schema)

    def generate_phase_timings(self, remove_existing=True):
        if remove_existing:
            self.phase_timings.remove_all()
        for signal_plan in self.signal_plans:
            signal_plan.emulate()

    def generate_visum_signal_groups(self):
        """
        Method to generate VISUM format signal groups from Phase Timings
        :return:
        """
        for phase_timing in self.phase_timings:
            if not self.visum_signal_groups.key_exists((phase_timing.controller_key, phase_timing.signal_group_number)):
                self.visum_signal_groups.add_from_phase_timing(phase_timing)
            visum_signal_group = self.visum_signal_groups.get_by_key(
                (phase_timing.controller_key, phase_timing.signal_group_number)
            )
            if phase_timing.time_period_id == "AM":
                visum_signal_group.green_time_start_am = phase_timing.start_time
                visum_signal_group.green_time_end_am = phase_timing.end_time
            elif phase_timing.time_period_id == "OP":
                visum_signal_group.green_time_start_op = phase_timing.start_time
                visum_signal_group.green_time_end_op = phase_timing.end_time
            elif phase_timing.time_period_id == "PM":
                visum_signal_group.green_time_start_pm = phase_timing.start_time
                visum_signal_group.green_time_end_pm = phase_timing.end_time

    def generate_saturn_signal_groups(self):
        """
        Method to generate SATURN format signal groups from Phase Timings
        :return:
        """
        for phase_timing in self.phase_timings:
            self.saturn_signal_groups.add_from_phase_timing(phase_timing)

if __name__ == "__main__":
    signal_emulator_config = load_json_to_dict(
        json_file_path="signal_emulator/resources/configs/signal_emulator_from_pg_config.json"

    )
    signal_emulator = SignalEmulator(config=signal_emulator_config)
    if not signal_emulator_config["load_from_postgres"]:
        signal_emulator.load_timing_sheets_from_directory("signal_emulator/resources/timing_sheets")
        signal_emulator.load_plans_from_cell_directories("signal_emulator/resources/plans")

    signal_emulator.generate_signal_plans()
    signal_emulator.generate_phase_timings()
    signal_emulator.generate_visum_signal_groups()
    signal_emulator.generate_saturn_signal_groups()
    signal_emulator.export_to_database()
    # signal_emulator.visum_signal_controllers.export_to_net_files()
    # signal_emulator.visum_signal_groups.export_to_net_files()
    # signal_emulator.linsig.export_all_to_lsg_v236()
    # signal_emulator.emulate_one(timing_sheet_filename="00_000002_Junc.csv")
    # d = signal_emulator.controller.phases.to_dataframe()
