from __future__ import annotations

import csv
import os
from collections import defaultdict
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional, List, Union, TYPE_CHECKING

import pandas as pd
import sqlalchemy

from signal_emulator.enums import PhaseType, PhaseTermType, PhaseTypeAndTermTypeToLinsigPhaseType
from signal_emulator.utilities.utility_functions import load_json_to_dict

if TYPE_CHECKING:
    from signal_emulator.emulator import SignalEmulator


class BaseCollection:
    WRITE_TO_DATABASE = False
    TABLE_NAME = None
    ITEM_CLASS = None
    DATACLASS_TO_SQL_TYPE_MAP = {
        List: sqlalchemy.ARRAY(sqlalchemy.types.String),
        List[str]: sqlalchemy.ARRAY(sqlalchemy.types.String),
    }

    def __init__(self, item_data=None, signal_emulator=None):
        if signal_emulator is not None:
            self.signal_emulator = signal_emulator
        if (
            signal_emulator
            and self.signal_emulator.postgres_connection
            and self.TABLE_NAME
            and self.signal_emulator.load_from_postgres
        ):
            self.signal_emulator.logger.info(f"Collection: {self.TABLE_NAME} data read from postgres")
            item_data = self.signal_emulator.postgres_connection.read_table_to_df(self.TABLE_NAME, to_dict=True)
        self.data = {}
        for item_row in item_data:
            if signal_emulator:
                item = self.ITEM_CLASS(**item_row, signal_emulator=signal_emulator)
            else:
                item = self.ITEM_CLASS(**item_row, signal_emulator=None)
            self.data[item.get_key()] = item

    def __iter__(self):
        return iter(self.data.values())

    def __len__(self):
        return len(self.data)

    def add_items(self, item_arg_list, signal_emulator=None, valid_only=False):
        for arg_list in item_arg_list:
            self.add_item(arg_list, signal_emulator=signal_emulator, valid_only=valid_only)

    def add_item(self, data, signal_emulator=None, valid_only=False):
        item = self.ITEM_CLASS(signal_emulator=signal_emulator, **data)
        if valid_only and item.is_valid:
            self.data[item.get_key()] = item
        elif not valid_only:
            self.data[item.get_key()] = item

    def add_instance(self, item):
        if isinstance(item, self.ITEM_CLASS):
            self.data[item.get_key()] = item
        else:
            self.signal_emulator.logger(
                f"Item: {item} cannot be added to Collection: {self.__class__.__name__} as it is not the correct type"
            )

    @property
    def num_items(self):
        return len(self.data)

    def get_by_key(self, key):
        return self.data.get(key)

    def get_first(self):
        if len(self.data) > 0:
            return list(self.data.values())[0]
        else:
            return None

    def get_last(self):
        if len(self.data) > 0:
            return list(self.data.values())[-1]
        else:
            return

    def get_all(self):
        return [a for a in self]

    def remove_by_key(self, key):
        if key in self.data:
            del self.data[key]

    def key_exists(self, key):
        return key in self.data

    def remove_all(self):
        self.data = {}

    def to_dataframe(self):
        all_fields = fields(self.ITEM_CLASS)
        item_data = []
        for item in self:
            item_data.append(
                {
                    field.name: getattr(item, field.name)
                    for field in all_fields
                    if field.type not in {object, Optional[object]}
                }
            )
        df = pd.DataFrame(item_data)
        return df

    def write_to_csv(self, output_path):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df = self.to_dataframe()
        df.to_csv(output_path, index=False)

    def write_to_database(self, schema=None):
        df = self.to_dataframe()
        dtypes = self.get_dtypes_from_fields()
        self.signal_emulator.postgres_connection.write_df_to_table(df, self.TABLE_NAME, schema, dtypes=dtypes)
        self.signal_emulator.logger.info(f"Collection: {self.TABLE_NAME} written to postgres")

    def get_dtypes_from_fields(self):
        all_fields = fields(self.ITEM_CLASS)
        dtypes = {
            f.name: self.DATACLASS_TO_SQL_TYPE_MAP[f.type]
            for f in all_fields
            if f.type in self.DATACLASS_TO_SQL_TYPE_MAP
        }
        return dtypes


class BaseItem:
    def __init__(self, signal_emulator=None):
        if signal_emulator:
            self.signal_emulator = signal_emulator

    def __repr__(self):
        return f"{self.__class__.__name__}: {self.get_key()}"

    def get_key(self):
        return NotImplementedError


