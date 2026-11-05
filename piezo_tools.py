# piezo_tools.py
# Version: 1.0.0 (2026-10-29)
#
# ANC350 (Attocube ピエゾコントローラ) 操作用の関数群。vna_tools.py と同じ使い方を想定。
#   軸番号は pylablib に合わせて 0 始まり。位置の単位は m。
#     axis 0 : 本体 CH1 (未使用。記録のみ)
#     axis 1 : 本体 CH2 / TM110
#     axis 2 : 本体 CH3 / TM210
#
# 変更履歴
#   1.1.0 (2026-10-29) ステップ電圧・周波数の読み書き (get_drive_settings, set_step_voltage,
#                      set_step_frequency, setup_piezo) を追加。measure_and_save の summary に駆動設定も記録
#   1.0.0 (2026-10-29) 初版

import csv
import time
import math
import statistics
import datetime
import os
import re

from anc350_linux import ANC350

# カラーコードの定義
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

AXES = (0, 1, 2)
AXIS_NAMES = {0: "CH1_unused", 1: "CH2_TM110", 2: "CH3_TM210"}

# 初期位置 [m] (axis 0, 1, 2)。axis 0 は未使用なので reset_position では動かさない
INITIAL_POSITION = (0.0, 0.007090, 0.004185)

# reset_position の安全制限: 現在位置からこれ以上離れた目標には動かさない [m]
MAX_RESET_DISTANCE = 0.5e-3

# set_step_voltage / set_step_frequency で受け付ける上限 (ANC350 の仕様上限 70 V 以下で設定)
MAX_STEP_VOLTAGE = 60.0     # [V]
MAX_STEP_FREQUENCY = 5000   # [Hz]

# setup_piezo で設定する駆動条件の初期値
DEFAULT_STEP_VOLTAGE = 30.0     # [V]
DEFAULT_STEP_FREQUENCY = 1500   # [Hz]


def connect_piezo(max_retries=3):
  """ANC350 に接続して atc を返す (USB リセットを含む再試行は ANC350 側で行う)"""
  for i in range(max_retries):
    try:
      print(f"Connecting to ANC350... ({i+1}/{max_retries})")
      atc = ANC350()
      print(f"{GREEN}ANC350 connected successfully!{RESET}")
      return atc
    except Exception as e:
      print(f"{RED}Connection attempt {i+1} failed: {e}{RESET}")
      if i < max_retries - 1:
        time.sleep(1.0)
      else:
        print("Maximum retry attempts reached.")
        raise e

def disconnect_piezo(atc):
  """接続を切る (close 時に定期更新を元に戻すので、次回もそのまま接続できる)"""
  try:
    atc.close()
    print(f"{GREEN}ANC350 disconnected.{RESET}")
  except Exception as e:
    print(f"{RED}ANC350 close failed: {e}{RESET}")

def check_connection(atc):
  """通信できるか確認する。全軸の位置が読めれば True"""
  try:
    pos = atc.get_position()
    if len(pos) != len(AXES) or not all(math.isfinite(p) for p in pos):
      raise ValueError(f"Invalid position readout: {pos}")
    print(f"{GREEN}ANC350 connection OK.{RESET}")
    return True
  except Exception as e:
    print(f"{RED}ANC350 connection check failed: {e}{RESET}")
    return False

def get_position(atc, verbose=True):
  """全軸の現在位置 [m] をリストで返す (axis 0, 1, 2)"""
  pos = list(atc.get_position())
  if verbose:
    for ax in AXES:
      print(f"  axis {ax} ({AXIS_NAMES[ax]:<10}): {pos[ax]*1e3:.6f} mm")
  return pos

def get_drive_settings(atc, verbose=True):
  """全軸の駆動設定を読んで dict で返す

  voltage   : ステップ電圧 [V] (1ステップの大きさに効く)
  frequency : ステップ周波数 [Hz] (move_to など連続移動の速さに効く。
              move_by_steps は 1コマンド = 1ステップなので速さは delay で決まる)
  offset    : DC オフセット電圧 [V]
  status    : 'running', 'limit', 'sens_err', 'sens_disconn', 'ref_valid' のリスト
  (is_enabled はこの実機では invalid address になるので読まない)
  """
  settings = {
    "voltage": list(atc.get_voltage()),
    "frequency": list(atc.get_frequency()),
    "offset": list(atc.get_offset()),
    "status": list(atc.get_status()),
  }
  if verbose:
    for ax in AXES:
      status = ", ".join(settings["status"][ax]) or "-"
      print(f"  axis {ax} ({AXIS_NAMES[ax]:<10}): "
            f"{settings['voltage'][ax]:5.1f} V, {settings['frequency'][ax]:5d} Hz, "
            f"offset {settings['offset'][ax]:5.2f} V, status [{status}]")
  return settings

