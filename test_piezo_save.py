import sys
import piezo_tools

# 使い方: python3 test_piezo_save.py [suffix]  (省略時 data)
# 読み出しのみ。全軸の位置を10回読んで平均・生データを保存
# 出力: ./data/YYYYMMDD/RunXXX/RunXXX_HHMMSS_piezo_{suffix}.csv
#       ./data/YYYYMMDD/RunXXX/raw_data/RunXXX_HHMMSS_piezo_raw_{suffix}.csv

def main():
  suffix = sys.argv[1] if len(sys.argv) > 1 else "data"

  try:
    atc = piezo_tools.connect_piezo()
  except Exception as e:
    print("Connection Error:", e)
    return

  try:
    piezo_tools.measure_and_save(atc, suffix)
  finally:
    piezo_tools.disconnect_piezo(atc)

if __name__ == "__main__":
  main()