@dataclass(eq=False)
class Controller(BaseItem):
    controller_key: str
    controller_type: str
    x_coord: int
    y_coord: int
    address: str
    spec_issue_no: str
    is_pedestrian_controller: bool
    signal_emulator: "SignalEmulator"

    TIMING_SHEET_COLUMN_LOOKUP_PATH = os.path.join(
        os.path.dirname(__file__), "resources/configs/timing_sheet_column_config.json"
    )

    def __post_init__(self):
        self.stream_keys = []
        self.intergreen_keys = []
        self.phase_delay_keys = []
        self.signal_plans = []
        self.phase_to_saturn_turns = []

    def get_key(self):
        return self.controller_key

    @property
    def borough_number(self):
        return int(self.controller_key[:2])

    @property
    def streams(self):
        return [self.signal_emulator.streams.get_by_key((self.controller_key, key)) for key in self.stream_keys]

    @property
    def stages(self):
        return [stage for stream in self.streams for stage in stream.stages_in_stream]

    @property
    def phases(self):
        return [phase for stream in self.streams for phase in stream.phases_in_stream]

    @property
    def intergreens(self):
        return [
            self.signal_emulator.intergreens.get_by_phase_keys(self.controller_key, end_phase_key, start_phase_key)
            for end_phase_key, start_phase_key in self.intergreen_keys
        ]

    @property
    def phase_delays(self):
        return [
            self.signal_emulator.phase_delays.get_by_key(
                (self.controller_key, end_stage_key, start_stage_key, phase_key)
            )
            for end_stage_key, start_stage_key, phase_key in self.phase_delay_keys
        ]

    @property
    def coord(self):
        return [self.x_coord, self.y_coord]

    @property
    def site_number_int(self):
        parts = self.controller_key.split("/")
        if parts[0][0].isalpha():
            parts[0] = parts[0][1:]
        return int(parts[0]) * 1000 + int(parts[1])

    @property
    def site_number_filename(self):
        return self.controller_key.replace("/", "_")

    @property
    def site_number_long(self):
        site_number_parts = self.controller_key.split("/")
        return f"{site_number_parts[0]}/000{site_number_parts[1]}"

    @property
    def pdf_filename(self):
        site_number_parts = self.controller_key.replace("J", "").split("/")
        return f"{site_number_parts[0]}_000{site_number_parts[1]}.pdf"

    @property
    def plan_filename(self):
        site_number_parts = self.controller_key.split("/")
        return f"j{site_number_parts[0][1:]}{site_number_parts[1][-3:]}.pln"

    @classmethod
    def timing_sheet_csv_to_dict(cls, timing_sheet_csv_path):
        column_dict = load_json_to_dict(cls.TIMING_SHEET_COLUMN_LOOKUP_PATH)
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
                data_dict[section] = cls.data_to_dict(section_data, column_dict[section])
            else:
                num_cols = len(column_dict[section])
                if num_cols < len(row):
                    if section == "Stages":
                        row[1] = " ".join(row[1:])
                    elif section == "Streams":
                        row[2] = " ".join(row[2:-2])
                        row[3] = row[-2]
                        row[4] = row[-1]
                if len(row) < num_cols:
                    row.extend([""] * (num_cols - len(row)))
                section_data.append(row[:num_cols])
        return data_dict

    @staticmethod
    def data_to_dict(data, column_dict):
        output_dict = []
        for d in data:
            output_dict.append({v: d[int(k) - 1] for k, v in column_dict.items() if v != "unused"})
        return output_dict

    def is_parallel(self):
        return self.controller_type == "Parallel Stage Stream Site"

    def validate(self):
        return len(self.stages) > 0 and len(self.phases) > 0 and self.controller_type != "Parallel Stage Stream Site"

    @property
    def visum_controller_name(self):
        return f"{self.site_number_int} - {self.address}"

    @property
    def latitude(self):
        return self.signal_emulator.osgb36_to_wgs84.transform(self.x_coord, self.y_coord)[1]

    @property
    def longitude(self):
        return self.signal_emulator.osgb36_to_wgs84.transform(self.x_coord, self.y_coord)[0]


class Controllers(BaseCollection):
    ITEM_CLASS = Controller
    TABLE_NAME = "controllers"
    WRITE_TO_DATABASE = True

    def __init__(self, item_data, signal_emulator):
        super().__init__(item_data=item_data, signal_emulator=signal_emulator)


