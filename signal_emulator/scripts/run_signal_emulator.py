from signal_emulator.emulator import SignalEmulator
from signal_emulator.utilities.utility_functions import load_json_to_dict


def run_all(config_path):
    config = load_json_to_dict(json_file_path=config_path)
    signal_emulator = SignalEmulator(config=config)
    signal_emulator.generate_signal_plans()
    signal_emulator.generate_phase_timings()
    signal_emulator.generate_visum_signal_groups()
    signal_emulator.generate_saturn_signal_groups()
    signal_emulator.saturn_signal_groups.export_to_rgs_files()
    signal_emulator.visum_signal_controllers.export_to_net_files()
    signal_emulator.visum_signal_groups.export_to_net_files()
    signal_emulator.linsig.export_all_to_lsg_v236()
    signal_emulator.export_to_database()


def run_from_files():
    run_all(config_path="signal_emulator/resources/configs/signal_emulator_from_files_config.json")


def run_from_postgres():
    run_all(config_path="signal_emulator/resources/configs/signal_emulator_from_pg_config.json")


if __name__ == "__main__":
    run_from_files()
    # run_from_postgres()
