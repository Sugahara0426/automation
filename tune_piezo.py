import time
import vna_tools


MODE_CONFIG = {
    "TM110": {
        "axis": 1,
        "ch": 2,
        "trace": "Trc4",
        "initial_position": None,  # 決まったら入力
    },
    "TM210": {
        "axis": 2,
        "ch": 4,
        "trace": "Trc9",
        "initial_position": None,  # 決まったら入力
    },
}


def get_resonance_frequency(znb, ch, trace):
    """VNAから共鳴周波数 [Hz] を取得する。"""

    result = vna_tools.find_min_freq(
        znb,
        ch,
        trace,
        threshold=0.5,
    )

    if isinstance(result, tuple):
        return result[0]

    return result


def notify(notify_callback, message):
    """通知関数が指定されていれば通知する。"""

    if notify_callback is None:
        return

    try:
        notify_callback(message)
    except Exception as e:
        print(f"WARNING: Notification failed: {e}")


def return_to_initial_position(
    atc,
    axis,
    initial_position,
    position_tolerance=0.0005,
    wait_time=0.1,
):
    """
    Piezoを初期位置へ戻し、get_position()で復帰確認する。

    Returns
    -------
    bool
        復帰成功 : True
        復帰失敗 : False
    """

    print("\n================================")
    print("Returning Piezo to initial position")
    print("================================")

    if initial_position is None:
        print("ERROR: Initial position is not defined.")
        return False

    print(f"Axis            : {axis}")
    print(f"Target position : {initial_position}")

    try:
        atc.move_to(axis, initial_position)
        time.sleep(wait_time)

        current_position = atc.get_position(axis)

        print(f"Current position: {current_position}")

        position_error = abs(
            current_position - initial_position
        )

        if position_error <= position_tolerance:
            print("Piezo returned to initial position.")
            return True

        print(
            "ERROR: Piezo did not reach "
            "the initial position."
        )
        print(
            f"Position error: {position_error}"
        )

        return False

    except Exception as e:
        print(
            "ERROR: Failed to return Piezo "
            "to initial position."
        )
        print(e)
        return False


def recover_and_notify(
    atc,
    axis,
    initial_position,
    mode,
    reason,
    notify_callback,
    position_tolerance,
    wait_time,
):
    """
    異常通知を送り、初期位置へ戻す。
    復帰に失敗した場合は追加通知する。
    """

    print(f"\nERROR: {reason}")

    notify(
        notify_callback,
        (
            f"⚠️ {mode} Frequency Tuning Failed\n"
            f"Reason: {reason}\n"
            f"Returning Piezo to initial position."
        ),
    )

    recovered = return_to_initial_position(
        atc=atc,
        axis=axis,
        initial_position=initial_position,
        position_tolerance=position_tolerance,
        wait_time=wait_time,
    )

    if not recovered:
        notify(
            notify_callback,
            (
                f"🚨 {mode} Piezo Recovery Failed\n"
                f"Could not return to initial position.\n"
                f"Manual check required."
            ),
        )

    return recovered


def choose_feedback_slope(
    error_hz,
    slope_plus,
    slope_minus,
):
    """
    目標方向へ動ける傾きを選択する。

    Returns
    -------
    tuple
        (slope, required_steps)

        使用可能な方向がない場合：
        (None, None)
    """

    candidates = []

    # +step方向
    if slope_plus != 0:
        required_plus = error_hz / slope_plus

        if required_plus > 0:
            candidates.append(
                (
                    abs(required_plus),
                    slope_plus,
                    required_plus,
                )
            )

    # -step方向
    if slope_minus != 0:
        required_minus = error_hz / slope_minus

        if required_minus < 0:
            candidates.append(
                (
                    abs(required_minus),
                    slope_minus,
                    required_minus,
                )
            )

    if not candidates:
        return None, None

    # 必要step数が少ない方を採用
    _, slope, required_steps = min(
        candidates,
        key=lambda x: x[0],
    )

    return slope, required_steps


