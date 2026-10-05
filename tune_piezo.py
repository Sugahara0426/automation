import time
import vna_tools


MODE_CONFIG = {
    "TM110": {
        "axis": 1,
        "ch": 2,
        "trace": "Trc4",

        # 1 stepあたりの周波数変化 [Hz/step]
        "freq_per_step": -1280,
    },

    "TM210": {
        "axis": 2,
        "ch": 4,
        "trace": "Trc9",

        # TM210は実測後に変更する
        "freq_per_step": -2500,
    },
}


def tune_piezo(
    atc,
    znb,
    target_f0,
    mode="TM110",
    tolerance_khz=50.0,
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
        目標周波数に到達した場合：
            最終共鳴周波数 [GHz]

        失敗した場合：
            None
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

    for i in range(1, max_iterations + 1):

        # 現在の共鳴周波数を取得
        result = vna_tools.find_min_freq(
            znb,
            ch,
            trace,
            threshold=0.5
        )

        # find_min_freq() は失敗時に
        # (None, None) を返す場合があるため対応
        if isinstance(result, tuple):
            f0_hz = result[0]
        else:
            f0_hz = result

        if f0_hz is None:

            print(
                "\nERROR: 共鳴周波数が見つかりませんでした。"
            )

            return None

        f0 = f0_hz / 1e9

        error_hz = (
            target_f0 * 1e9
            - f0_hz
        )

        error_khz = (
            error_hz / 1e3
        )

        print(f"\n--- Tuning {i} ---")
        print(f"Current : {f0:.9f} GHz")
        print(f"Target  : {target_f0:.9f} GHz")
        print(f"Error   : {error_khz:+.3f} kHz")


        # 許容範囲内なら終了
        if abs(error_khz) <= tolerance_khz:

            print(
                "\nTarget frequency reached."
            )

            print(
                f"Final frequency : "
                f"{f0:.9f} GHz"
            )

            return f0


        # 必要step数を計算
        required_steps = (
            error_hz
            / freq_per_step
        )

        move_steps = round(
            required_steps
        )

        # 誤差があるのにroundで0になった場合
        if move_steps == 0:

            move_steps = (
                1
                if required_steps > 0
                else -1
            )

        print(
            f"Required: "
            f"{required_steps:+.2f} steps"
        )

        print(
            f"Move    : "
            f"{move_steps:+d} steps"
        )

        # Piezo移動
        atc.move_by_steps(
            axis,
            move_steps,
            0.01
        )

        time.sleep(
            wait_time
        )


    # 最大回数まで合わせられなかった

    print(
        "\nWARNING: Maximum iterations reached."
    )

    print(
        "Target frequency was not reached."
    )

    return None