@dataclass(eq=False)
class Stage(BaseItem):
    controller_key: str
    stage_number: int
    stage_name: str
    stream_number: int
    stream_stage_number: int
    phase_keys_in_stage: List[str]
    signal_emulator: "SignalEmulator"

    def __post_init__(self):
        self.phase_stage_demand_dependencies = []
        self.stream.stage_keys_in_stream.append(self.stage_number)
        self.stream.stage_keys_in_stream = sorted(self.stream.stage_keys_in_stream)

    def __repr__(self):
        return f"Stage: {self.stream_number=} {self.stage_number=} {self.stream_stage_number=} {self.stage_name=}"

    @property
    def stream(self):
        return self.signal_emulator.streams.get_by_key(self.get_stream_key())

    @property
    def controller(self):
        return self.signal_emulator.controllers.get_by_key(self.controller_key)

    def get_key(self):
        return self.controller_key, self.stage_number

    def get_stream_key(self):
        return self.controller_key, self.stream_number

    def get_number_key(self):
        return self.controller_key, self.stream_number, self.stream_stage_number

    def get_name_key(self):
        return self.controller_key, self.stage_name

    @property
    def m37_stage_id(self):
        return f"G{self.stream_stage_number}"

    @property
    def m37_stage_id_ped(self):
        if self.stream_stage_number == 1:
            return "GX"
        elif self.stream_stage_number == 2:
            return "PG"
        else:
            return None

    @property
    def phases_in_stage(self):
        return [self.signal_emulator.phases.get_by_key((self.controller_key, key)) for key in self.phase_keys_in_stage]

    @property
    def stream_number_linsig(self):
        return self.stream_number + 1

    def get_m37(self, site_id):
        m37 = self.signal_emulator.m37s.get_by_key(
            (
                site_id,
                self.stream_stage_number,
                self.signal_emulator.time_periods.active_period_id,
            )
        )
        if not m37:
            m37 = self.signal_emulator.m37s.get_by_key(
                (
                    site_id,
                    self.stream_stage_number,
                    self.signal_emulator.time_periods.active_period_id,
                )
            )
        return m37

    def m37_exists(self, site_id):
        # todo fix for parallel streams
        # ped streams has Pxx/xxx site_number format
        m37 = self.signal_emulator.m37s.get_by_key(
            (
                site_id,
                self.stream_stage_number,
                self.signal_emulator.time_periods.active_period_id,
            )
        )
        if not m37:
            m37 = self.signal_emulator.m37s.get_by_key(
                (
                    site_id,
                    self.m37_stage_id_ped,
                    self.signal_emulator.time_periods.active_period_id,
                )
            )
        return m37 and m37.total_time > 0


class Stages(BaseCollection):
    ITEM_CLASS = Stage
    TABLE_NAME = "stages"
    WRITE_TO_DATABASE = True

    def __init__(self, item_data, signal_emulator):
        super().__init__(item_data=item_data, signal_emulator=signal_emulator)
        self.data_by_stage_name = {}
        self.data_by_stream_number_and_stage_number = {}
        for stage in self:
            self.data_by_stage_name[stage.get_name_key()] = stage
            self.data_by_stream_number_and_stage_number[stage.get_number_key()] = stage
        self.active_stage_id = None

    def key_exists_by_stage_name(self, stage_name):
        return stage_name in self.data_by_stage_name

    def key_exists_by_stream_number_and_stage_number(self, controller_key, stream_number, stage_number):
        return (
            controller_key,
            stream_number,
            stage_number,
        ) in self.data_by_stream_number_and_stage_number

    def get_by_stage_name(self, stage_name):
        return self.data_by_stage_name[stage_name]

    def get_by_stream_number_and_stage_number(self, controller_key, stream_number, stage_number):
        return self.data_by_stream_number_and_stage_number[(controller_key, stream_number, stage_number)]

    def add_item(self, data, signal_emulator=None, valid_only=False):
        stage = self.ITEM_CLASS(signal_emulator=signal_emulator, **data)
        self.data[stage.get_key()] = stage
        self.data_by_stream_number_and_stage_number[stage.get_number_key()] = stage
        self.data_by_stage_name[stage.get_name_key()] = stage

    def get_stream_stage_number(self, this_stage):
        count = 0
        for stage in self:
            if stage.stream_number == this_stage.stream_number:
                if stage.stage_name == this_stage.stage_name:
                    break
                count += 1
        return count

    def hacky_get_stage(self, stage_name):
        for stage in self:
            if stage.stage_name == stage_name and stage.stream_number is None:
                return stage

        for stage in self:
            if stage.stage_name == stage_name:
                return stage
        else:
            raise ValueError

    @property
    def active_stage_id(self):
        return self._active_stage_id

    @active_stage_id.setter
    def active_stage_id(self, value):
        self._active_stage_id = value

    @property
    def active_stage(self):
        return self.data[self._active_stage_id]

    @staticmethod
    def get_end_phases(current_stage, next_stage):
        return list(set(current_stage.phases_in_stage) - set(next_stage.phases_in_stage))

    @staticmethod
    def get_start_phases(current_stage, next_stage):
        return list(set(next_stage.phases_in_stage) - set(current_stage.phases_in_stage))


