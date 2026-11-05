import piezo_tools

# 使い方: python3 test_piezo_setup.py
# 全軸のステップ電圧・周波数を初期値 (piezo_tools.DEFAULT_STEP_VOLTAGE / DEFAULT_STEP_FREQUENCY,
# 30 V / 1500 Hz) に設定する。ピエゾは動かないが、1ステップの大きさが変わる

def main():
  try:
    atc = piezo_tools.connect_piezo()
  except Exception as e:
    print("Connection Error:", e)
    return

  try:
    piezo_tools.setup_piezo(atc)
  finally:
    piezo_tools.disconnect_piezo(atc)

if __name__ == "__main__":
  main()
