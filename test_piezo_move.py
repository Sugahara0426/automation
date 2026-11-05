import sys
import piezo_tools

# 使い方: python3 test_piezo_move.py axis steps [back]
#   axis  : 1 (TM110) or 2 (TM210)
#   steps : 動かすステップ数 (負で逆方向)
#   back  : "back" を付けると、同じステップ数だけ戻して往復させる
# 例: python3 test_piezo_move.py 1 5 back

def main():
  if len(sys.argv) < 3:
    print("Usage: python3 test_piezo_move.py axis steps [back]")
    return
  axis = int(sys.argv[1])
  steps = int(sys.argv[2])
  go_back = len(sys.argv) > 3 and sys.argv[3] == "back"

  try:
    atc = piezo_tools.connect_piezo()
  except Exception as e:
    print("Connection Error:", e)
    return

  try:
    piezo_tools.move_steps(atc, axis, steps)
    if go_back:
      piezo_tools.move_steps(atc, axis, -steps)
    piezo_tools.get_position(atc)
  finally:
    piezo_tools.disconnect_piezo(atc)

if __name__ == "__main__":
  main()