@dataclass(eq=False)
class Phase(BaseItem):
    controller_key: str
    phase_ref: str
    min_time: int
    phase_type_str: str
    appearance_type_int: int
    termination_type_int: int
    text: str
    associated_phase_ref: str
    signal_emulator: "SignalEmulator"

    def __post_init__(self):
        self.indicative_arrow_phase = None

    def __repr__(self):
        return f"Phase: {self.phase_ref}"

    @property
    def phase_type(self):
        return PhaseType[self.phase_type_str]

    def get_key(self):
        return self.controller_key, self.phase_ref

    @property
    def associated_phase(self):
        return self.signal_emulator.phases.get_by_key((self.controller_key, self.associated_phase_ref))

    @property
    def associated_phase_number(self):
        return self.associated_phase.phase_number if self.associated_phase else 0

    @property
    def phase_number(self):
        if len(self.phase_ref) == 1:
            return ord(self.phase_ref) - 64
        else:
            # handle two character phase refs
            return (ord(self.phase_ref[0]) - 64) * 26 + ord(self.phase_ref[1]) - 64

    @property
    def termination_type(self):
        return PhaseTermType(self.termination_type_int)

    @property
    def linsig_phase_type(self):
        return PhaseTypeAndTermTypeToLinsigPhaseType[(self.phase_type, self.termination_type)]

    @property
    def phase_timings(self):
        return self.signal_emulator.phase_timings.get_by_controller_key_phase_ref_time_period_id(
            *self.get_phase_timing_key()
        )

    def get_phase_timing_key(self):
        return (
            self.controller_key,
            self.phase_ref,
            self.signal_emulator.time_periods.active_period_id,
        )

    def get_phase_timings_by_time_period_id(self, time_period_id):
        return self.signal_emulator.phase_timings.get_by_controller_key_phase_ref_time_period_id(
            self.controller_key, self.phase_ref, time_period_id
        )


class Phases(BaseCollection):
    ITEM_CLASS = Phase
    TABLE_NAME = "phases"
    WRITE_TO_DATABASE = True

    def __init__(self, item_data, signal_emulator):
        super().__init__(item_data=item_data, signal_emulator=signal_emulator)

    @staticmethod
    def set_indicative_arrow_phases(phases):
        for phase in phases:
            if phase.associated_phase and phase.termination_type_int == 2:
                phase.associated_phase.indicative_arrow_phase = phase


@dataclass(eq=False)
class Stream(BaseItem):
    controller_key: str
    stream_number: int
    site_number: str
    signal_emulator: SignalEmulator
    stage_keys_in_stream: Optional[List[int]] = None
    is_pv_px_mode: bool = False

    def __init__(
        self,
        controller_key,
        stream_number,
        site_number,
        signal_emulator,
        stage_keys_in_stream=None,
        is_pv_px_mode=False,
    ):
        super().__init__(signal_emulator=signal_emulator)
        if stage_keys_in_stream is None:
            stage_keys_in_stream = []
        self.controller_key = controller_key
        self.stream_number = stream_number
        self.site_number = site_number
        self.stage_keys_in_stream = stage_keys_in_stream
        self.is_pv_px_mode = is_pv_px_mode
        self._active_stage_key = None
        self.__post_init__()

    def __post_init__(self):
        self.plans = []
        self.stage_keys_in_stream = []
        self.controller.stream_keys.append(self.stream_number)

    def __repr__(self):
        return f"Stream: {self.stream_number=} {self.site_number=}"

    def get_key(self):
        return self.controller_key, self.stream_number

    def get_site_key(self):
        return self.site_number

    @property
    def active_stage_key(self):
        return self._active_stage_key

    @active_stage_key.setter
    def active_stage_key(self, value):
        if not self.signal_emulator.stages.key_exists(value) and value[1] is not None:
            raise ValueError(f"Active stage key: {value} does not exist in Stages")
        self._active_stage_key = value

    @property
    def controller(self):
        return self.signal_emulator.controllers.get_by_key(self.controller_key)

    @property
    def active_stage(self):
        return self.signal_emulator.stages.get_by_key(self.active_stage_key)

    @property
    def stream_number_linsig(self):
        """
        Linsig streams are 1 based, so we must add 1
        :return: 1-based stream number, int
        """
        return self.stream_number + 1

    @property
    def plan_filename(self):
        parts = self.site_number.split("/")
        return f"j{parts[0][1:]}{parts[1][-3:]}.pln"

    @property
    def stages_in_stream(self):
        return [self.signal_emulator.stages.get_by_key((self.controller_key, key)) for key in self.stage_keys_in_stream]

    @property
    def stages_in_stream_linsig(self):
        return [
            self.signal_emulator.stages.get_by_key((self.controller_key, key))
            for key in self.stage_keys_in_stream
            if key > 0
        ]

    @property
    def phase_keys_in_stream(self):
        return list({phase_key for stage in self.stages_in_stream for phase_key in stage.phase_keys_in_stage})

    @property
    def phase_keys_in_stream_linsig(self):
        return list({phase_key for stage in self.stages_in_stream_linsig for phase_key in stage.phase_keys_in_stage})

    @property
    def phases_in_stream(self):
        return [self.signal_emulator.phases.get_by_key((self.controller_key, key)) for key in self.phase_keys_in_stream]

    @property
    def num_phases_in_stream_linsig(self):
        return len(self.phase_keys_in_stream)

    @property
    def num_stages_in_stream_linsig(self):
        return len([a for a in self.stage_keys_in_stream if a > 0])


