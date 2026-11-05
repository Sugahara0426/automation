import piezo_tools

# 使い方: python3 test_piezo_reset.py
# axis 1, 2 を piezo_tools.INITIAL_POSITION へ戻す (axis 0 は未使用なので動かさない)

def main():
  try:
    atc = piezo_tools.connect_piezo()
  except Exception as e:
    print("Connection Error:", e)
    return

  try:
    ok = piezo_tools.reset_position(atc)
    print("Reset:", "OK" if ok else "FAILED")
    piezo_tools.get_position(atc)
  finally:
    piezo_tools.disconnect_piezo(atc)

if __name__ == "__main__":
  main()
