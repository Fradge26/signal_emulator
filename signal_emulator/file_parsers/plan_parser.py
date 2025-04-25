import os
import re

from signal_emulator.utilities.utility_functions import txt_file_to_list, clean_site_number


class PlanParser:
    def __init__(self):
        pass

    @staticmethod
    def plan_file_iterator(plan_directory_path):
        for filename in os.listdir(plan_directory_path):
            plan_path = os.path.join(plan_directory_path, filename)
            if plan_path.endswith("pln") and os.path.isfile(plan_path):
                yield plan_path

    def pln_to_attr_dict(self, plan_file_path):
        input_plans_list = txt_file_to_list(plan_file_path)
        processed_args = {"plans": [], "plan_sequence_items": []}
        plan_number, cycle_time, timeout, index, header_found = None, None, None, 0, False
        site_id = self.get_site_id_from_pln_path(plan_file_path)
        name = None
        for row in input_plans_list:
            if self.is_header_row(row):
                header_found = True
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
            elif row == "":
                continue
            elif row.startswith("%"):
                name = row.replace("% ", "")
            elif row.startswith("*") and header_found:
                if not name:
                    name = f"Plan {plan_number}"
                processed_args["plans"].append(
                    {
                        "site_id": site_id,
                        "plan_number": plan_number,
                        "cycle_time": cycle_time,
                        "timeout": timeout,
                        "name": name.upper(),
                    }
                )
                header_found = False
                name = None
            elif not row.startswith((";", "#", "*")) and row.split("/")[0].isnumeric():
                processed_args["plan_sequence_items"].append(
                    self.plan_row_to_plan_sequence_item(row, site_id, plan_number, index)
                )
                index += 1
            if row.startswith("*"):
                index = 0
        return processed_args

    @staticmethod
    def get_site_id_from_pln_path(plan_file_path):
        directory, filename = os.path.split(plan_file_path)
        return clean_site_number(f"J{filename[1:3]}/{filename[3:6]}")

    @staticmethod
    def is_header_row(row):
        row_upper = row.upper()
        return "PLAN" in row_upper and "CYCLE" in row_upper and row_upper[0] not in {"#", "%"}

    def plan_row_to_plan_sequence_item(self, row, site_id, plan_number, index):
        data_split = row.split("/")
        f_bits, d_bits, p_bits, nto = self.get_commands_from_str(data_split[1])
        return {
            "site_id": site_id,
            "plan_number": plan_number,
            "index": index,
            "pulse_time": int(data_split[0]),
            "scoot_stage": data_split[2],
            "f_bits": f_bits,
            "d_bits": d_bits,
            "p_bits": p_bits,
            "nto": nto,
        }

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
