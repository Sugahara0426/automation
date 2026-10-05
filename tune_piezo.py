import time
import vna_tools


MODE_CONFIG = {
    "TM110": {
        "axis": 1,
        "ch": 2,
        "trace": "Trc4",
        "initial_position": 0.007,　#初期位置ここで設定
    },
    "TM210": {
        "axis": 2,
        "ch": 4,
        "trace": "Trc9",
        "initial_position": None,  # TM210の初期位置が決まったら設定
    },
}


def get_resonance_frequency(znb, ch, trace):
    """
    VNAから共鳴周波数を取得する。

    Returns
    -------
    float or None
        共鳴周波数 [Hz]
    """
    result = vna_tools.find_min_freq(
        znb,
        ch,
        trace,
        threshold=0.5,
    )

    if isinstance(result, tuple):
        return result[0]

    return result


def return_to_initial_position(
    atc,
    axis,
    initial_position,
    wait_time=0.1,
):
    """
    異常時にPiezoを指定した初期位置へ戻す。
    """
    print("\n================================")
    print("Returning Piezo to initial position")
    print("================================")

    if initial_position is None:
        print("WARNING: Initial position is not defined.")
        print("Piezo was NOT moved.")
        return

    print(f"Axis     : {axis}")
    print(f"Position : {initial_position}")

    try:
        atc.move_to(axis, initial_position)
        time.sleep(wait_time)
        print("Piezo returned to initial position.")

    except Exception as e:
        print("\nERROR: Failed to return Piezo to initial position.")
        print(e)


def tune_piezo(
    atc,
    znb,
    target_f0,
    mode="TM110",
    tolerance_khz=50.0,
    max_iterations=50,
    wait_time=0.1,
    probe_steps=50,
    save_callback=None,
):
    """
    Piezoを動かして共鳴周波数を目標値に合わせる。

    tune開始時にPiezoを少し動かし、
    実際の周波数変化からfreq_per_step [Hz/step]を求める。

    Feedback中も、実際のPiezo移動量と周波数変化から
    freq_per_stepを更新する。

    共鳴周波数が見つからなくなった場合は、
    指定した初期位置へPiezoを戻して終了する。
    """

    mode = mode.upper()

    if mode not in MODE_CONFIG:
        raise ValueError(f"Unknown mode: {mode}")

    config = MODE_CONFIG[mode]

    axis = config["axis"]
    ch = config["ch"]
    trace = config["trace"]
    initial_position = config["initial_position"]

    print("\n================================")
    print("Piezo Frequency Tuning")
    print("================================")
    print(f"Mode           : {mode}")
    print(f"Axis           : {axis}")
    print(f"VNA channel    : {ch}")
    print(f"Trace          : {trace}")
    print(f"Target         : {target_f0:.9f} GHz")
    print(f"Tolerance      : ±{tolerance_khz:.3f} kHz")
    print(f"Probe steps    : {probe_steps}")
    print(f"Max iterations : {max_iterations}")

    # 初期共鳴周波数を取得
    f_before_hz = get_resonance_frequency(znb, ch, trace)

    if f_before_hz is None:
        print("\nERROR: 初期共鳴周波数が見つかりませんでした。")
        print("Resonance may be outside the VNA range.")

        return_to_initial_position(
            atc,
            axis,
            initial_position,
            wait_time,
        )
        return None

    # Piezo応答測定
    print("\n================================")
    print("Measuring Piezo response")
    print("================================")
    print(f"Before     : {f_before_hz / 1e9:.9f} GHz")
    print(f"Probe move : {probe_steps:+d} steps")

    atc.move_by_steps(axis, probe_steps, 0.01)
    time.sleep(wait_time)

    # Probe後の共鳴周波数を取得
    f_after_hz = get_resonance_frequency(znb, ch, trace)

    if f_after_hz is None:
        print("\nERROR: Probe移動後の共鳴周波数が見つかりませんでした。")
        print("Resonance may be outside the VNA range.")

        return_to_initial_position(
            atc,
            axis,
            initial_position,
            wait_time,
        )
        return None

    print(f"After      : {f_after_hz / 1e9:.9f} GHz")

    # 実測傾きを計算
    delta_f_hz = f_after_hz - f_before_hz
    freq_per_step = delta_f_hz / probe_steps

    print(f"Delta f    : {delta_f_hz / 1e3:+.3f} kHz")
    print(f"Freq/step  : {freq_per_step:+.3f} Hz/step")

    if abs(freq_per_step) < 1.0:
        print("\nERROR: Piezo response is too small.")
        print("Feedback tuning was stopped.")

        return_to_initial_position(
            atc,
            axis,
            initial_position,
            wait_time,
        )
        return None

    # Probe後の位置からFeedback開始
    f0_hz = f_after_hz

    previous_f0_hz = None
    previous_move_steps = None

    for i in range(1, max_iterations + 1):

        # Tuning 2以降は共鳴周波数を再測定
        if i > 1:
            f0_hz = get_resonance_frequency(znb, ch, trace)

            if f0_hz is None:
                print("\nERROR: 共鳴周波数が見つかりませんでした。")
                print("Resonance may be outside the VNA range.")

                return_to_initial_position(
                    atc,
                    axis,
                    initial_position,
                    wait_time,
                )
                return None

            # 前回の移動結果から傾きを更新
            if (
                previous_f0_hz is not None
                and previous_move_steps is not None
                and previous_move_steps != 0
            ):
                measured_delta_f = f0_hz - previous_f0_hz
                new_freq_per_step = (
                    measured_delta_f / previous_move_steps
                )

                if abs(new_freq_per_step) >= 1.0:
                    freq_per_step = new_freq_per_step

                    print(
                        f"\nUpdated freq/step : "
                        f"{freq_per_step:+.3f} Hz/step"
                    )
                else:
                    print(
                        "\nWARNING: Measured Piezo response "
                        "was too small."
                    )
                    print(
                        "Previous freq/step will be used."
                    )

        # 誤差計算
        f0 = f0_hz / 1e9
        error_hz = target_f0 * 1e9 - f0_hz
        error_khz = error_hz / 1e3

        print(f"\n--- Tuning {i} ---")
        print(f"Current   : {f0:.9f} GHz")
        print(f"Target    : {target_f0:.9f} GHz")
        print(f"Error     : {error_khz:+.3f} kHz")
        print(f"Freq/step : {freq_per_step:+.3f} Hz/step")

        # 各TuningでVNAデータ + PNG保存
        if save_callback is not None:
            try:
                save_callback(
                    znb=znb,
                    mode=mode,
                    target_frequency=target_f0,
                    tuning_index=i,
                    current_frequency=f0,
                )

            except Exception as e:
                print("\nWARNING: VNA data saving failed.")
                print(e)

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

        print(f"Required : {required_steps:+.2f} steps")
        print(f"Move     : {move_steps:+d} steps")

        # 次回の傾き更新用に記録
        previous_f0_hz = f0_hz
        previous_move_steps = move_steps

        # Piezo移動
        atc.move_by_steps(axis, move_steps, 0.01)
        time.sleep(wait_time)

    print("\nWARNING: Maximum iterations reached.")
    print("Target frequency was not reached.")

    return None