class Streams(BaseCollection):
    ITEM_CLASS = Stream
    TABLE_NAME = "streams"
    WRITE_TO_DATABASE = True

    def __init__(self, item_data, signal_emulator):
        super().__init__(item_data=item_data, signal_emulator=signal_emulator)
        self.data_by_site_id = {}
        for stream in self:
            self.data_by_site_id[stream.get_site_key()] = stream

    def add_item(self, stream_data, **kwargs):
        stream = Stream(**stream_data, signal_emulator=kwargs.get("signal_emulator"))
        self.data[stream.get_key()] = stream
        self.data_by_site_id[stream.get_site_key()] = stream

    def get_by_site_id(self, site_number, strict=True):
        if strict:
            return self.data_by_site_id[site_number]
        else:
            return self.data.get(site_number, None)

    def site_id_exists(self, site_number):
        return site_number in self.data_by_site_id


@dataclass(eq=False)
class BaseIntergreen(BaseItem):
    controller_key: str
    end_phase_key: str
    start_phase_key: str
    intergreen_time: int
    signal_emulator: "SignalEmulator"

    def get_key(self):
        return self.controller_key, self.end_phase_key, self.start_phase_key

    @property
    def controller(self):
        return self.signal_emulator.controllers.get_by_key(self.controller_key)

    @property
    def start_phase(self):
        return self.signal_emulator.phases.get_by_key((self.controller_key, self.start_phase_key))

    @property
    def end_phase(self):
        return self.signal_emulator.phases.get_by_key((self.controller_key, self.end_phase_key))


@dataclass(eq=False)
class Intergreen(BaseIntergreen):
    def __post_init__(self):
        self.controller.intergreen_keys.append((self.end_phase_key, self.start_phase_key))

    def get_key(self):
        return self.controller_key, self.end_phase_key, self.start_phase_key

    @property
    def modified_intergreen(self):
        return self.signal_emulator.modified_intergreens.get_by_key(
            self.get_key() + (self.signal_emulator.time_periods.active_period_id,)
        )

    @property
    def modified_intergreen_time(self):
        return self.modified_intergreen.intergreen_time if self.modified_intergreen else self.intergreen_time


