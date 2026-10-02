import json

from kafka import KafkaProducer


# 設定

KAFKA_SERVER = "10.105.52.103:9092"
KAFKA_TOPIC = "frequency_control"

# Producer

class FrequencyCommandProducer:

    def __init__(
        self,
        kafka_server=KAFKA_SERVER,
        kafka_topic=KAFKA_TOPIC
    ):

        self.kafka_topic = kafka_topic

        self.producer = KafkaProducer(
            bootstrap_servers=kafka_server,

            value_serializer=lambda v:
                json.dumps(v).encode("utf-8")
        )


    def send_target(
        self,
        mode,
        target_frequency
    ):

        mode = mode.upper()

        if mode not in ("TM110", "TM210"):

            raise ValueError(
                f"Unknown mode: {mode}"
            )

        target_frequency = float(
            target_frequency
        )

        message = {
            "command": "tune",
            "mode": mode,
            "target_frequency": target_frequency,
        }

        print("\nSending frequency command:")
        print(message)

        future = self.producer.send(
            self.kafka_topic,
            value=message
        )

        # Kafkaへの送信完了を確認
        future.get(timeout=10)

        print("Frequency command sent.")


    def close(self):

        self.producer.flush()
        self.producer.close()


# 単体テスト

if __name__ == "__main__":

    producer = FrequencyCommandProducer()

    try:

        producer.send_target(
            mode="TM110",
            target_frequency=1.906
        )

    finally:

        producer.close()
