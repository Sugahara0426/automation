from time import time, sleep
from MuSEUM_KafkaProducer import KafkaProducerModule
from RaS_NRP2 import RaS_NRP2

class RaS_NRP2_Operator:

    def __init__( self, waiting_time = 1 ):
        self.waiting_time = waiting_time
        self.ras_nrp2 = RaS_NRP2( "192.168.12.2" )

        self.producer = KafkaProducerModule(
            ip_port = "10.105.52.103:9092",
            topic = "testdb",
            device_name = "RaS_NRP2",
            data_type = "microwave_power"
        )

    def SendDataToKafka( self ):
        power1 = self.ras_nrp2.GetPower( 1 )
        data1 = { "timestamp": int( time() ) , "microwave_power": float( power1 ), "channel": "CH1" }
        self.producer.Send( data1 )
        print( data1 )

        power2 = self.ras_nrp2.GetPower( 2 )
        data2 = { "timestamp": int( time() ) , "microwave_power": float( power2 ), "channel": "CH2" }
        self.producer.Send( data2 )
        print( data2 )
        
        sleep( self.waiting_time )

if __name__ == "__main__":

    example = RaS_NRP2_Operator( 0.2 )
    while True:
        example.SendDataToKafka()