def tune_piezo(
    atc,
    znb,
    target_f0,
    mode="TM110",
    tolerance_khz=50.0,
    max_iterations=50,
    wait_time=0.1,
    probe_steps=10,
    position_tolerance=0.0005,
    save_callback=None,
    notify_callback=None,
):
    """
    Piezoを動かして共鳴周波数を目標値に合わせる。

    1. 現在の共鳴周波数を確認
    2. 共鳴が見つからなければ初期位置へ復帰
    3. +10 step と -10 step で正負方向の傾きを測定
    4. 測定した傾きを使ってFeedback
    5. 各TuningでVNAデータ・PNGを保存
    6. 異常時はSlack通知し初期位置へ復帰
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
    print(f"Probe steps    : ±{probe_steps}")
    print(f"Max iterations : {max_iterations}")

    # ========================================================
    # 初期共鳴周波数
    # ========================================================

    f_start_hz = get_resonance_frequency(
        znb,
        ch,
        trace,
    )

    # 最初から共鳴が見つからなければ初期位置へ戻す
    if f_start_hz is None:

        print(
            "\nInitial resonance was not found."
        )

        recovered = return_to_initial_position(
            atc=atc,
            axis=axis,
            initial_position=initial_position,
            position_tolerance=position_tolerance,
            wait_time=wait_time,
        )

        if not recovered:
            notify(
                notify_callback,
                (
                    f"🚨 {mode} Initial Recovery Failed\n"
                    f"Initial resonance was not found and "
                    f"Piezo could not return to initial position.\n"
                    f"Manual check required."
                ),
            )
            return None

        # 初期位置で再測定
        f_start_hz = get_resonance_frequency(
            znb,
            ch,
            trace,
        )

        if f_start_hz is None:
            notify(
                notify_callback,
                (
                    f"⚠️ {mode} Frequency Tuning Failed\n"
                    f"Resonance was not found even after "
                    f"returning to the initial position."
                ),
            )
            return None

    # ========================================================
    # +10 step方向の傾き
    # ========================================================

    print("\n================================")
    print("Measuring Piezo slopes")
    print("================================")

    print(
        f"Start  : {f_start_hz / 1e9:.9f} GHz"
    )

    print(
        f"Move   : +{probe_steps} steps"
    )

    atc.move_by_steps(
        axis,
        probe_steps,
        0.01,
    )

    time.sleep(wait_time)

    f_plus_hz = get_resonance_frequency(
        znb,
        ch,
        trace,
    )

    if f_plus_hz is None:
        recover_and_notify(
            atc=atc,
            axis=axis,
            initial_position=initial_position,
            mode=mode,
            reason="Resonance lost during +step slope measurement.",
            notify_callback=notify_callback,
            position_tolerance=position_tolerance,
            wait_time=wait_time,
        )
        return None

    slope_plus = (
        f_plus_hz - f_start_hz
    ) / probe_steps

    print(
        f"After +{probe_steps}: "
        f"{f_plus_hz / 1e9:.9f} GHz"
    )

    print(
        f"Slope + : "
        f"{slope_plus:+.3f} Hz/step"
    )

    # ========================================================
    # そこから -10 step方向の傾き
    # ========================================================

    print(
        f"\nMove   : -{probe_steps} steps"
    )

    atc.move_by_steps(
        axis,
        -probe_steps,
        0.01,
    )

    time.sleep(wait_time)

    f_minus_hz = get_resonance_frequency(
        znb,
        ch,
        trace,
    )

    if f_minus_hz is None:
        recover_and_notify(
            atc=atc,
            axis=axis,
            initial_position=initial_position,
            mode=mode,
            reason="Resonance lost during -step slope measurement.",
            notify_callback=notify_callback,
            position_tolerance=position_tolerance,
            wait_time=wait_time,
        )
        return None

    slope_minus = (
        f_minus_hz - f_plus_hz
    ) / (-probe_steps)

    print(
        f"After -{probe_steps}: "
        f"{f_minus_hz / 1e9:.9f} GHz"
    )

    print(
        f"Slope - : "
        f"{slope_minus:+.3f} Hz/step"
    )

    # 傾きがほぼ0ならFeedbackに使えない
    if abs(slope_plus) < 1.0 or abs(slope_minus) < 1.0:

        recover_and_notify(
            atc=atc,
            axis=axis,
            initial_position=initial_position,
            mode=mode,
            reason=(
                "Measured Piezo slope is too small. "
                f"slope_plus={slope_plus:+.3f}, "
                f"slope_minus={slope_minus:+.3f} Hz/step"
            ),
            notify_callback=notify_callback,
            position_tolerance=position_tolerance,
            wait_time=wait_time,
        )

        return None

    # -10後の位置をFeedback開始位置として使う
    f0_hz = f_minus_hz

    # ========================================================
    # Feedback
    # ========================================================

    for i in range(
        1,
        max_iterations + 1,
    ):

        # Tuning 2以降は再測定
        if i > 1:
            f0_hz = get_resonance_frequency(
                znb,
                ch,
                trace,
            )

            if f0_hz is None:
                recover_and_notify(
                    atc=atc,
                    axis=axis,
                    initial_position=initial_position,
                    mode=mode,
                    reason="Resonance lost during feedback.",
                    notify_callback=notify_callback,
                    position_tolerance=position_tolerance,
                    wait_time=wait_time,
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

        # ====================================================
        # 各TuningでCSV + PNG保存
        # ====================================================

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
                print(
                    "\nWARNING: VNA data saving failed."
                )
                print(e)

        # ====================================================
        # 完了判定
        # ====================================================

        if abs(error_khz) <= tolerance_khz:

            print(
                "\nTarget frequency reached."
            )

            print(
                f"Final frequency : "
                f"{f0:.9f} GHz"
            )

            notify(
                notify_callback,
                (
                    f"✅ {mode} Frequency Tuning Completed\n"
                    f"Target: {target_f0:.9f} GHz\n"
                    f"Final : {f0:.9f} GHz\n"
                    f"Error : {error_khz:+.3f} kHz"
                ),
            )

            return f0

        # ====================================================
        # 動かす方向に応じた傾きを選ぶ
        # ====================================================

        slope, required_steps = (
            choose_feedback_slope(
                error_hz,
                slope_plus,
                slope_minus,
            )
        )

        if slope is None:

            recover_and_notify(
                atc=atc,
                axis=axis,
                initial_position=initial_position,
                mode=mode,
                reason=(
                    "No valid feedback direction was found. "
                    f"Error={error_khz:+.3f} kHz, "
                    f"slope_plus={slope_plus:+.3f}, "
                    f"slope_minus={slope_minus:+.3f}"
                ),
                notify_callback=notify_callback,
                position_tolerance=position_tolerance,
                wait_time=wait_time,
            )

            return None

        move_steps = round(
            required_steps
        )

        if move_steps == 0:
            move_steps = (
                1
                if required_steps > 0
                else -1
            )

        print(
            f"Slope    : "
            f"{slope:+.3f} Hz/step"
        )

        print(
            f"Required : "
            f"{required_steps:+.2f} steps"
        )

        print(
            f"Move     : "
            f"{move_steps:+d} steps"
        )

        atc.move_by_steps(
            axis,
            move_steps,
            0.01,
        )

        time.sleep(wait_time)

    # ========================================================
    # 最大回数
    # ========================================================

    recover_and_notify(
        atc=atc,
        axis=axis,
        initial_position=initial_position,
        mode=mode,
        reason=(
            f"Maximum iterations reached "
            f"({max_iterations})."
        ),
        notify_callback=notify_callback,
        position_tolerance=position_tolerance,
        wait_time=wait_time,
    )

    return None
