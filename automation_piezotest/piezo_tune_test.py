import math
import time
import traceback
from importlib.metadata import PackageNotFoundError, version
import vna_tools


# ============================================================
# Mode設定
# ============================================================

# テスト専用。位置の単位はm、軸番号は0始まり。
# 2026-10-23にget_position()で取得した基準位置。
POSITION_TOLERANCE = 50e-6  # ±50 µm以内なら復帰移動を省略
REFERENCE_TIMEOUT = 30.0  # 復帰待ちの上限 [s]

MODE_CONFIG = {
    "TM110": {
        "axis": 1,
        "ch": 2,
        "trace": "Trc4",
        "initial_position": 0.007115193,  # 本体CH2 / axis 1
    },

    "TM210": {
        "axis": 2,
        "ch": 4,
        "trace": "Trc9",
        "initial_position": 0.004126160,  # 本体CH3 / axis 2
    },
}


# ============================================================
# 共鳴周波数取得
# ============================================================

def get_resonance_frequency(znb, ch, trace):
    """VNAから共鳴周波数 [Hz] を取得する。"""

    result = vna_tools.find_min_freq(
        znb,
        ch,
        trace,
        threshold=0.5,
    )

    # find_min_freq()が失敗時にtupleを返す場合への対応
    if isinstance(result, tuple):
        return result[0]

    return result


# ============================================================
# 通知
# ============================================================

def notify(notify_callback, message):
    """通知関数が設定されている場合だけ通知する。"""

    if notify_callback is None:
        return

    try:
        notify_callback(message)

    except Exception as e:
        print(f"WARNING: Notification failed: {e}")


# ============================================================
# 初期位置への復帰
# ============================================================

def return_to_initial_position(
    atc,
    axis,
    initial_position,
    position_tolerance=POSITION_TOLERANCE,
    wait_time=1.0,
    timeout=REFERENCE_TIMEOUT,
):
    """基準から許容差を超える場合だけ復帰し、停止・安定後の位置を確認する。

    位置・許容差はm。タイムアウトや通信エラー時はFalseを返す。
    移動を開始した場合は、例外・中断時もstop(axis)を試みる。
    """
    print("\nChecking Piezo reference position [software tolerance v2]", flush=True)
    try:
        print(f"pylablib version: {version('pylablib')}", flush=True)
    except PackageNotFoundError:
        print("pylablib version: package metadata not found", flush=True)
    print(f"Axis            : {axis}")
    print(f"Reference [m]   : {initial_position}")

    try:
        if initial_position is None or not math.isfinite(initial_position):
            raise ValueError("Reference position must be a finite value in m")
        if not math.isfinite(position_tolerance) or position_tolerance <= 0:
            raise ValueError("Position tolerance must be positive and finite")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Reference timeout must be positive and finite")
        if not math.isfinite(wait_time) or wait_time < 0:
            raise ValueError("Wait time must be non-negative and finite")

        print(f"[reference] get_position BEFORE: axis={axis}", flush=True)
        current_position = atc.get_position(axis)
        print(f"[reference] get_position OK: {current_position!r} m", flush=True)
        if not math.isfinite(current_position):
            raise ValueError("Invalid position readout")
        position_error = abs(current_position - initial_position)
        print(f"Current [m]     : {current_position}")
        print(f"Error [µm]      : {position_error * 1e6:.3f}")
        # 境界値での浮動小数点の丸め誤差だけを許容する。
        if position_error <= position_tolerance or math.isclose(
            position_error, position_tolerance, rel_tol=1e-9, abs_tol=0.0
        ):
            print("Within reference tolerance; no return move.")
            return True

        try:
            print(
                f"[reference] move_to BEFORE: axis={axis}, "
                f"position={initial_position!r} m (no device precision setting)",
                flush=True,
            )
            # precisionを指定するとset_precision()->get_precision(0x3036)が
            # 実行され、この実機ではinvalid addressになるため指定しない。
            deadline = time.monotonic() + timeout
            atc.move_to(axis, initial_position)
            print("[reference] move_to OK", flush=True)
            print(
                f"[reference] position polling: tolerance={position_tolerance * 1e6:.3f} µm, "
                f"timeout={timeout} s",
                flush=True,
            )
            # wait_move()も許容差レジスターを参照するので使用しない。
            # 動作実績のある位置読取だけで、ソフトウェア側で到達を判定する。
            last_report = -math.inf
            while True:
                current_position = atc.get_position(axis)
                if not math.isfinite(current_position):
                    raise ValueError("Invalid position readout during return")
                position_error = abs(current_position - initial_position)
                reached = position_error <= position_tolerance or math.isclose(
                    position_error, position_tolerance, rel_tol=1e-9, abs_tol=0.0
                )
                now = time.monotonic()
                if reached or now - last_report >= 1.0:
                    print(
                        f"[reference] position={current_position!r} m, "
                        f"error={position_error * 1e6:.3f} µm",
                        flush=True,
                    )
                    last_report = now
                if reached:
                    print("[reference] reference tolerance reached", flush=True)
                    break
                if now >= deadline:
                    raise TimeoutError(
                        f"Axis {axis} did not reach reference tolerance within {timeout} s; "
                        f"last error={position_error * 1e6:.3f} µm"
                    )
                time.sleep(min(0.1, deadline - now))
        finally:
            # 移動または到達待ちの失敗時にも停止を試みる。
            # 両方で失敗した場合も、下記tracebackに元の例外が残る。
            print(f"[reference] stop BEFORE: axis={axis}", flush=True)
            atc.stop(axis)
            print("[reference] stop OK", flush=True)

        print(f"[reference] settling: {wait_time} s", flush=True)
        time.sleep(wait_time)
        print(f"[reference] get_position AFTER: axis={axis}", flush=True)
        current_position = atc.get_position(axis)
        print(f"[reference] get_position OK: {current_position!r} m", flush=True)
        if not math.isfinite(current_position):
            raise ValueError("Invalid position readout after return")
        position_error = abs(current_position - initial_position)
        print(f"Returned [m]    : {current_position}")
        print(f"Error [µm]      : {position_error * 1e6:.3f}")
        if position_error <= position_tolerance or math.isclose(
            position_error, position_tolerance, rel_tol=1e-9, abs_tol=0.0
        ):
            return True
        print("ERROR: Piezo is outside reference tolerance after stopping.")
        return False

    except Exception as e:
        print(f"ERROR: Reference positioning failed on axis {axis}: {e}", flush=True)
        print("[reference] Full traceback follows:", flush=True)
        print(traceback.format_exc(), flush=True)
        return False


