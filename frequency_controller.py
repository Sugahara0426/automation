import json
import csv
import os

# ============================================================
# Slack通知を使用するときに有効化
# ============================================================

# import urllib.request

import pyvisa
import matplotlib.pyplot as plt

from kafka import KafkaConsumer
from pylablib.devices import Attocube

import vna_tools
from tune_piezo import tune_piezo


# ============================================================
# 保存場所
#
# frequency_controller.pyと同じ場所を基準にする
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

os.chdir(BASE_DIR)


# ============================================================
# Kafka / VNA設定
# ============================================================

KAFKA_SERVER = "10.105.52.103:9092"
KAFKA_TOPIC = "frequency_control"

VNA_RESOURCE = (
    "TCPIP0::192.168.12.4::inst0::INSTR"
)


# ============================================================
# Slack設定
#
# Webhook URL取得後にコメントアウトを外す
# ============================================================

# SLACK_WEBHOOK_URL = (
#     "https://hooks.slack.com/services/..."
# )

# 表示用
# 実際の送信先はWebhookに紐づいたチャンネル
# SLACK_CHANNEL = "#frequency-tuning"


# ============================================================
# Slack通知
#
# Webhook URL取得後にコメントアウトを外す
# ============================================================

# def notify_slack(message):
#     """Slack Incoming Webhookへ通知する。"""
#
#     if not SLACK_WEBHOOK_URL:
#         print(
#             "WARNING: Slack Webhook URL "
#             "is not configured."
#         )
#         return False
#
#     payload = json.dumps(
#         {
#             "text": message
#         }
#     ).encode("utf-8")
#
#     request = urllib.request.Request(
#         SLACK_WEBHOOK_URL,
#         data=payload,
#         headers={
#             "Content-Type": "application/json"
#         },
#         method="POST",
#     )
#
#     try:
#
#         with urllib.request.urlopen(
#             request,
#             timeout=5,
#         ) as response:
#             response.read()
#
#         print(
#             f"Slack notification sent "
#             f"({SLACK_CHANNEL})."
#         )
#
#         return True
#
#     except Exception as e:
#
#         print(
#             f"WARNING: "
#             f"Slack notification failed: {e}"
#         )
#
#         return False


# ============================================================
# VNA Narrow sweep範囲 [GHz]
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
        value_deserializer=lambda m: json.loads(
            m.decode("utf-8")
        ),
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
    target_frequency = message.get(
        "target_frequency"
    )

    if mode is None:
        print("ERROR: modeがありません。")
        return None

    if target_frequency is None:
        print(
            "ERROR: target_frequencyがありません。"
        )
        return None

    mode = mode.upper()

    if mode not in ("TM110", "TM210"):
        print(
            f"ERROR: Unknown mode: {mode}"
        )
        return None

    try:
        target_frequency = float(
            target_frequency
        )

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

def check_target_range(
    mode,
    target_frequency,
):

    freq_range = VNA_NARROW_RANGE[mode]

    min_freq = freq_range["min_ghz"]
    max_freq = freq_range["max_ghz"]

    if min_freq <= target_frequency <= max_freq:
        return True

    print("\n======================================")
    print(
        "ERROR: "
        "Target frequency is outside VNA range."
    )
    print("======================================")

    print(f"Mode   : {mode}")

    print(
        f"Target : "
        f"{target_frequency:.9f} GHz"
    )

    print(
        f"Range  : "
        f"{min_freq:.9f} - "
        f"{max_freq:.9f} GHz"
    )

    print("\nCommand rejected.")
    print("Piezo will not move.")

    return False


# ============================================================
# VNAデータ保存 + PNG保存
# ============================================================

