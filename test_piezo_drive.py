import sys
import piezo_tools

# 使い方:
#   python3 test_piezo_drive.py                       全軸の電圧・周波数を表示 (読み出しのみ)
#   python3 test_piezo_drive.py axis voltage [freq]   axis のステップ電圧 [V] (と周波数 [Hz]) を変更
# 例: python3 test_piezo_drive.py 1 40 1500

def main():
  try:
    atc = piezo_tools.connect_piezo()
  except Exception as e:
    print("Connection Error:", e)
    return

  try:
    if len(sys.argv) >= 3:
      axis = int(sys.argv[1])
      piezo_tools.set_step_voltage(atc, axis, float(sys.argv[2]))
      if len(sys.argv) >= 4:
        piezo_tools.set_step_frequency(atc, axis, int(sys.argv[3]))
    piezo_tools.get_drive_settings(atc)
  finally:
    piezo_tools.disconnect_piezo(atc)

if __name__ == "__main__":
  main()
