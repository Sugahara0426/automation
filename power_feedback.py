# ============================================================
# power_feedback.py
#
# Microwave Power Feedback Controller
#
# Power measurement:
#   NRP2 -> RaS_NRP2_Operator -> Kafka -> this module
#
# Control:
#   start()
#       -> SG frequency / initial power setting
#       -> RF ON
#       -> power feedback start
#
#   stop()
#       -> feedback stop
#       -> RF OFF
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
# Device / Kafka settings
# ============================================================

SG_IP = "192.168.12.229"

KAFKA_SERVER = "10.105.52.103:9092"
KAFKA_TOPIC = "testdb"

POWER_CHANNEL = "CH2"


# ============================================================
# Default feedback settings
# ============================================================

DEFAULT_KP = 330000.0
DEFAULT_KI = 150.0
DEFAULT_KD = 0.0

DEFAULT_INTERVAL = 1.0
DEFAULT_TARGET_POWER_W = 7e-6
DEFAULT_FILTER_WINDOW = 1

# 積分項に使う時間幅
INTEGRAL_WINDOW_TIME = 10.0


# ============================================================
# SG safety limits
# ============================================================

SG_MIN_POWER_DBM = -50.0
SG_MAX_POWER_DBM = 5.0


# ============================================================
# Unit conversion
# ============================================================

def dbm_to_w(dbm):
    return (10.0 ** (dbm / 10.0)) * 1e-3


def w_to_dbm(watt):

    if watt <= 0:
        return SG_MIN_POWER_DBM

    return 10.0 * np.log10(watt * 1000.0)