def save_vna_data(
    znb,
    mode,
    target_frequency,
    tuning_index,
    current_frequency,
):
    """
    VNAを10回測定してCSVを保存し、
    Narrow S11から共鳴周波数を求めてPNGを保存する。

    Returns
    -------
    resonance_frequency : float
        保存したVNAデータから求めた共鳴周波数 [GHz]
    """

    suffix = (
        f"{mode}_"
        f"{target_frequency:.6f}GHz_"
        f"tuning{tuning_index:02d}"
    )

    print("\n======================================")
    print(
        f"Saving VNA data - Tuning {tuning_index}"
    )
    print("======================================")

    print(
        f"Suffix : {suffix}"
    )

    # --------------------------------------------------------
    # VNAデータ保存
    # --------------------------------------------------------

    summary_filename = (
        vna_tools.measure_and_save(
            znb,
            suffix_arg=suffix,
        )
    )

    print("VNA data saved.")

    # --------------------------------------------------------
    # 使用するNarrow mode
    # --------------------------------------------------------

    if mode == "TM110":
        measurement_mode = "110_Narrow"

    elif mode == "TM210":
        measurement_mode = "210_Narrow"

    else:
        raise ValueError(
            f"Unknown mode: {mode}"
        )

    # --------------------------------------------------------
    # Summary CSV読み込み
    # --------------------------------------------------------

    frequencies = []
    s11_amplitudes = []

    with open(
        summary_filename,
        "r",
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:

            if (
                row["Measurement_Mode"]
                != measurement_mode
            ):
                continue

            frequency_ghz = (
                float(
                    row["Frequency [Hz]"]
                )
                / 1e9
            )

            s11_amp = float(
                row["S11_Amp_Mean"]
            )

            frequencies.append(
                frequency_ghz
            )

            s11_amplitudes.append(
                s11_amp
            )

    if not frequencies:
        raise RuntimeError(
            f"No data found for "
            f"{measurement_mode}"
        )

    # --------------------------------------------------------
    # 平均S11が最小になる周波数
    # --------------------------------------------------------

    min_index = (
        s11_amplitudes.index(
            min(s11_amplitudes)
        )
    )

    resonance_frequency = (
        frequencies[min_index]
    )

    resonance_amp = (
        s11_amplitudes[min_index]
    )

    error_khz = (
        target_frequency
        - resonance_frequency
    ) * 1e6

    print("\nSaved VNA resonance:")

    print(
        f"Resonance : "
        f"{resonance_frequency:.9f} GHz"
    )

    print(
        f"Target    : "
        f"{target_frequency:.9f} GHz"
    )

    print(
        f"Error     : "
        f"{error_khz:+.3f} kHz"
    )

    # ========================================================
    # PNG
    # ========================================================

    plt.figure(
        figsize=(8, 6)
    )

    plt.plot(
        frequencies,
        s11_amplitudes,
        label="S11",
    )

    plt.axvline(
        target_frequency,
        linestyle="--",
        label=(
            "Target "
            f"{target_frequency:.9f} GHz"
        ),
    )

    plt.axvline(
        resonance_frequency,
        linestyle=":",
        label=(
            "Resonance "
            f"{resonance_frequency:.9f} GHz"
        ),
    )

    plt.scatter(
        [resonance_frequency],
        [resonance_amp],
        zorder=5,
    )

    info_text = (
        f"Tuning    : {tuning_index}\n"
        f"Pre-save  : {current_frequency:.9f} GHz\n"
        f"Target    : {target_frequency:.9f} GHz\n"
        f"Resonance : {resonance_frequency:.9f} GHz\n"
        f"Error     : {error_khz:+.3f} kHz"
    )

    plt.text(
        0.02,
        0.98,
        info_text,
        transform=plt.gca().transAxes,
        verticalalignment="top",
        bbox=dict(
            boxstyle="round",
            alpha=0.8,
        ),
    )

    plt.xlabel(
        "Frequency [GHz]"
    )

    plt.ylabel(
        "|S11|"
    )

    plt.title(
        f"{mode} Frequency Tuning "
        f"- Tuning {tuning_index}"
    )

    plt.grid()
    plt.legend()
    plt.tight_layout()

    # --------------------------------------------------------
    # PNG保存
    # --------------------------------------------------------

    image_filename = (
        os.path.splitext(
            summary_filename
        )[0]
        + ".png"
    )

    plt.savefig(
        image_filename,
        dpi=150,
    )

    plt.close()

    print(
        f"VNA plot saved to: "
        f"{image_filename}"
    )

    # ========================================================
    # 重要
    #
    # この値をFeedbackと最終SG周波数に使用する
    # ========================================================

    return resonance_frequency


# ============================================================
# Controller
# ============================================================

def run_controller(atc):

    print("\n======================================")
    print("Frequency Controller")
    print("======================================")

    # --------------------------------------------------------
    # VNA接続
    # --------------------------------------------------------

    print("\nConnecting to VNA...")

    rm = pyvisa.ResourceManager(
        "@py"
    )

    znb = vna_tools.get_vna_resource(
        rm,
        VNA_RESOURCE,
    )

    print("Setting up VNA...")

    vna_tools.setup_vna(
        znb
    )

    print("VNA setup completed.")

    # --------------------------------------------------------
    # Kafka
    # --------------------------------------------------------

    print("\nConnecting to Kafka...")

    consumer = create_consumer()

    print("Kafka connected.")
    print(f"Server : {KAFKA_SERVER}")
    print(f"Topic  : {KAFKA_TOPIC}")

    print(
        "\nWaiting for frequency command..."
    )

    # ========================================================
    # Kafka常駐
    # ========================================================

    try:

        while True:

            records = consumer.poll(
                timeout_ms=1000
            )

            for _, messages in records.items():

                for msg in messages:

                    print(
                        "\n======================================"
                    )

                    print(
                        "Kafka message received"
                    )

                    print(
                        "======================================"
                    )

                    print(msg.value)

                    # ------------------------------------------------
                    # Command解析
                    # ------------------------------------------------

                    command = parse_command(
                        msg.value
                    )

                    if command is None:
                        print("Command skipped.")
                        continue

                    mode, target_frequency = (
                        command
                    )

                    print(
                        f"\nMode   : {mode}"
                    )

                    print(
                        f"Target : "
                        f"{target_frequency:.9f} GHz"
                    )

                    # ------------------------------------------------
                    # VNA範囲確認
                    # ------------------------------------------------

                    if not check_target_range(
                        mode,
                        target_frequency,
                    ):

                        print(
                            "\nWaiting for next "
                            "frequency command..."
                        )

                        continue

                    # ====================================================
                    # Piezo Feedback
                    # ====================================================

                    try:

                        final_f0 = tune_piezo(
                            atc=atc,
                            znb=znb,
                            target_f0=target_frequency,
                            mode=mode,
                            tolerance_khz=10.0,
                            max_iterations=50,
                            wait_time=1.0,
                            probe_steps=10,
                            save_callback=save_vna_data,

                            # Slack使用時に有効化
                            # notify_callback=notify_slack,
                        )

                    except Exception as e:

                        print(
                            "\nERROR during "
                            "frequency tuning:"
                        )

                        print(e)

                        # Slack使用時に有効化
                        #
                        # notify_slack(
                        #     (
                        #         f"🚨 {mode} "
                        #         f"Frequency Controller Error\n"
                        #         f"Target: "
                        #         f"{target_frequency:.9f} GHz\n"
                        #         f"Error: {e}"
                        #     )
                        # )

                        print(
                            "\nWaiting for next "
                            "frequency command..."
                        )

                        continue

                    # ====================================================
                    # 調整失敗
                    # ====================================================

                    if final_f0 is None:

                        print(
                            "\nFrequency tuning failed."
                        )

                        print(
                            "\nWaiting for next "
                            "frequency command..."
                        )

                        continue

                    # ====================================================
                    # 調整成功
                    #
                    # final_f0は最後に保存したPNGの
                    # Resonanceと同じ値
                    # ====================================================

                    error_khz = (
                        target_frequency
                        - final_f0
                    ) * 1e6

                    print(
                        "\n======================================"
                    )

                    print(
                        "Frequency tuning finished"
                    )

                    print(
                        "======================================"
                    )

                    print(
                        f"Target          : "
                        f"{target_frequency:.9f} GHz"
                    )

                    print(
                        f"Final resonance : "
                        f"{final_f0:.9f} GHz"
                    )

                    print(
                        f"Final error     : "
                        f"{error_khz:+.3f} kHz"
                    )

                    print(
                        f"SG frequency    : "
                        f"{final_f0:.9f} GHz"
                    )

                    # ------------------------------------------------
                    # 将来ここでSGへfinal_f0を設定する
                    # ------------------------------------------------
                    #
                    # set_sg_frequency(final_f0)

                    print(
                        "\nWaiting for next "
                        "frequency command..."
                    )

    except KeyboardInterrupt:

        print(
            "\nFrequency Controller "
            "stopped by user."
        )

    finally:

        print(
            "\nClosing Kafka consumer..."
        )

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

    print("\nConnecting to ANC350...")

    atc = Attocube.ANC350()

    print("ANC350 connected.")

    try:

        run_controller(
            atc
        )

    finally:

        print("\nClosing ANC350...")

        atc.close()

        print("ANC350 closed.")

        print(
            "Frequency Controller shutdown."
        )
