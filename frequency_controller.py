import json

import pyvisa
from kafka import KafkaConsumer
from pylablib.devices import Attocube

import vna_tools
from tune_piezo import tune_piezo


# ============================================================
# 基本設定
# ============================================================

KAFKA_SERVER = "10.105.52.103:9092"
KAFKA_TOPIC = "frequency_control"

VNA_RESOURCE = "TCPIP0::192.168.12.4::inst0::INSTR"


# ============================================================
# VNA Narrow sweep範囲
#
# 現在の vna_tools.py の setup_vna() に合わせている
#
# TM110:
#   center = 1.8974 GHz
#   span   = 4 MHz
#   range  = 1.8954 - 1.8994 GHz
#
# TM210:
#   center = 2.5659 GHz
#   span   = 4 MHz
#   range  = 2.5639 - 2.5679 GHz
# ============================================================

VNA_NARROW_RANGE = {
    "TM110": {
        "min_ghz": 1.8954,
        "max_ghz": 1.8994,
    },

    "TM210": {
        "min_ghz": 2.5639,
        "max_ghz": 2.5679,
    },
}


# ============================================================
# Kafka Consumer
# ============================================================

def create_consumer():

    return KafkaConsumer(
        KAFKA_TOPIC,

        bootstrap_servers=KAFKA_SERVER,

        value_deserializer=lambda m:
            json.loads(m.decode("utf-8")),

        auto_offset_reset="latest",
        enable_auto_commit=True,
    )


# ============================================================
# Kafka message解析
# ============================================================

def parse_command(message):

    if not isinstance(message, dict):
        print("ERROR: message is not dict.")
        return None

    if message.get("command") != "tune":
        print("Command is not 'tune'.")
        return None

    mode = message.get("mode")
    target_frequency = message.get("target_frequency")

    if mode is None:
        print("ERROR: modeがありません。")
        return None

    if target_frequency is None:
        print("ERROR: target_frequencyがありません。")
        return None

    mode = mode.upper()

    if mode not in ("TM110", "TM210"):
        print(f"ERROR: Unknown mode: {mode}")
        return None

    try:
        target_frequency = float(target_frequency)

    except (TypeError, ValueError):

        print(
            "ERROR: target_frequencyを"
            "数値に変換できません。"
        )

        return None

    return mode, target_frequency


# ============================================================
# VNA範囲チェック
# ============================================================

def check_target_range(mode, target_frequency):

    freq_range = VNA_NARROW_RANGE[mode]

    min_freq = freq_range["min_ghz"]
    max_freq = freq_range["max_ghz"]

    if min_freq <= target_frequency <= max_freq:
        return True

    print("\n======================================")
    print("ERROR: Target frequency is outside VNA range.")
    print("======================================")

    print(f"Mode   : {mode}")
    print(f"Target : {target_frequency:.9f} GHz")

    print(
        f"Range  : "
        f"{min_freq:.9f} - {max_freq:.9f} GHz"
    )

    print("\nCommand rejected.")
    print("Piezo will not move.")

    return False


# ============================================================
# Controller本体
# ============================================================

def run_controller(atc):

    print("\n======================================")
    print("Frequency Controller")
    print("======================================")

    # --------------------------------------------------------
    # VNA接続
    # --------------------------------------------------------

    print("\nConnecting to VNA...")

    rm = pyvisa.ResourceManager("@py")

    znb = vna_tools.get_vna_resource(
        rm,
        VNA_RESOURCE
    )

    print("Setting up VNA...")

    vna_tools.setup_vna(znb)

    print("VNA setup completed.")

    # --------------------------------------------------------
    # Kafka接続
    # --------------------------------------------------------

    print("\nConnecting to Kafka...")

    consumer = create_consumer()

    print("Kafka connected.")
    print(f"Server : {KAFKA_SERVER}")
    print(f"Topic  : {KAFKA_TOPIC}")

    print("\nWaiting for frequency command...")

    # --------------------------------------------------------
    # 常駐ループ
    # --------------------------------------------------------

    try:

        while True:

            records = consumer.poll(
                timeout_ms=1000
            )

            for _, messages in records.items():

                for msg in messages:

                    print("\n======================================")
                    print("Kafka message received")
                    print("======================================")

                    print(msg.value)

                    # ----------------------------------------
                    # Command解析
                    # ----------------------------------------

                    command = parse_command(
                        msg.value
                    )

                    if command is None:
                        print("Command skipped.")
                        continue

                    mode, target_frequency = command

                    print(f"\nMode   : {mode}")

                    print(
                        f"Target : "
                        f"{target_frequency:.9f} GHz"
                    )

                    # ----------------------------------------
                    # VNA範囲チェック
                    #
                    # 範囲外ならPiezoを動かさない
                    # ----------------------------------------

                    if not check_target_range(
                        mode,
                        target_frequency
                    ):

                        print(
                            "\nWaiting for next "
                            "frequency command..."
                        )

                        continue

                    # ----------------------------------------
                    # Piezo feedback
                    # ----------------------------------------

                    try:

                        final_f0 = tune_piezo(
                            atc=atc,
                            znb=znb,
                            target_f0=target_frequency,
                            mode=mode,
                            tolerance_khz=1.0,
                            max_iterations=50,
                        )

                    except Exception as e:

                        print(
                            "\nERROR during frequency tuning:"
                        )

                        print(e)

                        print(
                            "\nWaiting for next "
                            "frequency command..."
                        )

                        continue

                    # ----------------------------------------
                    # 結果表示
                    # ----------------------------------------

                    if final_f0 is None:

                        print(
                            "\nFrequency tuning failed."
                        )

                    else:

                        error_khz = (
                            target_frequency
                            - final_f0
                        ) * 1e6

                        print(
                            "\nFrequency tuning finished."
                        )

                        print(
                            f"Final : "
                            f"{final_f0:.9f} GHz"
                        )

                        print(
                            f"Error : "
                            f"{error_khz:+.3f} kHz"
                        )

                    print(
                        "\nWaiting for next "
                        "frequency command..."
                    )

    except KeyboardInterrupt:

        print(
            "\nFrequency Controller stopped "
            "by user."
        )

    finally:

        print("\nClosing Kafka consumer...")
        consumer.close()

        print("Closing VNA...")
        znb.close()
        rm.close()


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    print("\n======================================")
    print("Starting Frequency Controller")
    print("======================================")

    # ANC350接続
    print("\nConnecting to ANC350...")

    atc = Attocube.ANC350()

    print("ANC350 connected.")

    try:

        run_controller(atc)

    finally:

        print("\nClosing ANC350...")

        atc.close()

        print("ANC350 closed.")
        print("Frequency Controller shutdown.")
