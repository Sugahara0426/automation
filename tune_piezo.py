import time
import csv
import os
from datetime import datetime

import find_resonance
import vna_tools


def tune_piezo(atc, znb, target_f0, freq_per_step,
               mode="TM110", tolerance_khz=1, max_iterations=50):

    # ログファイルの準備
    date_str = datetime.now().strftime("%Y%m%d")
    log_dir = f"data/{date_str}/tuning"
    os.makedirs(log_dir, exist_ok=True)

    start_time = datetime.now().strftime("%H%M%S")
    log_path = f"{log_dir}/{mode}_tuning_{start_time}.csv"

    with open(log_path, "w", newline="") as f:
        writer = csv.writer(f)

        writer.writerow([
            "Iteration",
            "Current_Frequency_GHz",
            "Target_Frequency_GHz",
            "Error_kHz",
            "Move_Steps"
        ])

    print(f"Tuning log : {log_path}")


    # チューニング開始
    for i in range(1, max_iterations + 1):

        # VNA測定
        csv_path = vna_tools.measure_and_save(
            znb,
            f"{mode}_tune{i}"
        )

        # 共鳴周波数を解析
        results = find_resonance.analyze(csv_path)

        if mode == "TM110":
            f0 = results["110_Narrow"]["f0"]

        elif mode == "TM210":
            f0 = results["210_Narrow"]["f0"]

        else:
            raise ValueError(f"Unknown mode: {mode}")

        # 目標周波数との差
        error_khz = (target_f0 - f0) * 1e6

        print(f"\n--- Tuning {i} ---")
        print(f"Current : {f0:.6f} GHz")
        print(f"Target  : {target_f0:.6f} GHz")
        print(f"Error   : {error_khz:+.3f} kHz")

        # 目標 ±1 kHz に入ったら終了
        if abs(error_khz) <= tolerance_khz:

            # 到達したこともログに残す
            with open(log_path, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    i,
                    f0,
                    target_f0,
                    error_khz,
                    0
                ])

            print("\nTarget frequency reached.")
            print(f"Tuning log saved : {log_path}")

            return f0


        # 必要なpiezo step数を計算
        required_steps = error_khz * 1000 / freq_per_step

        move_steps = round(required_steps)

        # 0 stepになった場合
        if move_steps == 0:
            move_steps = 1 if required_steps > 0 else -1

        print(f"Move    : {move_steps:+d} steps")

        # ログに保存
        with open(log_path, "a", newline="") as f:
            writer = csv.writer(f)

            writer.writerow([
                i,
                f0,
                target_f0,
                error_khz,
                move_steps
            ])

        # piezoを動かす
        atc.move_by_steps(
            1,
            move_steps,
            0.01
        )

        time.sleep(0.1)

    print("\nMaximum iterations reached.")
    print(f"Tuning log saved : {log_path}")

    return f0