class Intergreens(BaseCollection):
    ITEM_CLASS = Intergreen
    TABLE_NAME = "intergreens"
    WRITE_TO_DATABASE = True

    def __init__(self, item_data, signal_emulator):
        super().__init__(item_data=item_data, signal_emulator=signal_emulator)

    def get_by_key(self, key, modified=False):
        if modified and self.signal_emulator.modified_intergreens.key_exists(
            key + (self.signal_emulator.time_periods.active_period_id,)
        ):
            return self.signal_emulator.modified_intergreens.get_by_key(
                key + (self.signal_emulator.time_periods.active_period_id,)
            )
        else:
            controller_key, end_phase_key, start_phase_key = key
            return self.data.get(
                key,
                BaseIntergreen(
                    controller_key,
                    end_phase_key,
                    start_phase_key,
                    0,
                    signal_emulator=self.signal_emulator,
                ),
            )

    def exists_by_phase_keys(self, controller_key, end_phase_key, start_phase_key, modified=False):
        if modified:
            modified_exists = self.signal_emulator.modified_intergreens.key_exists(
                (
                    controller_key,
                    end_phase_key,
                    start_phase_key,
                    self.signal_emulator.time_periods.active_period_id,
                )
            )
        else:
            modified_exists = False
        return (controller_key, end_phase_key, start_phase_key) in self.data or modified_exists

    def get_by_phase_keys(self, controller_key, end_phase_key, start_phase_key, modified=False):
        if modified and self.signal_emulator.modified_intergreens.key_exists(
            (
                controller_key,
                end_phase_key,
                start_phase_key,
                self.signal_emulator.time_periods.active_period_id,
            )
        ):
            return self.signal_emulator.modified_intergreens.get_by_key(
                (
                    controller_key,
                    end_phase_key,
                    start_phase_key,
                    self.signal_emulator.time_periods.active_period_id,
                )
            )
        else:
            return self.data.get((controller_key, end_phase_key, start_phase_key), None)

    def get_intergreen_time_by_phase_keys(self, controller_key, end_phase_key, start_phase_key, modified=False):
        if modified and self.signal_emulator.modified_intergreens.key_exists(
            (
                controller_key,
                end_phase_key,
                start_phase_key,
                self.signal_emulator.time_periods.active_period_id,
            )
        ):
            return self.signal_emulator.modified_intergreens.get_by_key(
                (
                    controller_key,
                    end_phase_key,
                    start_phase_key,
                    self.signal_emulator.time_periods.active_period_id,
                )
            ).intergreen_time

        if not self.key_exists((controller_key, end_phase_key, start_phase_key)):
            return 0
        else:
            return self.data.get((controller_key, end_phase_key, start_phase_key)).intergreen_time

    @property
    def num_items_non_zero(self):
        return len([a for a in self if a.intergreen_time > 0])


@dataclass(eq=False)
class ModifiedIntergreen(BaseIntergreen):
    time_period_id: str
    original_time: int

    def __post_init__(self):
        pass

    def get_key(self):
        return self.controller_key, self.end_phase_key, self.start_phase_key, self.time_period_id


class ModifiedIntergreens(BaseCollection):
    ITEM_CLASS = ModifiedIntergreen
    TABLE_NAME = "modified_intergreens"
    WRITE_TO_DATABASE = True

    def __init__(self, item_data, signal_emulator):
        super().__init__(item_data=item_data, signal_emulator=signal_emulator)


@dataclass(eq=False)
class BasePhaseDelay(BaseItem):
    controller_key: str
    end_stage_key: int
    start_stage_key: int
    phase_ref: str
    delay_time: int
    signal_emulator: "SignalEmulator"
    is_absolute: bool

    def __repr__(self):
        return f"PhaseDelay: {self.end_stage_key=} {self.start_stage_key=} {self.phase_ref=} {self.delay_time=}"

    def get_key(self):
        return self.controller_key, self.end_stage_key, self.start_stage_key, self.phase_ref

    @property
    def controller(self):
        return self.signal_emulator.controllers.get_by_key(self.controller_key)

    @property
    def end_stage(self):
        return self.signal_emulator.stages.get_by_key((self.controller_key, self.end_stage_key))

    @property
    def start_stage(self):
        return self.signal_emulator.stages.get_by_key((self.controller_key, self.start_stage_key))

    @property
    def phase(self):
        return self.signal_emulator.phases.get_by_key((self.controller_key, self.phase_ref))

    @property
    def phase_delay_type(self):
        if self.phase_ref in self.end_stage.phase_keys_in_stage:
            return "gaining"
        elif self.phase_ref in self.start_stage.phase_keys_in_stage:
            return "losing"
        else:
            raise ValueError

    @property
    def modified_delay_time(self):
        return 0


@dataclass(eq=False)
class PhaseDelay(BasePhaseDelay):
    def __post_init__(self):
        self.controller.phase_delay_keys.append((self.end_stage_key, self.start_stage_key, self.phase_ref))

    @property
    def is_valid(self):
        return (
            self.phase_ref in self.end_stage.phase_keys_in_stage
            or self.phase_ref in self.start_stage.phase_keys_in_stage
        )

    @property
    def modified_phase_delay(self):
        return self.signal_emulator.modified_phase_delays.get_by_key(
            self.get_key() + (self.signal_emulator.time_periods.active_period_id,)
        )

    @property
    def modified_delay_time(self):
        return self.modified_phase_delay.delay_time if self.modified_phase_delay else self.delay_time


