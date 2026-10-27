#!/usr/local/bin/python3

from time import time, sleep
import os
from datetime import datetime
from MuSEUM_KafkaProducer import KafkaProducerModule

class MagneticField_Operator:
    """
    Magnetic Field data reader and Kafka sender
    Reads LastTrendData.csv and sends channel data to Kafka
    """
    
    def __init__(self, csv_file_path, waiting_time=3, max_channels=4):
        """
        Args:
            csv_file_path: Path to LastTrendData.csv
            waiting_time: Interval for checking CSV file (seconds)
            max_channels: Number of channels to send (default: 4, can be increased to 8)
        """
        self.csv_file_path = csv_file_path
        self.waiting_time = waiting_time
        self.max_channels = max_channels
        self.last_modified_time = 0
        
        # Kafka Producer設定
        self.producer = KafkaProducerModule(
            ip_port="10.105.52.103:9092",
            topic="testdb",
            device_name="MagneticField",
            data_type="proton_frequency"
        )
    
    def ReadCSV(self):
        """
        Read the latest line from CSV file
        Returns: dict with channel data or None if error
        """
        try:
            with open(self.csv_file_path, 'r') as f:
                lines = f.readlines()
                if len(lines) < 2:  # No data line
                    return None
                
                # Get header and last data line
                header = lines[0].strip().split(',')
                data_line = lines[-1].strip().split(',')
                
                # Create dictionary
                data_dict = {}
                for i, col_name in enumerate(header):
                    if i < len(data_line):
                        data_dict[col_name] = data_line[i]
                
                return data_dict
                
        except FileNotFoundError:
            print(f"CSV file not found: {self.csv_file_path}")
            return None
        except Exception as e:
            print(f"Error reading CSV: {e}")
            return None
    
    def CheckFileModified(self):
        """
        Check if CSV file has been modified
        Returns: True if file is new/modified
        """
        try:
            current_modified_time = os.path.getmtime(self.csv_file_path)
            if current_modified_time > self.last_modified_time:
                self.last_modified_time = current_modified_time
                return True
            return False
        except:
            return False
    
    def SendChannelDataToKafka(self):
        """
        Read CSV and send channel data to Kafka
        """
        # Check if file has been updated
        if not self.CheckFileModified():
            print("CSV file not updated yet...")
            return
        
        # Read CSV data
        data_dict = self.ReadCSV()
        if data_dict is None:
            return
        
        # Extract timestamp from Date and Time
        try:
            date_str = data_dict.get('Date', '')
            time_str = data_dict.get('Time', '')
            timestamp_str = f"{date_str} {time_str}"
            timestamp = int(datetime.strptime(timestamp_str, "%Y/%m/%d %H:%M:%S").timestamp())
        except:
            timestamp = int(time())
        
        # Send data for each channel
        for ch_num in range(1, self.max_channels + 1):
            freq_key = f"Ch{ch_num}Freq"
            fdiff_key = f"Ch{ch_num}Fdiff"
            
            if freq_key in data_dict and fdiff_key in data_dict:
                try:
                    frequency = float(data_dict[freq_key])
                    freq_diff = float(data_dict[fdiff_key])
                    
                    # Prepare data payload
                    channel_data = {
                        "timestamp": timestamp,
                        "channel": ch_num,
                        "frequency": frequency,
                        "freq_diff": freq_diff,
                        "date": data_dict.get('Date', ''),
                        "time": data_dict.get('Time', '')
                    }
                    
                    # Change device name for each channel
                    self.producer.ChangeDevice(f"MagneticField_CH{ch_num}")
                    
                    # Send to Kafka
                    self.producer.Send(channel_data)
                    print(f"CH{ch_num}: Freq={frequency}, Fdiff={freq_diff}")
                    
                except ValueError as e:
                    print(f"Error parsing CH{ch_num} data: {e}")
                    continue
        
        print(f"--- Data sent at {timestamp_str} ---\n")
    
    def Run(self):
        """
        Main loop: monitor CSV and send data
        """
        print(f"Starting Magnetic Field Operator...")
        print(f"Monitoring: {self.csv_file_path}")
        print(f"Sending CH1-CH{self.max_channels} data")
        print(f"Check interval: {self.waiting_time}s\n")
        
        while True:
            self.SendChannelDataToKafka()
            sleep(self.waiting_time)


if __name__ == "__main__":
    # CSVファイルのパスを指定
    CSV_PATH = "LastTrendData.csv"  # 適切なパスに変更してください
    
    # オペレーターの作成（CH1-CH4を送信）
    operator = MagneticField_Operator(
        csv_file_path=CSV_PATH,
        waiting_time=3,  # 3秒ごとにチェック
        max_channels=4   # CH1-CH4を送信（将来的に8まで増やせる）
    )
    
    # 実行
    operator.Run()