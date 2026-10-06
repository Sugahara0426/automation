# ============================================================
# power_feedback.py
#
# Microwave Power Feedback Controller
#
# Power data:
#   NRP2
#     -> RaS_NRP2.py
#     -> RaS_NRP2_Operator.py
#     -> Kafka "testdb"
#     -> this module
#
# Usage:
#
#   from power_feedback import PowerFeedbackController
#
#   feedback = PowerFeedbackController()
#
#   feedback.start(
#       frequency_ghz=1.8974,
#       target_power_w=7e-6,
#       initial_sg_power_dbm=-30.0
#   )
#
#   feedback.stop()
#
# ============================================================

import json
import time
import queue
import threading
import statistics
from collections import deque

import numpy as np
from kafka import KafkaConsumer

from RaS_SMB_100A import RaS_SMB_100A


# ============================================================
# Device settings
# ============================================================

SG_IP = "192.168.12.229"


# ============================================================
# Kafka settings
# ============================================================

KAFKA_SERVER = "10.105.52.103:9092"
KAFKA_TOPIC = "testdb"

POWER_DEVICE = "RaS_NRP2"
POWER_DATA_TYPE = "microwave_power"
POWER_CHANNEL = "CH2"


# ============================================================
# Feedback default parameters
# ============================================================

DEFAULT_KP = 330000.0
DEFAULT_KI = 150.0
DEFAULT_KD = 0.0

DEFAULT_INTERVAL = 1.0
DEFAULT_TARGET_POWER_W = 7e-6
DEFAULT_FILTER_WINDOW = 1

# 積分項は直近10秒分
INTEGRAL_WINDOW_TIME = 10.0


# ============================================================
# SG power limits
# ============================================================

SG_MIN_POWER_DBM = -50.0
SG_MAX_POWER_DBM = 5.0


# ============================================================
# Unit conversion
# ============================================================

def dbm_to_w(dbm):
    """
    dBm -> W
    """
    return (10.0 ** (dbm / 10.0)) * 1e-3


def w_to_dbm(watt):
    """
    W -> dBm
    """

    if watt <= 0:
        return SG_MIN_POWER_DBM

    return 10.0 * np.log10(watt * 1000.0)


# ============================================================
# Power Feedback Controller
# ============================================================