def set_step_voltage(atc, axis, voltage):
  """axis のステップ電圧 [V] を設定し、読み戻した値を返す"""
  if axis not in AXES:
    raise ValueError(f"axis must be one of {AXES}")
  if not 0 <= voltage <= MAX_STEP_VOLTAGE:
    raise ValueError(f"voltage must be 0 - {MAX_STEP_VOLTAGE} V")
  before = atc.get_voltage(axis)
  after = atc.set_voltage(axis, voltage)
  color = GREEN if abs(after - voltage) < 1e-3 else RED
  print(f"{color}axis {axis}: step voltage {before:.1f} -> {after:.1f} V{RESET}")
  return after

def set_step_frequency(atc, axis, frequency):
  """axis のステップ周波数 [Hz] を設定し、読み戻した値を返す"""
  if axis not in AXES:
    raise ValueError(f"axis must be one of {AXES}")
  if not 1 <= frequency <= MAX_STEP_FREQUENCY:
    raise ValueError(f"frequency must be 1 - {MAX_STEP_FREQUENCY} Hz")
  before = atc.get_frequency(axis)
  after = atc.set_frequency(axis, int(frequency))
  color = GREEN if after == int(frequency) else RED
  print(f"{color}axis {axis}: step frequency {before} -> {after} Hz{RESET}")
  return after

def setup_piezo(atc, axes=AXES, voltage=DEFAULT_STEP_VOLTAGE, frequency=DEFAULT_STEP_FREQUENCY):
  """指定した軸のステップ電圧・周波数を初期値に設定する (ピエゾは動かない)。
  1ステップの大きさが変わるので、tune_piezo の slope などは設定後に測り直すこと"""
  print("Setting up ANC350...")
  for axis in axes:
    set_step_voltage(atc, axis, voltage)
    set_step_frequency(atc, axis, frequency)
  return get_drive_settings(atc)

def next_run_number(data_root="./data"):
  """vna_tools.next_run_number と同じ規則で次の通し Run 番号を返す
  (vna_tools を import すると VNA 用の ResourceManager が作られるので複製している)"""
  nums = [int(m.group(1)) for _, _, files in os.walk(data_root) for f in files
          if (m := re.match(r"Run(\d+)_", f))]
  return max(nums, default=0) + 1

def measure_and_save(atc, suffix_arg="data", output_dir=None, run_num=None,
                     num_measurements=10, interval=0.1):
  """全軸の位置を num_measurements 回読み、平均と生データを CSV に保存する

  保存先・Run 番号の扱いは vna_tools.measure_and_save と同じ
  (省略時は ./data/YYYYMMDD/RunXXX/、生データは raw_data/ 以下)。
  VNA の測定と同じ Run にまとめるときは同じ output_dir, run_num を渡す。

  Returns
  -------
  means : 各軸の平均位置 [m] のリスト
  """
  samples = []   # (経過時間 [s], [pos0, pos1, pos2])
  t0 = time.time()
  for m in range(num_measurements):
    print(f"Reading piezo position... ({m+1}/{num_measurements})")
    samples.append((time.time() - t0, list(atc.get_position())))
    if m < num_measurements - 1:
      time.sleep(interval)

  drive = get_drive_settings(atc, verbose=False)
  means = [statistics.mean(s[1][ax] for s in samples) for ax in AXES]
  stdevs = [statistics.stdev(s[1][ax] for s in samples) if num_measurements > 1 else 0.0
            for ax in AXES]

  # --- CSV書き出し ---
  now_dt = datetime.datetime.now()
  now_str = now_dt.strftime("%H%M%S")
  date_dir = now_dt.strftime("%Y%m%d")

  if run_num is None:
    run_num = next_run_number()
  run_str = f"Run{run_num:03d}"

  if output_dir is None:
    output_dir = f"./data/{date_dir}/{run_str}"
  raw_dir = f"{output_dir}/raw_data"
  os.makedirs(raw_dir, exist_ok=True)

  summary_filename = f"{output_dir}/{run_str}_{now_str}_piezo_{suffix_arg}.csv"
  with open(summary_filename, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['Axis', 'Name', 'Position_Mean [m]', 'Position_Err [m]', 'N',
                     'Step_Voltage [V]', 'Step_Frequency [Hz]', 'Offset [V]', 'Status'])
    for ax in AXES:
      writer.writerow([ax, AXIS_NAMES[ax], means[ax], stdevs[ax], num_measurements,
                       drive['voltage'][ax], drive['frequency'][ax], drive['offset'][ax],
                       "|".join(drive['status'][ax])])
  print(f"Piezo summary saved to: {summary_filename}")

  raw_filename = f"{raw_dir}/{run_str}_{now_str}_piezo_raw_{suffix_arg}.csv"
  with open(raw_filename, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['Measurement_Count', 'Elapsed [s]'] +
                    [f'Axis{ax}_{AXIS_NAMES[ax]} [m]' for ax in AXES])
    for m_idx, (t, pos) in enumerate(samples):
      writer.writerow([m_idx + 1, f"{t:.3f}"] + pos)
  print(f"Piezo raw data saved to: {raw_filename}")

  for ax in AXES:
    print(f"  axis {ax} ({AXIS_NAMES[ax]:<10}): {means[ax]*1e3:.6f} mm ± {stdevs[ax]*1e6:.3f} µm")
  return means