# ============================================================
# Controller
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

        # ----------------------------------------
        # Feedback parameters
        # ----------------------------------------

        self.kp = float(kp)
        self.ki = float(ki)
        self.kd = float(kd)

        self.interval = float(interval)
        self.target_power_w = float(target_power_w)
        self.filter_window = int(filter_window)

        # ----------------------------------------
        # Current states
        # ----------------------------------------

        self.frequency_ghz = None

        self.initial_sg_power_dbm = None
        self.current_sg_power_dbm = None

        self.measured_power_raw_w = None
        self.measured_power_filtered_w = None

        self.rf_on = False
        self.feedback_on = False

        # ----------------------------------------
        # Threads
        # ----------------------------------------

        self.stop_event = threading.Event()

        self.kafka_thread = None
        self.feedback_thread = None

        # Kafka -> feedback loop
        self.power_queue = queue.Queue()

        # ----------------------------------------
        # Devices
        # ----------------------------------------

        self.sg = RaS_SMB_100A(SG_IP)

        # ----------------------------------------
        # State lock
        # ----------------------------------------

        self.lock = threading.Lock()


    # ========================================================
    # Settings
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
            raise ValueError("interval must be > 0")

        with self.lock:
            self.interval = interval


    def set_target_power(self, target_power_w):

        target_power_w = float(target_power_w)

        if target_power_w <= 0:
            raise ValueError("target_power_w must be > 0")

        with self.lock:
            self.target_power_w = target_power_w


    def set_filter_window(self, filter_window):

        filter_window = int(filter_window)

        if filter_window < 1:
            raise ValueError(
                "filter_window must be >= 1"
            )

        with self.lock:
            self.filter_window = filter_window


    # ========================================================
    # Kafka reader
    # ========================================================

    def _kafka_reader(self):

        print("[PowerFeedback] Kafka reader started.")

        consumer = None

        try:

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

                        try:

                            if (
                                data.get("data_type")
                                != "microwave_power"
                            ):
                                continue

                            value = data["value"]

                            if (
                                value.get("channel")
                                != POWER_CHANNEL
                            ):
                                continue

                            power = float(
                                value["microwave_power"]
                            )

                        except (
                            KeyError,
                            TypeError,
                            ValueError,
                        ):
                            continue

                        # Queueには最新値だけ残したい
                        while not self.power_queue.empty():

                            try:
                                self.power_queue.get_nowait()

                            except queue.Empty:
                                break

                        self.power_queue.put(power)


        except Exception as e:

            print(
                "[PowerFeedback] "
                f"Kafka error: {e}"
            )

            self.stop_event.set()


        finally:

            if consumer is not None:

                try:
                    consumer.close()

                except Exception:
                    pass

            print("[PowerFeedback] Kafka reader stopped.")


    # ========================================================
    # PID calculation
    # ========================================================

    def _calculate_pid(
        self,
        target,
        measured,
        current_sg_power_dbm,
        prev_error,
        integral_buffer,
        dt,
    ):

        # ----------------------------------------
        # Error
        # ----------------------------------------

        error = target - measured


        # ----------------------------------------
        # Integral
        #
        # 現行仕様と同様、
        # 「直近10秒程度」の誤差のみ使用
        # ----------------------------------------

        integral_buffer.append(error)

        max_len = max(
            1,
            int(INTEGRAL_WINDOW_TIME / dt)
        )

        while len(integral_buffer) > max_len:
            integral_buffer.popleft()

        integral_sum = sum(integral_buffer)


        # ----------------------------------------
        # Derivative
        # ----------------------------------------

        derivative = error - prev_error


        # ----------------------------------------
        # Current SG power -> W
        # ----------------------------------------

        current_sg_power_w = dbm_to_w(
            current_sg_power_dbm
        )


        # ----------------------------------------
        # PID output
        # ----------------------------------------

        correction_w = (
            self.kp * error
            + self.ki * integral_sum
            + self.kd * derivative
        )


        new_sg_power_w = (
            current_sg_power_w
            + correction_w
        )


        # ----------------------------------------
        # W -> dBm
        # ----------------------------------------

        new_sg_power_dbm = w_to_dbm(
            new_sg_power_w
        )


        # ----------------------------------------
        # Safety limit
        # ----------------------------------------

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
            f"Waiting for Kafka {POWER_CHANNEL} power..."
        )

        prev_error = 0.0
        integral_buffer = deque()

        meas_buffer = deque(
            maxlen=max(1, self.filter_window)
        )


        # ----------------------------------------
        # Wait for first detector value
        # ----------------------------------------

        while not self.stop_event.is_set():

            try:

                power = self.power_queue.get(
                    timeout=2.0
                )

            except queue.Empty:

                print(
                    "[PowerFeedback] "
                    "Waiting for detector data..."
                )

                continue


            if power is None:
                continue

            if power < 1e-12:
                continue

            # 最初のデータを次のloopでも使用
            self.power_queue.put(power)

            break


        if self.stop_event.is_set():
            return


        with self.lock:
            self.feedback_on = True


        print("[PowerFeedback] Feedback ON")


        # ========================================
        # Main feedback loop
        # ========================================

        while not self.stop_event.is_set():

            # ------------------------------------
            # Get latest power
            # ------------------------------------

            try:

                measured_raw = (
                    self.power_queue.get(
                        timeout=2.0
                    )
                )

            except queue.Empty:

                print(
                    "[PowerFeedback] "
                    "No power data."
                )

                continue


            # ------------------------------------
            # Safety check
            # ------------------------------------

            if measured_raw is None:
                continue

            if measured_raw < 1e-12:

                print(
                    "[PowerFeedback] "
                    "Power too low."
                )

                continue


            # ------------------------------------
            # Read current parameters
            # ------------------------------------

            with self.lock:

                interval = self.interval
                target = self.target_power_w

                filter_window = (
                    self.filter_window
                )

                current_sg_power_dbm = (
                    self.current_sg_power_dbm
                )


            # ------------------------------------
            # Filter window update
            # ------------------------------------

            filter_window = max(
                1,
                int(filter_window)
            )

            if meas_buffer.maxlen != filter_window:

                meas_buffer = deque(
                    meas_buffer,
                    maxlen=filter_window
                )


            # ------------------------------------
            # Median filter
            # ------------------------------------

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


            # ------------------------------------
            # PID
            # ------------------------------------

            new_sg_power_dbm, prev_error = (
                self._calculate_pid(
                    target=target,
                    measured=measured_filtered,
                    current_sg_power_dbm=
                        current_sg_power_dbm,
                    prev_error=prev_error,
                    integral_buffer=
                        integral_buffer,
                    dt=interval,
                )
            )


            # ------------------------------------
            # Set SG power
            # ------------------------------------

            try:

                self.sg.SetPower(
                    float(new_sg_power_dbm)
                )

            except Exception as e:

                print(
                    "[PowerFeedback] "
                    f"SG SetPower error: {e}"
                )

                self.stop_event.set()

                break


            # ------------------------------------
            # Update states
            # ------------------------------------

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


            print(
                "[PowerFeedback] "
                f"Raw={measured_raw:.3e} W | "
                f"Filtered={measured_filtered:.3e} W | "
                f"Target={target:.3e} W | "
                f"SG={new_sg_power_dbm:.3f} dBm"
            )


            time.sleep(interval)


        with self.lock:
            self.feedback_on = False


        print("[PowerFeedback] Feedback OFF")


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
        Microwave RF + Power feedback start.

        Sequence:

        1. Frequency setting
        2. Initial SG power setting
        3. RF ON
        4. Kafka power reader start
        5. Feedback start
        """

        if self.rf_on:

            print(
                "[PowerFeedback] "
                "Already running."
            )

            return False


        # ----------------------------------------
        # Inputs
        # ----------------------------------------

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


        # ----------------------------------------
        # Initial power safety limit
        # ----------------------------------------

        initial_sg_power_dbm = max(
            SG_MIN_POWER_DBM,
            min(
                SG_MAX_POWER_DBM,
                initial_sg_power_dbm
            )
        )


        print(
            "[PowerFeedback] "
            "Starting..."
        )


        # ----------------------------------------
        # Clear old Queue data
        # ----------------------------------------

        while not self.power_queue.empty():

            try:
                self.power_queue.get_nowait()

            except queue.Empty:
                break


        # ----------------------------------------
        # Reset stop event
        # ----------------------------------------

        self.stop_event.clear()


        # ----------------------------------------
        # Store state
        # ----------------------------------------

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


        # ----------------------------------------
        # SG Frequency
        # ----------------------------------------

        self.sg.SetFrequency(
            frequency_ghz * 1e9
        )


        # ----------------------------------------
        # Initial SG Power
        # ----------------------------------------

        self.sg.SetPower(
            float(initial_sg_power_dbm)
        )


        # ----------------------------------------
        # RF ON
        # ----------------------------------------

        self.sg.SetIO("ON")

        with self.lock:
            self.rf_on = True


        print(
            "[PowerFeedback] "
            f"RF ON | "
            f"{frequency_ghz:.9f} GHz | "
            f"{initial_sg_power_dbm:.2f} dBm"
        )


        # ----------------------------------------
        # Kafka reader
        # ----------------------------------------

        self.kafka_thread = threading.Thread(
            target=self._kafka_reader,
            daemon=True,
        )


        # ----------------------------------------
        # Feedback
        # ----------------------------------------

        self.feedback_thread = threading.Thread(
            target=self._feedback_loop,
            daemon=True,
        )


        self.kafka_thread.start()
        self.feedback_thread.start()


        return True


    # ========================================================
    # STOP
    # ========================================================

    def stop(self):
        """
        Sequence:

        1. Feedback stop
        2. Kafka reader stop
        3. RF OFF
        """

        print(
            "[PowerFeedback] "
            "Stopping..."
        )


        # ----------------------------------------
        # Stop threads
        # ----------------------------------------

        self.stop_event.set()


        if (
            self.feedback_thread is not None
            and self.feedback_thread.is_alive()
        ):

            self.feedback_thread.join(
                timeout=3
            )


        if (
            self.kafka_thread is not None
            and self.kafka_thread.is_alive()
        ):

            self.kafka_thread.join(
                timeout=3
            )


        # ----------------------------------------
        # RF OFF
        # ----------------------------------------

        try:

            self.sg.SetIO("OFF")

        except Exception as e:

            print(
                "[PowerFeedback] "
                f"RF OFF error: {e}"
            )


        # ----------------------------------------
        # State reset
        # ----------------------------------------

        with self.lock:

            self.rf_on = False
            self.feedback_on = False


        self.kafka_thread = None
        self.feedback_thread = None


        print(
            "[PowerFeedback] "
            "RF OFF"
        )


        return True


    # ========================================================
    # Status
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


    # ========================================================
    # Cleanup
    # ========================================================

    def close(self):

        if self.rf_on:
            self.stop()