class PhaseDelays(BaseCollection):
    ITEM_CLASS = PhaseDelay
    TABLE_NAME = "phase_delays"
    WRITE_TO_DATABASE = True

    def __init__(self, item_data, signal_emulator, remove_invalid=False):
        super().__init__(item_data=item_data, signal_emulator=signal_emulator)
        if remove_invalid:
            self.remove_invalid()

    def get_by_key(self, key, modified=False):
        if modified and self.signal_emulator.modified_phase_delays.key_exists(
            (key + (self.signal_emulator.time_periods.active_period_id,))
        ):
            return self.signal_emulator.modified_phase_delays.get_by_key(
                (key + (self.signal_emulator.time_periods.active_period_id,))
            )
        else:
            return self.data.get(
                key,
                BasePhaseDelay(*key, delay_time=0, signal_emulator=self.signal_emulator, is_absolute=True),
            )

    def remove_invalid(self):
        for phase_delay in list(self):
            if (
                phase_delay.phase_ref not in phase_delay.end_stage.phase_keys_in_stage
                and phase_delay.phase_ref not in phase_delay.start_stage.phase_keys_in_stage
            ):
                self.signal_emulator.logger.warning(
                    f"Phase delay: {phase_delay.get_key()} "
                    f"removed because phase ref not found in end stage or start stage"
                )
                self.remove_by_key(phase_delay.get_key())
                phase_delay.controller.phase_delay_keys.remove(
                    (phase_delay.end_stage_key, phase_delay.start_stage_key, phase_delay.phase_ref)
                )

    def get_delay_time_by_stage_and_phase_keys(
        self, controller_key, end_stage_key, start_stage_key, phase_key, modified=False
    ):
        if modified and self.signal_emulator.modified_phase_delays.key_exists(
            (
                controller_key,
                end_stage_key,
                start_stage_key,
                phase_key,
                self.signal_emulator.time_periods.active_period_id,
            )
        ):
            return self.signal_emulator.modified_phase_delays.get_by_key(
                (
                    controller_key,
                    end_stage_key,
                    start_stage_key,
                    phase_key,
                    self.signal_emulator.time_periods.active_period_id,
                )
            ).delay_time
        elif self.key_exists((controller_key, end_stage_key, start_stage_key, phase_key)):
            return self.data.get((controller_key, end_stage_key, start_stage_key, phase_key)).delay_time
        else:
            return 0

    @property
    def num_items_linsig(self):
        return len([a for a in self if a.delay_time > 0 and a.start_stage_key > 0 and a.end_stage_key > 0])


@dataclass(eq=False)
class ModifiedPhaseDelay(BasePhaseDelay):
    original_delay_time: int
    time_period_id: str

    def __post_init__(self):
        pass

    def get_key(self):
        return (
            self.controller_key,
            self.end_stage_key,
            self.start_stage_key,
            self.phase_ref,
            self.time_period_id,
        )


class ModifiedPhaseDelays(PhaseDelays):
    ITEM_CLASS = ModifiedPhaseDelay
    TABLE_NAME = "modified_phase_delays"
    WRITE_TO_DATABASE = True

    def get_by_key(self, key, modified=False):
        return self.data.get(key, None)


@dataclass(eq=False)
class ProhibitedStageMove(BaseItem):
    controller_key: str
    end_stage_key: int
    start_stage_key: int
    via_stage_key: Union[int, None]
    prohibited: bool
    ignore: bool
    signal_emulator: "SignalEmulator"

    @property
    def end_stage(self):
        return self.signal_emulator.stages.get_by_key((self.controller_key, self.end_stage_key))

    @property
    def start_stage(self):
        return self.signal_emulator.stages.get_by_key((self.controller_key, self.start_stage_key))

    @property
    def via_stage(self):
        return self.signal_emulator.stages.get_by_key((self.controller_key, self.via_stage_key))

    def get_key(self):
        return self.controller_key, self.end_stage_key, self.start_stage_key


class ProhibitedStageMoves(BaseCollection):
    ITEM_CLASS = ProhibitedStageMove
    TABLE_NAME = "prohibited_stage_moves"
    WRITE_TO_DATABASE = True

    def __init__(self, item_data, signal_emulator):
        super().__init__(item_data=item_data, signal_emulator=signal_emulator)

    def is_prohibited_by_stage_keys(self, controller_key, end_stage_key, start_stage_key):
        return (controller_key, end_stage_key, start_stage_key) in self.data


