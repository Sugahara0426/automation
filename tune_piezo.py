import time
import vna_tools


MODE_CONFIG = {
    "TM110": {
        "axis": 1,
        "ch": 2,
        "trace": "Trc4",
        "initial_position": None,  # 初期位置が決まったら入力
    },

    "TM210": {
        "axis": 2,
        "ch": 4,
        "trace": "Trc9",
        "initial_position": None,  # 初期位置が決まったら入力
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
    """通知関数が設定されている場合だけ通知する。"""

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
    wait_time=1.0,
):
    """
    Piezoを初期位置へ戻し、
    get_position()で復帰確認する。

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
        print("WARNING: Initial position is not defined.")
        print("Piezo was NOT moved.")
        return False

    print(f"Axis            : {axis}")
    print(f"Target position : {initial_position}")

    try:
        atc.move_to(axis, initial_position)
        time.sleep(wait_time)

        current_position = atc.get_position(axis)
        position_error = abs(
            current_position - initial_position
        )

        print(f"Current position: {current_position}")
        print(f"Position error  : {position_error}")

        if position_error <= position_tolerance:
            print("Piezo returned to initial position.")
            return True

        print(
            "ERROR: Piezo did not reach "
            "the initial position."
        )

        return False

    except Exception as e:
        print(
            "ERROR: Failed to return Piezo "
            "to initial position."
        )
        print(e)

        return False


def handle_failure(
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
    異常を表示・通知し、
    Piezoを初期位置へ戻す。
    """

    print("\n================================")
    print("Frequency Tuning Failed")
    print("================================")
    print(f"Mode   : {mode}")
    print(f"Reason : {reason}")

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

    if recovered:

        notify(
            notify_callback,
            (
                f"ℹ️ {mode} Piezo Recovery Completed\n"
                f"Piezo returned to the initial position."
            ),
        )

    else:

        print(
            "WARNING: Piezo recovery failed. "
            "Manual check may be required."
        )

        notify(
            notify_callback,
            (
                f"🚨 {mode} Piezo Recovery Failed\n"
                f"Could not return to the initial position.\n"
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

    +step方向なら slope_plus、
    -step方向なら slope_minus を使用する。

    Returns
    -------
    tuple
        slope, required_steps

        使用可能な方向がない場合：
        None, None
    """

    candidates = []

    # +step方向
    if slope_plus != 0:

        required_plus = (
            error_hz / slope_plus
        )

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

        required_minus = (
            error_hz / slope_minus
        )

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

    # 両方向が使える場合は
    # 必要step数が少ない方を選択
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
    tolerance_khz=10.0,
    max_iterations=5,
    wait_time=1.0,
    probe_steps=10,
    position_tolerance=0.0005,
    save_callback=None,
    notify_callback=None,
):
    """
    Piezoを動かして共鳴周波数を目標値に合わせる。

    流れ
    ----
    1. 現在の共鳴周波数を確認
    2. 見つからなければ初期位置へ戻して再確認
    3. +10 stepして共鳴周波数を測定
    4. そこから-10 stepして共鳴周波数を測定
    5. 正方向・負方向それぞれの傾きを計算
    6. その傾きを使ってFeedback
    7. 各TuningでVNAデータ + PNG保存
    8. 異常時は初期位置へ戻して終了
    9. 成功・失敗時に通知可能
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
    # 最初の共鳴周波数を確認
    # ========================================================

    f_start_hz = get_resonance_frequency(
        znb,
        ch,
        trace,
    )

    # 最初から共鳴が見つからない場合
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
                    f"🚨 {mode} Frequency Tuning Failed\n"
                    f"Initial resonance was not found and "
                    f"Piezo recovery failed.\n"
                    f"Manual check required."
                ),
            )

            return None

        # 初期位置で再確認
        f_start_hz = get_resonance_frequency(
            znb,
            ch,
            trace,
        )

        if f_start_hz is None:

            print(
                "ERROR: Resonance was not found "
                "even at the initial position."
            )

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
    # +step方向の傾きを取得
    # ========================================================

    print("\n================================")
    print("Measuring Piezo slopes")
    print("================================")

    print(
        f"Start       : "
        f"{f_start_hz / 1e9:.9f} GHz"
    )

    print(
        f"Move        : "
        f"+{probe_steps} steps"
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

        handle_failure(
            atc=atc,
            axis=axis,
            initial_position=initial_position,
            mode=mode,
            reason=(
                "Resonance lost during "
                "+step slope measurement."
            ),
            notify_callback=notify_callback,
            position_tolerance=position_tolerance,
            wait_time=wait_time,
        )

        return None

    slope_plus = (
        f_plus_hz - f_start_hz
    ) / probe_steps

    print(
        f"After +{probe_steps:<3}: "
        f"{f_plus_hz / 1e9:.9f} GHz"
    )

    print(
        f"Slope +     : "
        f"{slope_plus:+.3f} Hz/step"
    )

    # ========================================================
    # そこから-step方向の傾きを取得
    # ========================================================

    print(
        f"\nMove        : "
        f"-{probe_steps} steps"
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

        handle_failure(
            atc=atc,
            axis=axis,
            initial_position=initial_position,
            mode=mode,
            reason=(
                "Resonance lost during "
                "-step slope measurement."
            ),
            notify_callback=notify_callback,
            position_tolerance=position_tolerance,
            wait_time=wait_time,
        )

        return None

    slope_minus = (
        f_minus_hz - f_plus_hz
    ) / (-probe_steps)

    print(
        f"After -{probe_steps:<3}: "
        f"{f_minus_hz / 1e9:.9f} GHz"
    )

    print(
        f"Slope -     : "
        f"{slope_minus:+.3f} Hz/step"
    )

    # ========================================================
    # 傾きが小さすぎる場合
    # ========================================================

    if (
        abs(slope_plus) < 1.0
        or abs(slope_minus) < 1.0
    ):

        handle_failure(
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

    print("\n================================")
    print("Slope measurement finished")
    print("================================")
    print(
        f"Slope + : "
        f"{slope_plus:+.3f} Hz/step"
    )
    print(
        f"Slope - : "
        f"{slope_minus:+.3f} Hz/step"
    )

    # -10 step後の位置からFeedback開始
    f0_hz = f_minus_hz

    # ========================================================
    # Feedback
    # ========================================================

    for i in range(
        1,
        max_iterations + 1,
    ):

        # Tuning 2以降はVNAで再測定
        if i > 1:

            f0_hz = get_resonance_frequency(
                znb,
                ch,
                trace,
            )

            if f0_hz is None:

                handle_failure(
                    atc=atc,
                    axis=axis,
                    initial_position=initial_position,
                    mode=mode,
                    reason=(
                        "Resonance lost during feedback."
                    ),
                    notify_callback=notify_callback,
                    position_tolerance=position_tolerance,
                    wait_time=wait_time,
                )

                return None

        # ====================================================
        # 誤差計算
        # ====================================================

        f0 = (
            f0_hz / 1e9
        )

        error_hz = (
            target_f0 * 1e9
            - f0_hz
        )

        error_khz = (
            error_hz / 1e3
        )

        print(
            f"\n--- Tuning {i} ---"
        )

        print(
            f"Current : "
            f"{f0:.9f} GHz"
        )

        print(
            f"Target  : "
            f"{target_f0:.9f} GHz"
        )

        print(
            f"Error   : "
            f"{error_khz:+.3f} kHz"
        )

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
                    "\nWARNING: "
                    "VNA data saving failed."
                )

                print(e)

        # ====================================================
        # 調整完了
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
        # 使用する傾きとstep数を決定
        # ====================================================

        slope, required_steps = (
            choose_feedback_slope(
                error_hz,
                slope_plus,
                slope_minus,
            )
        )

        if slope is None:

            handle_failure(
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

        # ====================================================
        # Piezo移動
        # ====================================================

        atc.move_by_steps(
            axis,
            move_steps,
            0.01,
        )

        time.sleep(wait_time)

    # ========================================================
    # 最大回数まで到達
    # ========================================================

    handle_failure(
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
