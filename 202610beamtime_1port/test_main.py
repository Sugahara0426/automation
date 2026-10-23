import pyvisa
import sys
import vna_tools

def main():
  rm = pyvisa.ResourceManager('@py')
  resource_string = 'TCPIP0::192.168.12.4::inst0::INSTR'
  
  # 1. 接続
  try:
    znb = vna_tools.get_vna_resource(rm, resource_string)
  except Exception as e:
    print("Connection Failed:", e)
    return

  # 2. セットアップ実行
  vna_tools.setup_vna(znb)

  # コマンドライン引数（ファイル名の末尾）を取得
  suffix_arg = sys.argv[1] if len(sys.argv) > 1 else "data"

  # 3. 測定と保存の実行
  vna_tools.measure_and_save(znb, suffix_arg)

  # 4. 終了処理
  znb.close()
  rm.close()

if __name__ == "__main__":
  main()