import piezo_tools
import vna_tools

# Mode設定
MODE_CONFIG = {
    "TM110": {
        "axis": 1,
        "ch": 2,
        "trace": "Trc4",
    },

    "TM210": {
        "axis": 2,
        "ch": 4,
        "trace": "Trc9",
    },
}

# 共鳴周波数取得
def get_resonance_frequency(znb, ch, trace):
    # VNAから共鳴周波数 [Hz] を取得する。
    result = vna_tools.find_min_freq(znb, ch, trace, threshold=0.5)

    # find_min_freq()が失敗時にtupleを返す場合への対応
    if isinstance(result, tuple):
        return result[0]

    return result

# 通知
def notify(notify_callback, message):
    # 通知関数が設定されている場合だけ通知する。
    if notify_callback is None:
        return

    try:
        notify_callback(message)
    except Exception as e:
        print(f"WARNING: Notification failed: {e}")

# 異常処理
def handle_failure(atc, axis, mode, reason, notify_callback, position_tolerance):
    # 異常を表示し、Piezoを初期位置へ戻す。
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

    try:
        recovered = piezo_tools.reset_position(atc, axes=(axis,), tolerance=position_tolerance)
    except Exception as e:
        print(f"ERROR: Piezo recovery failed: {e}")
        recovered = False

    if recovered:
        notify(
            notify_callback,
            (
                f"ℹ️ {mode} Piezo Recovery Completed\n"
                f"Piezo returned to the initial position."
            ),
        )
    else:
        print('WARNING: Piezo recovery failed. Manual check may be required.')

        notify(
            notify_callback,
            (
                f"🚨 {mode} Piezo Recovery Failed\n"
                f"Could not return to the initial position.\n"
                f"Manual check required."
            ),
        )

    return recovered

# Feedback方向決定
def choose_feedback_slope(residual_hz, slope_plus, slope_minus):
    # 目標へ向かえるPiezo方向を選択する。
    #
    # Returns
    # slope, required_steps
    #
    # 使用可能な方向がなければ
    # None, None
    candidates = []

    # +step方向
    if slope_plus != 0:
        required_plus = residual_hz / slope_plus

        if required_plus > 0:
            candidates.append((abs(required_plus), slope_plus, required_plus))

    # -step方向
    if slope_minus != 0:
        required_minus = residual_hz / slope_minus

        if required_minus < 0:
            candidates.append((abs(required_minus), slope_minus, required_minus))

    if not candidates:
        return None, None

    # 両方向が可能なら必要step数が小さい方
    _, slope, required_steps = min(candidates, key=lambda x: x[0])

    return slope, required_steps

