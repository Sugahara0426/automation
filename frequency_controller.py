import json

import pyvisa
from kafka import KafkaConsumer
from pylablib.devices import Attocube

import vna_tools
from tune_piezo import tune_piezo


# 設定

KAFKA_SERVER = "10.105.52.103:9092"
KAFKA_TOPIC = "frequency_control"

VNA_RESOURCE = "TCPIP0::192.168.12.4::inst0::INSTR"


# Kafka Consumer
def create_consumer():

    consumer = KafkaConsumer(
        KAFKA_TOPIC,

        bootstrap_servers=KAFKA_SERVER,

        value_deserializer=lambda m:
            json.loads(m.decode("utf-8")),

        # Controller起動前の古い命令は基本的に読まない
        auto_offset_reset="latest",

        enable_auto_commit=True,
    )

    return consumer


# Kafka message解析

def parse_command(message):

    if not isinstance(message, dict):
        print("ERROR: message is not dict.")
        return None

    # tune命令以外は無視
    if message.get("command") != "tune":
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
            "floatに変換できません。"
        )

        return None

    return mode, target_frequency


# Controller
def run_controller(atc):

    print("\n======================================")
    print("Frequency Controller")
    print("======================================")

    # VNA接続

    print("\nConnecting to VNA...")

    rm = pyvisa.ResourceManager("@py")

    znb = vna_tools.get_vna_resource(
        rm,
        VNA_RESOURCE
    )

    print("Setting up VNA...")

    vna_tools.setup_vna(znb)

    print("VNA setup completed.")

    # Kafka接続

    print("\nConnecting to Kafka...")

    consumer = create_consumer()

    print("Kafka connected.")
    print(f"Server : {KAFKA_SERVER}")
    print(f"Topic  : {KAFKA_TOPIC}")

    print("\nWaiting for frequency command...")

    # 常駐ループ
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

                    # 周波数調整
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
                            "\nWaiting for next command..."
                        )

                        continue

                    # 結果
                    if final_f0 is None:

                        print(
                            "\nFrequency tuning failed."
                        )

                    else:

                        error_khz = (
                            target_frequency - final_f0
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


# Main
if __name__ == "__main__":

    print("\n======================================")
    print("Starting Frequency Controller")
    print("======================================")

    # ANC350
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