class PowerFeedbackController:

    def __init__(
        self,
        kp=DEFAULT_KP,
        ki=DEFAULT_KI,
        kd=DEFAULT_KD,
        interval=DEFAULT_INTERVAL,
        target_power_w=DEFAULT_TARGET_POWER_W,
        filter_window=DEFAULT_FILTER_WINDOW,
    ):

        # ----------------------------------------------------
        # Feedback parameters
        # ----------------------------------------------------

        self.kp = float(kp)
        self.ki = float(ki)
        self.kd = float(kd)

        self.interval = float(interval)
        self.target_power_w = float(target_power_w)
        self.filter_window = int(filter_window)


        # ----------------------------------------------------
        # Current SG state
        # ----------------------------------------------------

        self.frequency_ghz = None

        self.initial_sg_power_dbm = None
        self.current_sg_power_dbm = None


        # ----------------------------------------------------
        # Current measured power
        # ----------------------------------------------------

        self.measured_power_raw_w = None
        self.measured_power_filtered_w = None


        # ----------------------------------------------------
        # State
        # ----------------------------------------------------

        self.rf_on = False
        self.feedback_on = False


        # ----------------------------------------------------
        # Thread control
        # ----------------------------------------------------

        self.stop_event = threading.Event()

        self.kafka_thread = None
        self.feedback_thread = None


        # Kafka -> Feedback data
        self.power_queue = queue.Queue()


        # ----------------------------------------------------
        # SG connection
        # ----------------------------------------------------

        self.sg = RaS_SMB_100A(SG_IP)


        # ----------------------------------------------------
        # Thread lock
        # ----------------------------------------------------

        self.lock = threading.Lock()


    # ========================================================
    # Parameter settings
    # ========================================================

    def set_pid(self, kp=None, ki=None, kd=None):

        with self.lock:

            if kp is not None:
                self.kp = float(kp)

            if ki is not None:
                self.ki = float(ki)

            if kd is not None:
                self.kd = float(kd)


    def set_interval(self, interval):

        interval = float(interval)

        if interval <= 0:
            interval = DEFAULT_INTERVAL

        with self.lock:
            self.interval = interval


    def set_target_power(self, target_power_w):

        with self.lock:
            self.target_power_w = float(target_power_w)


    def set_filter_window(self, filter_window):

        filter_window = int(filter_window)

        if filter_window < 1:
            filter_window = 1

        with self.lock:
            self.filter_window = filter_window


    # ========================================================
    # Kafka reader
    # ========================================================

    def _kafka_reader(self):

        print("[PowerFeedback] Kafka reader started")

        consumer = KafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=KAFKA_SERVER,
            value_deserializer=lambda m:
                json.loads(m.decode("utf-8")),
            auto_offset_reset="latest",
            enable_auto_commit=True,
        )


        while not self.stop_event.is_set():

            records = consumer.poll(
                timeout_ms=500
            )


            for _, messages in records.items():

                for msg in messages:

                    data = msg.value


                    # ----------------------------------------
                    # NRP2 microwave powerのみ
                    # ----------------------------------------

                    if (
                        data.get("device_name")
                        != POWER_DEVICE
                    ):
                        continue


                    if (
                        data.get("data_type")
                        != POWER_DATA_TYPE
                    ):
                        continue


                    value = data.get(
                        "value",
                        {}
                    )


                    if (
                        value.get("channel")
                        != POWER_CHANNEL
                    ):
                        continue


                    try:

                        power = float(
                            value["microwave_power"]
                        )

                    except (
                        KeyError,
                        TypeError,
                        ValueError
                    ):

                        continue


                    # ----------------------------------------
                    # 最新値だけ使いたいので
                    # 古いQueueデータを捨てる
                    # ----------------------------------------

                    while not self.power_queue.empty():

                        try:
                            self.power_queue.get_nowait()

                        except queue.Empty:
                            break


                    self.power_queue.put(power)


            time.sleep(0.01)


        consumer.close()

        print("[PowerFeedback] Kafka reader stopped")


    # ========================================================
    # PID calculation
    # ========================================================

    def _calculate_pid(
        self,
        target_power,
        measured_power,
        current_sg_power_dbm,
        prev_error,
        integral_buffer,
        dt,
    ):

        # ----------------------------------------------------
        # Error
        # ----------------------------------------------------

        error = (
            target_power
            - measured_power
        )


        # ----------------------------------------------------
        # Integral
        # ----------------------------------------------------

        integral_buffer.append(
            error
        )


        if dt <= 0:
            dt = DEFAULT_INTERVAL


        max_len = int(
            INTEGRAL_WINDOW_TIME
            / dt
        )


        if max_len < 1:
            max_len = 1


        while (
            len(integral_buffer)
            > max_len
        ):

            integral_buffer.popleft()


        integral_sum = sum(
            integral_buffer
        )


        # ----------------------------------------------------
        # Derivative
        # ----------------------------------------------------

        derivative = (
            error
            - prev_error
        )


        # ----------------------------------------------------
        # Current SG power
        #
        # dBm -> W
        # ----------------------------------------------------

        current_sg_power_w = dbm_to_w(
            current_sg_power_dbm
        )


        # ----------------------------------------------------
        # PID
        # ----------------------------------------------------

        output = (
            self.kp * error
            + self.ki * integral_sum
            + self.kd * derivative
        )


        new_sg_power_w = (
            current_sg_power_w
            + output
        )


        # ----------------------------------------------------
        # W -> dBm
        # ----------------------------------------------------

        new_sg_power_dbm = w_to_dbm(
            new_sg_power_w
        )


        # ----------------------------------------------------
        # SG power limit
        # ----------------------------------------------------

        new_sg_power_dbm = max(
            SG_MIN_POWER_DBM,
            min(
                SG_MAX_POWER_DBM,
                new_sg_power_dbm
            )
        )


        return (
            new_sg_power_dbm,
            error
        )


    # ========================================================
    # Feedback loop
    # ========================================================

    def _feedback_loop(self):

        print(
            "[PowerFeedback] "
            "Waiting for NRP2 CH2 data..."
        )


        prev_error = 0.0
        integral_buffer = deque()


        with self.lock:
            filter_window = self.filter_window


        meas_buffer = deque(
            maxlen=max(
                1,
                filter_window
            )
        )


        # ----------------------------------------------------
        # Main loop
        # ----------------------------------------------------

        with self.lock:
            self.feedback_on = True


        print(
            "[PowerFeedback] "
            "Feedback ON"
        )


        while not self.stop_event.is_set():

            # ----------------------------------------
            # Power取得
            # ----------------------------------------

            try:

                measured_raw = (
                    self.power_queue.get(
                        timeout=2.0
                    )
                )

            except queue.Empty:

                # 既存と同じくデータが来るまで待つ
                continue


            # ----------------------------------------
            # Power too low
            # ----------------------------------------

            if (
                measured_raw is None
                or measured_raw < 1e-12
            ):

                print(
                    "[PowerFeedback] "
                    "Power too low or missing"
                )

                continue


            # ----------------------------------------
            # Current parameters
            # ----------------------------------------

            with self.lock:

                target_power = (
                    self.target_power_w
                )

                interval = (
                    self.interval
                )

                filter_window = (
                    self.filter_window
                )

                current_sg_power_dbm = (
                    self.current_sg_power_dbm
                )


            if interval <= 0:
                interval = 0.1


            # ----------------------------------------
            # Median Filter
            # ----------------------------------------

            filter_window = max(
                1,
                int(filter_window)
            )


            if (
                meas_buffer.maxlen
                != filter_window
            ):

                meas_buffer = deque(
                    meas_buffer,
                    maxlen=filter_window
                )


            meas_buffer.append(
                measured_raw
            )


            if filter_window == 1:

                measured_filtered = (
                    measured_raw
                )

            else:

                measured_filtered = (
                    statistics.median(
                        meas_buffer
                    )
                )


            # ----------------------------------------
            # PID
            # ----------------------------------------

            (
                new_sg_power_dbm,
                prev_error
            ) = self._calculate_pid(

                target_power=
                    target_power,

                measured_power=
                    measured_filtered,

                current_sg_power_dbm=
                    current_sg_power_dbm,

                prev_error=
                    prev_error,

                integral_buffer=
                    integral_buffer,

                dt=
                    interval,
            )


            # ----------------------------------------
            # SG Power変更
            # ----------------------------------------

            self.sg.SetPower(
                float(
                    new_sg_power_dbm
                )
            )


            # ----------------------------------------
            # State update
            # ----------------------------------------

            with self.lock:

                self.current_sg_power_dbm = (
                    new_sg_power_dbm
                )

                self.measured_power_raw_w = (
                    measured_raw
                )

                self.measured_power_filtered_w = (
                    measured_filtered
                )


            # ----------------------------------------
            # Console output
            # ----------------------------------------

            print(
                "[PowerFeedback] "
                f"Raw={measured_raw:.3e} W | "
                f"Filtered={measured_filtered:.3e} W | "
                f"Target={target_power:.3e} W | "
                f"SG={new_sg_power_dbm:.3f} dBm"
            )


            time.sleep(
                interval
            )


        with self.lock:
            self.feedback_on = False


        print(
            "[PowerFeedback] "
            "Feedback OFF"
        )


    # ========================================================
    # START
    # ========================================================

    def start(
        self,
        frequency_ghz,
        target_power_w=None,
        initial_sg_power_dbm=-30.0,
    ):
        """
        Power Feedback開始

        Sequence:
            Frequency設定
            -> Initial SG Power設定
            -> RF ON
            -> Kafka CH2受信
            -> Feedback
        """


        if self.rf_on:

            print(
                "[PowerFeedback] "
                "Already running"
            )

            return


        frequency_ghz = float(
            frequency_ghz
        )

        initial_sg_power_dbm = float(
            initial_sg_power_dbm
        )


        if target_power_w is not None:

            self.set_target_power(
                target_power_w
            )


        # ----------------------------------------------------
        # Initial SG Power limit
        # ----------------------------------------------------

        initial_sg_power_dbm = max(
            SG_MIN_POWER_DBM,
            min(
                SG_MAX_POWER_DBM,
                initial_sg_power_dbm
            )
        )


        # ----------------------------------------------------
        # Queue clear
        # ----------------------------------------------------

        while not self.power_queue.empty():

            try:
                self.power_queue.get_nowait()

            except queue.Empty:
                break


        # ----------------------------------------------------
        # State
        # ----------------------------------------------------

        with self.lock:

            self.frequency_ghz = (
                frequency_ghz
            )

            self.initial_sg_power_dbm = (
                initial_sg_power_dbm
            )

            self.current_sg_power_dbm = (
                initial_sg_power_dbm
            )


        # ----------------------------------------------------
        # SG Frequency
        # ----------------------------------------------------

        self.sg.SetFrequency(
            frequency_ghz
            * 1e9
        )


        # ----------------------------------------------------
        # Initial SG Power
        # ----------------------------------------------------

        self.sg.SetPower(
            initial_sg_power_dbm
        )


        # ----------------------------------------------------
        # RF ON
        # ----------------------------------------------------

        self.sg.SetIO(
            "ON"
        )


        with self.lock:
            self.rf_on = True


        print(
            "[PowerFeedback] "
            f"RF ON | "
            f"{frequency_ghz:.9f} GHz | "
            f"{initial_sg_power_dbm:.2f} dBm"
        )


        # ----------------------------------------------------
        # Threads start
        # ----------------------------------------------------

        self.stop_event.clear()


        self.kafka_thread = threading.Thread(
            target=
                self._kafka_reader,
            daemon=True
        )


        self.feedback_thread = threading.Thread(
            target=
                self._feedback_loop,
            daemon=True
        )


        self.kafka_thread.start()
        self.feedback_thread.start()


    # ========================================================
    # STOP
    # ========================================================

    def stop(self):
        """
        Feedback停止
          -> RF OFF
        """


        if not self.rf_on:

            print(
                "[PowerFeedback] "
                "Already stopped"
            )

            return


        print(
            "[PowerFeedback] "
            "Stopping..."
        )


        # ----------------------------------------------------
        # Feedback / Kafka stop
        # ----------------------------------------------------

        self.stop_event.set()


        if (
            self.feedback_thread
            is not None
        ):

            self.feedback_thread.join(
                timeout=3
            )


        if (
            self.kafka_thread
            is not None
        ):

            self.kafka_thread.join(
                timeout=3
            )


        # ----------------------------------------------------
        # RF OFF
        # ----------------------------------------------------

        self.sg.SetIO(
            "OFF"
        )


        with self.lock:

            self.rf_on = False
            self.feedback_on = False


        self.feedback_thread = None
        self.kafka_thread = None


        print(
            "[PowerFeedback] "
            "RF OFF"
        )


    # ========================================================
    # Current status
    # ========================================================

    def get_status(self):

        with self.lock:

            return {

                "rf_on":
                    self.rf_on,

                "feedback_on":
                    self.feedback_on,

                "frequency_ghz":
                    self.frequency_ghz,

                "sg_power_dbm":
                    self.current_sg_power_dbm,

                "target_power_w":
                    self.target_power_w,

                "measured_power_raw_w":
                    self.measured_power_raw_w,

                "measured_power_filtered_w":
                    self.measured_power_filtered_w,

                "kp":
                    self.kp,

                "ki":
                    self.ki,

                "kd":
                    self.kd,

                "interval":
                    self.interval,

                "filter_window":
                    self.filter_window,
            }
