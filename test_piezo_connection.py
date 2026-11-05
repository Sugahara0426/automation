import sys
import piezo_tools

# 使い方: python3 test_piezo_connection.py [回数]  (省略時 1)
# 読み出しのみ (ピエゾは動かさない)。接続 -> 通信確認 -> 位置・駆動設定の表示 -> 切断 を繰り返す

def main():
  n = int(sys.argv[1]) if len(sys.argv) > 1 else 1

  for i in range(n):
    print(f"\n=== Connection test {i+1}/{n} ===")
    try:
      atc = piezo_tools.connect_piezo()
    except Exception as e:
      print("Connection Error:", e)
      return

    try:
      if not piezo_tools.check_connection(atc):
        return
      print("Position:")
      piezo_tools.get_position(atc)
      print("Drive settings:")
      piezo_tools.get_drive_settings(atc)
    finally:
      piezo_tools.disconnect_piezo(atc)

  print(f"\n{piezo_tools.GREEN}OK: {n} 回連続で接続できました{piezo_tools.RESET}")

if __name__ == "__main__":
  main()
