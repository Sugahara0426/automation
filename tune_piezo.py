import time
import vna_tools


def tune_piezo(atc, znb, target_f0, freq_per_step,
               mode="TM110", tolerance_khz=1, max_iterations=50):
    """
    Piezoを動かして共鳴周波数を目標値に合わせる。

    Parameters
    ----------
    atc : ANC350 controller
        Piezoを制御するANC350のオブジェクト

    znb : VNA resource
        VNAのオブジェクト

    target_f0 : float [GHz]
        目標の共鳴周波数

    freq_per_step : float [Hz/step]
        Piezoを1 step動かしたときの共鳴周波数の変化量
        例：+1 stepで周波数が2.5 kHz下がる
            → -2500 [Hz/step]

    mode : str
        "TM110" または "TM210"

    tolerance_khz : float [kHz]
        目標周波数に対する許容範囲

    max_iterations : int
        最大調整回数
    """


    # モードごとのVNA設定
    mode = mode.upper()

    if mode == "TM110":
        ch = 2
        trace = "Trc4"

    elif mode == "TM210":
        ch = 4
        trace = "Trc9"

    else:
        raise ValueError(f"Unknown mode: {mode}")

    print("\n================================")
    print("Piezo Frequency Tuning")
    print("================================")
    print(f"Mode            : {mode}")
    print(f"Target          : {target_f0:.9f} GHz")
    print(f"Freq/step       : {freq_per_step:+.1f} Hz/step")
    print(f"Tolerance       : ±{tolerance_khz:.1f} kHz")
    print(f"Max iterations  : {max_iterations}")


    # チューニング開始
    for i in range(1, max_iterations + 1):

        # VNAから共鳴周波数を取得
        f0_hz = vna_tools.find_min_freq(
            znb,
            ch,
            trace,
            threshold=0.5
        )

        if f0_hz is None:
            print("\n共鳴周波数が見つかりませんでした。")
            return None

        # Hz → GHz
        f0 = f0_hz / 1e9

        # 目標周波数との差
        # target_f0 : GHz
        # f0        : GHz
        # error_khz : kHz

        error_khz = (target_f0 - f0) * 1e6

        print(f"\n--- Tuning {i} ---")
        print(f"Current : {f0:.9f} GHz")
        print(f"Target  : {target_f0:.9f} GHz")
        print(f"Error   : {error_khz:+.3f} kHz")

        # 目標 ± tolerance_khz に入ったら終了

        if abs(error_khz) <= tolerance_khz:
            print("\nTarget frequency reached.")
            return f0

        # 必要なpiezo step数を計算
        error_hz = error_khz * 1000  # kHz → Hz

        required_steps = error_hz / freq_per_step

        move_steps = round(required_steps)

        # 0 stepになった場合

        if move_steps == 0:
            move_steps = 1 if required_steps > 0 else -1

        print(f"Move    : {move_steps:+d} steps")

        # piezoを動かす

        atc.move_by_steps(
            1,
            move_steps,
            0.01
        )

        # piezo移動後、少し待つ
        time.sleep(0.1)

    # 最大回数に到達
    print("\nMaximum iterations reached.")

    return f0