@dataclass(eq=False)
class PhaseTiming:
    signal_emulator: "SignalEmulator"
    controller_key: str
    site_id: str
    phase_ref: str
    index: int
    time_period_id: str
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    cycle_time: Optional[int] = None

    def __repr__(self):
        return (
            f"PhaseTiming: site_id:{self.site_id} phase_ref:{self.phase_ref} index:{self.index} "
            f"start_time:{self.start_time} end_time:{self.end_time}"
        )

    def get_key(self):
        return self.site_id, self.phase_ref, self.index, self.time_period_id

    def get_controller_key_phase_ref_time_period_id(self):
        return self.controller_key, self.phase_ref, self.time_period_id

    @property
    def signal_group_number(self):
        return self.index * len(self.controller.phases) + self.phase.phase_number

    @property
    def visum_phase_name(self):
        phase_timings = self.phase.get_phase_timings_by_time_period_id(self.time_period_id)
        if len(phase_timings) > 1:
            return f"{self.phase_ref}{self.index + 1}"
        else:
            return self.phase_ref

    @property
    def controller(self):
        return self.signal_emulator.controllers.get_by_key(self.controller_key)

    @property
    def phase(self):
        return self.signal_emulator.phases.get_by_key(self.get_phase_key())

    @property
    def green_time(self):
        if self.end_time > self.start_time:
            return self.end_time - self.start_time
        else:
            return self.cycle_time - self.start_time + self.end_time

    @property
    def effective_end_time(self):
        if (
            self.phase.phase_type != PhaseType.T
            or self.green_time == 0
            or self.green_time == self.cycle_time
            or self.green_time == self.cycle_time - 1
        ):
            return self.end_time
        effective_end_time = self.end_time + self.signal_emulator.phase_timings.effective_green_time_adjustment
        if effective_end_time > self.cycle_time:
            effective_end_time = effective_end_time % self.cycle_time
        return effective_end_time

    @property
    def effective_green_time(self):
        if self.effective_end_time > self.start_time:
            return self.effective_end_time - self.start_time
        else:
            return self.cycle_time - self.start_time + self.effective_end_time

    def get_phase_key(self):
        return self.controller_key, self.phase_ref


class PhaseTimings(BaseCollection):
    ITEM_CLASS = PhaseTiming
    TABLE_NAME = "phase_timings"
    WRITE_TO_DATABASE = True

    def __init__(self, item_data, effective_green_time_adjustment, signal_emulator):
        super().__init__(item_data=item_data, signal_emulator=signal_emulator)
        self.data_by_controller_key_phase_ref_time_period_id = defaultdict(list)
        self.effective_green_time_adjustment = effective_green_time_adjustment
        for phase_timing in self:
            self.data_by_controller_key_phase_ref_time_period_id[
                phase_timing.get_controller_key_phase_ref_time_period_id()
            ].append(phase_timing)

    def remove_all(self):
        super().remove_all()
        self.data_by_controller_key_phase_ref_time_period_id = defaultdict(list)

    def add_instance(self, item):
        if isinstance(item, self.ITEM_CLASS):
            self.data[item.get_key()] = item
            self.data_by_controller_key_phase_ref_time_period_id[
                item.get_controller_key_phase_ref_time_period_id()
            ].append(item)
        else:
            self.signal_emulator.logger(
                f"Item: {item} cannot be added to Collection: {self.__class__.__name__} as it is not the correct type"
            )

    def get_last(self):
        if len(self.data) == 0:
            return None
        else:
            return self.data[len(self.data) - 1]

    def get_by_controller_key_phase_ref_time_period_id(self, controller_key, phase_ref, time_period_id):
        return self.data_by_controller_key_phase_ref_time_period_id[(controller_key, phase_ref, time_period_id)]


@dataclass(eq=False)
class PhaseStageDemandDependency(BaseItem):
    controller_key: str
    stage_number: int
    phase_ref: str
    signal_emulator: "SignalEmulator"

    def __post_init__(self):
        if self.stage:
            self.stage.phase_stage_demand_dependencies.append(self)
        else:
            self.signal_emulator.logger.warning(f"Stage: {self.controller_key} {self.stage_number} does not exist")

    @property
    def stage(self):
        return self.signal_emulator.stages.get_by_key(self.get_stage_key())

    def get_stage_key(self):
        return self.controller_key, self.stage_number

    @property
    def phase(self):
        return self.signal_emulator.phases.get_by_key(self.get_phase_key())

    def get_phase_key(self):
        return self.controller_key, self.phase_ref


class PhaseStageDemandDependencies(BaseCollection):
    ITEM_CLASS = PhaseStageDemandDependency
    TABLE_NAME = "phase_stage_demand_dependencies"
    WRITE_TO_DATABASE = True

    def __init__(self, item_data, signal_emulator):
        super().__init__(item_data=item_data, signal_emulator=signal_emulator)
