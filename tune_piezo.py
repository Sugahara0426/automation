import time
import vna_tools


MODE_CONFIG = {
    "TM110": {
        "axis": 0,
        "ch": 2,
        "trace": "Trc4",

        # 1 stepあたりの周波数変化 [Hz/step]
        # 実測値に変更する
        "freq_per_step": -1280,
    },

    "TM210": {
        "axis": 1,
        "ch": 4,
        "trace": "Trc9",

        # 実測値に変更する
        "freq_per_step": -2500,
    },
}


def tune_piezo(
    atc,
    znb,
    target_f0,
    mode="TM110",
    tolerance_khz=1.0,
    max_iterations=50,
    wait_time=0.1,
):
    """
    Piezoを動かして共鳴周波数を目標値に合わせる。

    Parameters
    ----------
    atc :
        ANC350オブジェクト

    znb :
        VNAオブジェクト

    target_f0 : float
        目標共鳴周波数 [GHz]

    mode : str
        "TM110" または "TM210"

    tolerance_khz : float
        許容誤差 [kHz]

    max_iterations : int
        最大調整回数

    wait_time : float
        Piezo移動後の待ち時間 [s]

    Returns
    -------
    float or None
        最終的な共鳴周波数 [GHz]
    """

    mode = mode.upper()

    if mode not in MODE_CONFIG:
        raise ValueError(f"Unknown mode: {mode}")

    config = MODE_CONFIG[mode]

    axis = config["axis"]
    ch = config["ch"]
    trace = config["trace"]
    freq_per_step = config["freq_per_step"]

    print("\n================================")
    print("Piezo Frequency Tuning")
    print("================================")
    print(f"Mode           : {mode}")
    print(f"Axis           : {axis}")
    print(f"VNA channel    : {ch}")
    print(f"Trace          : {trace}")
    print(f"Target         : {target_f0:.9f} GHz")
    print(f"Freq/step      : {freq_per_step:+.3f} Hz/step")
    print(f"Tolerance      : ±{tolerance_khz:.3f} kHz")
    print(f"Max iterations : {max_iterations}")

    final_f0 = None

    for i in range(1, max_iterations + 1):

        # 現在の共鳴周波数を取得
        f0_hz = vna_tools.find_min_freq(
            znb,
            ch,
            trace,
            threshold=0.5
        )

        if f0_hz is None:
            print("\nERROR: 共鳴周波数が見つかりませんでした。")
            return None

        f0 = f0_hz / 1e9
        final_f0 = f0

        error_hz = target_f0 * 1e9 - f0_hz
        error_khz = error_hz / 1e3

        print(f"\n--- Tuning {i} ---")
        print(f"Current : {f0:.9f} GHz")
        print(f"Target  : {target_f0:.9f} GHz")
        print(f"Error   : {error_khz:+.3f} kHz")

        # 許容範囲内なら終了
        if abs(error_khz) <= tolerance_khz:

            print("\nTarget frequency reached.")
            print(f"Final frequency : {f0:.9f} GHz")

            return f0

        # 必要step数を計算
        required_steps = error_hz / freq_per_step
        move_steps = round(required_steps)

        if move_steps == 0:
            move_steps = 1 if required_steps > 0 else -1

        print(f"Required: {required_steps:+.2f} steps")
        print(f"Move    : {move_steps:+d} steps")

        # Piezo移動
        atc.move_by_steps(
            axis,
            move_steps,
            0.01
        )

        time.sleep(wait_time)

    print("\nWARNING: Maximum iterations reached.")

    if final_f0 is not None:
        print(f"Final frequency : {final_f0:.9f} GHz")

    return final_f0
