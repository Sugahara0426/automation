from kafka import KafkaProducer
import json
import time
import random

class KafkaProducerModule:

    def __init__( self, ip_port: str, topic: str, device_name: str, data_type: str ):
        self.kafka_topic = topic
        self.device_name = device_name
        self.data_type = data_type

        # Kafka Producer Configuration
        self.producer = KafkaProducer(
            bootstrap_servers = ip_port,
            value_serializer = lambda v: json.dumps(v).encode("utf-8") # convert to JSON
        )

    def Send( self, value: dict ):
        payload = {
            "device_name": self.device_name,
            "data_type": self.data_type,
            "value": value
            }


        try:
            ### unsynchronized data sending
            future = self.producer.send( self.kafka_topic, value = payload )

            ### show sending result by callback function
            future.add_callback( self.on_send_success, payload )
            future.add_errback( self.on_send_error, payload )

        except Exception as e:
            print(f"Failed to send message: {e}")


    def on_send_success( self, record_metadata, payload ):
        print(f"Message delivered: topic={record_metadata.topic}, partition={record_metadata.partition}, offset={record_metadata.offset}, payload={payload}")

    def on_send_error( self, exc, payload ):
        print(f"Message delivery failed: {exc}, payload={payload}")


    def ChangeDevice( self, device_name ):
        self.device_name = device_name

    def ChangeDataType( self, data_type ):
        self.data_type = data_type

        
if __name__ == "__main__":
    KAFKA_TOPIC = "testdb"
    KAFKA_SERVER = "10.105.52.103:9092"
    DEVICE_NAME = "Piezo_TM110"
    DATA_TYPE = "encorder"
    DEVICE_NAME2 = "Thermometer"
    DATA_TYPE2 = "temperature"

    producer = KafkaProducerModule(
        ip_port = KAFKA_SERVER,
        topic = KAFKA_TOPIC,
        device_name = DEVICE_NAME,
        data_type = DATA_TYPE
    )

    while True:
        producer.ChangeDevice( DEVICE_NAME )
        producer.ChangeDataType( DATA_TYPE )
        sample_value = round( 300.0 + random.uniform(-10.0, 10.0), 2) 
        sample_data = { "timestamp": int( time.time() ), "value": sample_value }
        producer.Send( sample_data )
        time.sleep( 0.5 )

        
        producer.ChangeDevice( DEVICE_NAME2 )
        producer.ChangeDataType( DATA_TYPE2 )
        sample_value2 = round( random.uniform( 26.0, 28.0), 2)
        sample_data2 = { "timestamp": int( time.time() ), "value": sample_value2 }
        producer.Send( sample_data2 )
        time.sleep( 0.5 )