# ============================================================
# 異常処理
# ============================================================

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
    """異常を表示し、Piezoを初期位置へ戻す。"""

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


# ============================================================
# Feedback方向決定
# ============================================================

def choose_feedback_slope(
    residual_hz,
    slope_plus,
    slope_minus,
):
    """
    目標へ向かえるPiezo方向を選択する。

    Returns
    -------
    slope, required_steps

    使用可能な方向がなければ
    None, None
    """

    candidates = []

    # +step方向
    if slope_plus != 0:

        required_plus = residual_hz / slope_plus

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

        required_minus = residual_hz / slope_minus

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

    # 両方向が可能なら必要step数が小さい方
    _, slope, required_steps = min(
        candidates,
        key=lambda x: x[0],
    )

    return slope, required_steps


# ============================================================
# Frequency Tuning
# ============================================================

def tune_piezo(
    atc,
    znb,
    target_f0,
    mode="TM110",
    tolerance_khz=10.0,
    max_iterations=50,
    wait_time=1.0,
    probe_steps=10,
    position_tolerance=POSITION_TOLERANCE,
    save_callback=None,
    notify_callback=None,
):
    """
    Piezoを動かして共鳴周波数を目標値へ合わせる。

    target_f0 : GHz
    非調整軸を基準位置の±50 µm（既定値）へそろえた後、共鳴を測定する。
    調整軸は共鳴が見つかる限り現在位置から開始し、見つからなければ復帰して再測定。

    最終的に返す値は、
    最後に保存したVNAデータから求めた共鳴周波数 [GHz]。
    """

    mode = mode.upper()

    if mode not in MODE_CONFIG:
        raise ValueError(f"Unknown mode: {mode}")

    config = MODE_CONFIG[mode]

    axis = config["axis"]
    ch = config["ch"]
    trace = config["trace"]
    initial_position = config["initial_position"]
    fixed_mode = "TM210" if mode == "TM110" else "TM110"
    fixed_config = MODE_CONFIG[fixed_mode]

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
    # 最初の共鳴周波数（非調整軸を基準位置へそろえた後に測定）
    # ========================================================

    # 対応しない軸は先に基準へそろえる。失敗時は調整軸を動かさない。
    print(f"Fixed mode      : {fixed_mode}")
    print(f"Fixed axis      : {fixed_config['axis']}")
    print(f"Position tol.   : ±{position_tolerance * 1e6:.3f} µm")
    if not return_to_initial_position(
        atc=atc,
        axis=fixed_config["axis"],
        initial_position=fixed_config["initial_position"],
        position_tolerance=position_tolerance,
        wait_time=wait_time,
    ):
        notify(
            notify_callback,
            f"{mode} tuning cancelled: fixed axis {fixed_config['axis']} "
            "could not be placed at its reference. Manual check required.",
        )
        return None

    f_start_hz = get_resonance_frequency(
        znb,
        ch,
        trace,
    )

    # 共鳴が見つからない場合
    if f_start_hz is None:

        print("\nInitial resonance was not found.")

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

        # 初期位置へ戻った後でもう一度確認
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
    # Piezo slope測定
    # ========================================================

    print("\n================================")
    print("Measuring Piezo slopes")
    print("================================")

    print(
        f"Start       : "
        f"{f_start_hz / 1e9:.9f} GHz"
    )

    # --------------------------------------------------------
    # +step
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # -step
    # --------------------------------------------------------

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
    # 傾きチェック
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

    # -10 step後の値からFeedback開始
    f0_hz = f_minus_hz

    # ========================================================
    # Feedback
    # ========================================================

    for i in range(
        1,
        max_iterations + 1,
    ):

        # ----------------------------------------------------
        # Tuning 2以降は、まず共鳴が存在するか確認
        # ----------------------------------------------------

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

        f0 = f0_hz / 1e9

        print(
            f"\n--- Tuning {i} ---"
        )

        print(
            f"Pre-save current : "
            f"{f0:.9f} GHz"
        )

        # ====================================================
        # VNAデータ保存
        #
        # save_callback()が10回測定したデータから
        # 共鳴周波数 [GHz] を返す。
        # ====================================================

        if save_callback is not None:

            try:

                saved_f0 = save_callback(
                    znb=znb,
                    mode=mode,
                    target_frequency=target_f0,
                    tuning_index=i,
                    current_frequency=f0,
                )

                if saved_f0 is not None:

                    # 保存したグラフのResonanceを
                    # 正式なCurrentとして使用
                    f0 = saved_f0
                    f0_hz = f0 * 1e9

            except Exception as e:

                print(
                    "\nWARNING: "
                    "VNA data saving failed."
                )

                print(e)

        # ====================================================
        # 目標周波数に対する残差
        # ====================================================

        residual_hz = (
            target_f0 * 1e9
            - f0_hz
        )

        residual_khz = residual_hz / 1e3

        print(
            "\nFeedback frequency:"
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
            f"Residual: "
            f"{residual_khz:+.3f} kHz"
        )

        # ====================================================
        # 調整完了
        #
        # 最後に保存したグラフのResonanceを
        # final_f0として返す。
        # ====================================================

        if abs(residual_khz) <= tolerance_khz:

            print(
                "\nTarget frequency reached."
            )

            print("\n================================")
            print("Frequency Tuning Completed")
            print("================================")

            print(
                f"Target          : "
                f"{target_f0:.9f} GHz"
            )

            print(
                f"Final resonance : "
                f"{f0:.9f} GHz"
            )

            print(
                f"Final residual  : "
                f"{residual_khz:+.3f} kHz"
            )

            print(
                f"AMP frequency    : "
                f"{f0:.9f} GHz"
            )

            notify(
                notify_callback,
                (
                    f"✅ {mode} Frequency Tuning Completed\n"
                    f"Target: {target_f0:.9f} GHz\n"
                    f"Final resonance: {f0:.9f} GHz\n"
                    f"Residual: {residual_khz:+.3f} kHz"
                ),
            )

            return f0

        # ====================================================
        # Feedback方向とstep数
        # ====================================================

        slope, required_steps = choose_feedback_slope(
            residual_hz,
            slope_plus,
            slope_minus,
        )

        if slope is None:

            handle_failure(
                atc=atc,
                axis=axis,
                initial_position=initial_position,
                mode=mode,
                reason=(
                    "No valid feedback direction was found. "
                    f"Residual={residual_khz:+.3f} kHz, "
                    f"slope_plus={slope_plus:+.3f}, "
                    f"slope_minus={slope_minus:+.3f}"
                ),
                notify_callback=notify_callback,
                position_tolerance=position_tolerance,
                wait_time=wait_time,
            )

            return None

        move_steps = round(required_steps)

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
    # 最大回数到達
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
