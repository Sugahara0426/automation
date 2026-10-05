import json
from kafka import KafkaProducer


# ============================================================
# Kafka設定
# ============================================================

KAFKA_SERVER = "10.105.52.103:9092"
KAFKA_TOPIC = "frequency_control"


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
# Producer
# ============================================================

class FrequencyCommandProducer:

    def __init__(
        self,
        kafka_server=KAFKA_SERVER,
        kafka_topic=KAFKA_TOPIC,
    ):
        self.kafka_topic = kafka_topic

        self.producer = KafkaProducer(
            bootstrap_servers=kafka_server,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

    def send_target(self, mode, target_frequency_khz):

        # Mode確認
        mode = mode.upper()

        if mode not in ("TM110", "TM210"):
            raise ValueError(f"Unknown mode: {mode}")

        # 入力値をfloatへ変換
        try:
            target_frequency_khz = float(target_frequency_khz)
        except (TypeError, ValueError):
            raise ValueError(
                "target_frequency_khz must be a number."
            )

        # kHz → GHz
        target_frequency = target_frequency_khz / 1e6

        # --------------------------------------------------------
        # VNA範囲チェック
        # --------------------------------------------------------

        freq_range = VNA_NARROW_RANGE[mode]

        min_freq = freq_range["min_ghz"]
        max_freq = freq_range["max_ghz"]

        if not (min_freq <= target_frequency <= max_freq):
            raise ValueError(
                "\nTarget frequency is outside VNA range.\n"
                f"Mode   : {mode}\n"
                f"Target : {target_frequency_khz:.3f} kHz\n"
                f"       = {target_frequency:.9f} GHz\n"
                f"Range  : "
                f"{min_freq * 1e6:.3f} - "
                f"{max_freq * 1e6:.3f} kHz\n"
                "Kafka message was NOT sent."
            )

        # --------------------------------------------------------
        # Kafka message
        #
        # ControllerにはGHzで渡す
        # --------------------------------------------------------

        message = {
            "command": "tune",
            "mode": mode,
            "target_frequency": target_frequency,
        }

        print("\nSending frequency command:")
        print(f"Mode   : {mode}")
        print(f"Target : {target_frequency_khz:.3f} kHz")
        print(f"       = {target_frequency:.9f} GHz")

        future = self.producer.send(
            self.kafka_topic,
            value=message,
        )

        future.get(timeout=10)

        print("Frequency command sent.")

    def close(self):
        self.producer.flush()
        self.producer.close()


# ============================================================
# 単体テスト
# ============================================================

if __name__ == "__main__":

    producer = FrequencyCommandProducer()

    try:
        producer.send_target(
            mode="TM110",
            target_frequency_khz=1897400,
        )

    finally:
        producer.close()
    finally:

        producer.close()