def move_steps(atc, axis, steps, delay=0.01, settle=0.1):
  """axis を現在位置から steps ステップ動かす (正負で方向)。移動後の位置 [m] を返す

  delay  : 1ステップごとの待ち [s] (scan_macro / tune_piezo と同じ 0.01)
  settle : 移動後、位置を読むまでの待ち [s]
  """
  if axis not in AXES:
    raise ValueError(f"axis must be one of {AXES}")
  if axis == 0:
    print(f"{YELLOW}WARNING: axis 0 (CH1) は未使用の軸です。{RESET}")
  before = atc.get_position(axis)
  atc.move_by_steps(axis, int(steps), delay)
  time.sleep(settle)
  after = atc.get_position(axis)
  print(f"axis {axis}: {steps:+d} steps  "
        f"{before*1e3:.6f} -> {after*1e3:.6f} mm  (Δ = {(after-before)*1e6:+.3f} µm)")
  return after

def reset_position(atc, axes=(1, 2), initial_position=INITIAL_POSITION,
                   tolerance=50e-6, timeout=30.0, max_distance=MAX_RESET_DISTANCE):
  """指定した軸を初期位置へ戻す。全軸が tolerance 以内に入れば True

  この実機では精度レジスタ (0x3036) が invalid address になるため、
  pylablib の wait_move / is_target_reached は使わず、位置を読み続けて到達を判定する。
  最後に stop() で閉ループ制御を止める (止めないと後の move_steps が戻されるため)。
  現在位置から max_distance より遠い目標は、設定ミスとみなして動かさない。
  """
  ok = True
  for axis in axes:
    target = initial_position[axis]
    current = atc.get_position(axis)
    error = abs(current - target)
    print(f"axis {axis} ({AXIS_NAMES[axis]}): current {current*1e3:.6f} mm, "
          f"target {target*1e3:.6f} mm, error {error*1e6:.3f} µm")

    if error <= tolerance:
      print(f"{GREEN}  Within tolerance; no move.{RESET}")
      continue
    if error > max_distance:
      print(f"{RED}  Target is {error*1e3:.3f} mm away (> {max_distance*1e3:.3f} mm). "
            f"Not moved. Check initial_position.{RESET}")
      ok = False
      continue

    deadline = time.monotonic() + timeout
    try:
      atc.move_to(axis, target)
      while True:
        current = atc.get_position(axis)
        error = abs(current - target)
        if error <= tolerance:
          break
        if time.monotonic() >= deadline:
          raise TimeoutError(f"not reached within {timeout} s (error {error*1e6:.3f} µm)")
        time.sleep(0.1)
    except Exception as e:
      print(f"{RED}  Reset failed: {e}{RESET}")
      ok = False
    finally:
      atc.stop(axis)

    time.sleep(0.5)
    current = atc.get_position(axis)
    error = abs(current - target)
    reached = error <= tolerance
    color = GREEN if reached else RED
    print(f"{color}  Returned: {current*1e3:.6f} mm, error {error*1e6:.3f} µm{RESET}")
    ok = ok and reached
  return ok


if __name__ == "__main__":
  # 動作確認 (読み出しのみ。ピエゾは動かさない)
  atc = connect_piezo()
  try:
    check_connection(atc)
    get_position(atc)
    get_drive_settings(atc)
  finally:
    disconnect_piezo(atc)