# Frequency Tuning
def tune_piezo(
    atc,
    znb,
    target_f0,
    mode="TM110",
    tolerance_khz=10.0,
    max_iterations=10,
    wait_time=1.0,
    probe_steps=10,
    position_tolerance=50e-6,
    save_callback=None,
    notify_callback=None,
):
    # Piezoを動かして共鳴周波数を目標値へ合わせる。
    #
    # target_f0 : GHz
    #
    # 最終的に返す値は、
    # 最後に保存したVNAデータから求めた共鳴周波数 [GHz]。
    mode = mode.upper()

    if mode not in MODE_CONFIG:
        raise ValueError(f"Unknown mode: {mode}")

    config = MODE_CONFIG[mode]
    axis = config["axis"]
    ch = config["ch"]
    trace = config["trace"]

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

    # 最初の共鳴周波数
    f_start_hz = get_resonance_frequency(znb, ch, trace)

    # 共鳴が見つからない場合
    if f_start_hz is None:
        print("\nInitial resonance was not found.")

        try:
            recovered = piezo_tools.reset_position(atc, axes=(axis,), tolerance=position_tolerance)
        except Exception as e:
            print(f"ERROR: Piezo recovery failed: {e}")
            recovered = False

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
        f_start_hz = get_resonance_frequency(znb, ch, trace)

        if f_start_hz is None:
            print('ERROR: Resonance was not found even at the initial position.')

            notify(
                notify_callback,
                (
                    f"⚠️ {mode} Frequency Tuning Failed\n"
                    f"Resonance was not found even after "
                    f"returning to the initial position."
                ),
            )

            return None

    # Piezo slope測定
    print("\n================================")
    print("Measuring Piezo slopes")
    print("================================")
    print(f'Start       : {f_start_hz / 1e9:.9f} GHz')

    # +step
    print(f'Move        : +{probe_steps} steps')

    piezo_tools.move_steps(atc, axis, probe_steps, delay=0.01, settle=wait_time)

    f_plus_hz = get_resonance_frequency(znb, ch, trace)

    if f_plus_hz is None:
        handle_failure(
            atc=atc,
            axis=axis,
            mode=mode,
            reason='Resonance lost during +step slope measurement.',
            notify_callback=notify_callback,
            position_tolerance=position_tolerance,
        )

        return None

    slope_plus = (f_plus_hz - f_start_hz) / probe_steps

    print(f'After +{probe_steps:<3}: {f_plus_hz / 1e9:.9f} GHz')
    print(f'Slope +     : {slope_plus:+.3f} Hz/step')

    # -step
    print(f'\nMove        : -{probe_steps} steps')

    piezo_tools.move_steps(atc, axis, -probe_steps, delay=0.01, settle=wait_time)

    f_minus_hz = get_resonance_frequency(znb, ch, trace)

    if f_minus_hz is None:
        handle_failure(
            atc=atc,
            axis=axis,
            mode=mode,
            reason='Resonance lost during -step slope measurement.',
            notify_callback=notify_callback,
            position_tolerance=position_tolerance,
        )

        return None

    slope_minus = (f_minus_hz - f_plus_hz) / -probe_steps

    print(f'After -{probe_steps:<3}: {f_minus_hz / 1e9:.9f} GHz')
    print(f'Slope -     : {slope_minus:+.3f} Hz/step')

    # 傾きチェック
    if (abs(slope_plus) < 1.0 or abs(slope_minus) < 1.0):
        handle_failure(
            atc=atc,
            axis=axis,
            mode=mode,
            reason=(
                "Measured Piezo slope is too small. "
                f"slope_plus={slope_plus:+.3f}, "
                f"slope_minus={slope_minus:+.3f} Hz/step"
            ),
            notify_callback=notify_callback,
            position_tolerance=position_tolerance,
        )

        return None

    print("\n================================")
    print("Slope measurement finished")
    print("================================")
    print(f'Slope + : {slope_plus:+.3f} Hz/step')
    print(f'Slope - : {slope_minus:+.3f} Hz/step')

    # 逆方向のprobe移動後の値からFeedback開始
    f0_hz = f_minus_hz

    # Feedback
    for i in range(max_iterations):
        # Tuning 0はslope測定後。1以降は共鳴が存在するか確認
        if i > 0:
            f0_hz = get_resonance_frequency(znb, ch, trace)

            if f0_hz is None:
                handle_failure(
                    atc=atc,
                    axis=axis,
                    mode=mode,
                    reason='Resonance lost during feedback.',
                    notify_callback=notify_callback,
                    position_tolerance=position_tolerance,
                )

                return None

        f0 = f0_hz / 1e9

        print(f'\n--- Tuning {i} ---')
        print(f'Pre-save current : {f0:.9f} GHz')

        # VNAデータ保存
        #
        # save_callback()が10回測定したデータから
        # 共鳴周波数 [GHz] を返す。
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
                print('\nWARNING: VNA data saving failed.')
                print(e)

        # 目標周波数に対する残差
        residual_hz = target_f0 * 1e9 - f0_hz
        residual_khz = residual_hz / 1e3

        print('\nFeedback frequency:')
        print(f'Current : {f0:.9f} GHz')
        print(f'Target  : {target_f0:.9f} GHz')
        print(f'Residual: {residual_khz:+.3f} kHz')

        # 調整完了
        #
        # 最後に保存したグラフのResonanceを
        # final_f0として返す。
        if abs(residual_khz) <= tolerance_khz:
            print('\nTarget frequency reached.')
            print("\n================================")
            print("Frequency Tuning Completed")
            print("================================")
            print(f'Target          : {target_f0:.9f} GHz')
            print(f'Final resonance : {f0:.9f} GHz')
            print(f'Final residual  : {residual_khz:+.3f} kHz')
            print(f'AMP frequency    : {f0:.9f} GHz')

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

        # Feedback方向とstep数
        slope, required_steps = choose_feedback_slope(residual_hz, slope_plus, slope_minus)

        if slope is None:
            handle_failure(
                atc=atc,
                axis=axis,
                mode=mode,
                reason=(
                    "No valid feedback direction was found. "
                    f"Residual={residual_khz:+.3f} kHz, "
                    f"slope_plus={slope_plus:+.3f}, "
                    f"slope_minus={slope_minus:+.3f}"
                ),
                notify_callback=notify_callback,
                position_tolerance=position_tolerance,
            )

            return None

        move_steps = round(required_steps)

        if move_steps == 0:
            move_steps = 1 if required_steps > 0 else -1

        print(f'Slope    : {slope:+.3f} Hz/step')
        print(f'Required : {required_steps:+.2f} steps')
        print(f'Move     : {move_steps:+d} steps')

        # Piezo移動
        piezo_tools.move_steps(atc, axis, move_steps, delay=0.01, settle=wait_time)

    # 最大回数到達
    handle_failure(
        atc=atc,
        axis=axis,
        mode=mode,
        reason=f'Maximum iterations reached ({max_iterations}).',
        notify_callback=notify_callback,
        position_tolerance=position_tolerance,
    )

    return None
