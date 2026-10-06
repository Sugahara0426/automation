# ============================================================
# Switchcontrol.py
#
# PMX32-2QU を用いたマイクロ波スイッチ制御
#
# CH2 : SG / VNA 切替
# CH3 : 共通12V供給
# CH4 : TM110 / TM210 切替
# ============================================================

import socket
import sys
import time

# ===== PMX設定 =====
PMX_IP = "192.168.12.5"
PMX_PORT = 5025

# ===== チャンネル割り当て =====
CH_SWITCH1 = 2
CH_COMMON  = 3
CH_SWITCH2 = 4

# ===== 共通電源設定 =====
COMMON_VOLTAGE = 12.0
COMMON_CURRENT = 5.0

# ===== 安全制限 =====
MAX_VOLTAGE = 15.0
MAX_CURRENT = 5.0

# ===== 設定ファイル読み込み =====
import SGvsVNA_set
import TM_set


# ============================================================
# 基本通信関数
# ============================================================

def send(sock, cmd):
    sock.sendall((cmd + "\n").encode())


def query(sock, cmd):
    send(sock, cmd)
    return sock.recv(1024).decode().strip()


# ============================================================
# チャンネル選択
# ============================================================

def select_channel(sock, ch):

    send(sock, f"INST:NSEL {ch}")

    time.sleep(0.1)


# ============================================================
# 出力制御
# ============================================================

def output_on(sock, ch):

    select_channel(sock, ch)

    send(sock, "OUTP ON")


def output_off(sock, ch):

    select_channel(sock, ch)

    send(sock, "OUTP OFF")


# ============================================================
# 電圧・電流設定
# ============================================================

def apply_setting(sock, ch, voltage, current):

    select_channel(sock, ch)

    send(sock, f"VOLT {voltage}")
    send(sock, f"CURR {current}")

    time.sleep(0.1)


# ============================================================
# 状態表示
# ============================================================

def print_channel_status(sock, ch, name=""):

    select_channel(sock, ch)

    voltage = query(sock, "VOLT?")
    current = query(sock, "CURR?")
    output  = query(sock, "OUTP?")

    print("-----------------------------------")

    if name:
        print(f"CH{ch} : {name}")
    else:
        print(f"CH{ch}")

    print(f"Voltage : {voltage} V")
    print(f"Current : {current} A")
    print(f"Output  : {'ON' if output == '1' else 'OFF'}")


# ============================================================
# ALL OFF
# ============================================================

def all_off():

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:

        s.settimeout(3)

        print("===================================")
        print("Connecting to PMX32-2QU...")
        print("===================================")

        s.connect((PMX_IP, PMX_PORT))

        print("Connected\n")

        output_off(s, CH_SWITCH1)
        print("CH2 -> OFF")

        output_off(s, CH_COMMON)
        print("CH3 -> OFF")

        output_off(s, CH_SWITCH2)
        print("CH4 -> OFF")

        print("\n===================================")
        print("All channels OFF completed")
        print("===================================")


# ============================================================
# メイン制御関数
# ============================================================

def set_switch(mode1, mode2):

    # ========================================================
    # 引数チェック
    # ========================================================

    if mode1 not in ["SG", "VNA"]:

        raise ValueError("mode1 must be SG or VNA")

    if mode2 not in ["TM110", "TM210"]:

        raise ValueError("mode2 must be TM110 or TM210")

    # ========================================================
    # 設定値読み込み
    # ========================================================

    sw1_voltage = SGvsVNA_set.VOLTAGE
    sw1_current = SGvsVNA_set.CURRENT

    sw2_voltage = TM_set.VOLTAGE
    sw2_current = TM_set.CURRENT

    # ========================================================
    # 安全チェック
    # ========================================================

    if sw1_voltage > MAX_VOLTAGE:
        raise ValueError("CH2 voltage too high")

    if sw1_current > MAX_CURRENT:
        raise ValueError("CH2 current too high")

    if sw2_voltage > MAX_VOLTAGE:
        raise ValueError("CH4 voltage too high")

    if sw2_current > MAX_CURRENT:
        raise ValueError("CH4 current too high")

    # ========================================================
    # 接続
    # ========================================================

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:

        s.settimeout(3)

        print("===================================")
        print("Connecting to PMX32-2QU...")
        print(f"IP   : {PMX_IP}")
        print(f"PORT : {PMX_PORT}")
        print("===================================")

        s.connect((PMX_IP, PMX_PORT))

        print("Connected\n")

        # ====================================================
        # ID確認
        # ====================================================

        try:
            idn = query(s, "*IDN?")
            print(f"Instrument : {idn}")
        except:
            print("Warning: *IDN? failed")

        # ====================================================
        # 実行前状態表示
        # ====================================================

        print("\n===================================")
        print("Current Status")
        print("===================================")

        print_channel_status(s, CH_SWITCH1, "Switch1 SG/VNA")
        print_channel_status(s, CH_COMMON,  "Common 12V")
        print_channel_status(s, CH_SWITCH2, "Switch2 TM")

        # ====================================================
        # CH3 : 共通12V供給
        # ====================================================

        print("\n===================================")
        print("CH3 : Common Power")
        print("===================================")

        apply_setting(
            s,
            CH_COMMON,
            COMMON_VOLTAGE,
            COMMON_CURRENT
        )

        output_on(s, CH_COMMON)

        # ====================================================
        # CH2 : SG / VNA
        # ====================================================

        print("\n===================================")
        print("CH2 : Switch1 Control")
        print("===================================")

        apply_setting(
            s,
            CH_SWITCH1,
            sw1_voltage,
            sw1_current
        )

        if mode1 == "SG":

            output_off(s, CH_SWITCH1)

        elif mode1 == "VNA":

            output_on(s, CH_SWITCH1)

        # ====================================================
        # CH4 : TM110 / TM210
        # ====================================================

        print("\n===================================")
        print("CH4 : Switch2 Control")
        print("===================================")

        apply_setting(
            s,
            CH_SWITCH2,
            sw2_voltage,
            sw2_current
        )

        if mode2 == "TM110":

            output_off(s, CH_SWITCH2)

        elif mode2 == "TM210":

            output_on(s, CH_SWITCH2)

        time.sleep(0.3)

        # ====================================================
        # 最終状態表示
        # ====================================================

        print("\n===================================")
        print("Final Status")
        print("===================================")

        print_channel_status(s, CH_SWITCH1, "Switch1 SG/VNA")
        print_channel_status(s, CH_COMMON,  "Common 12V")
        print_channel_status(s, CH_SWITCH2, "Switch2 TM")

        print("\n===================================")
        print("Switch configuration completed")
        print("===================================")


# ============================================================
# コマンドライン実行用
# ============================================================

def main():

    if len(sys.argv) < 2:

        print("Usage:")
        print("python3 Switchcontrol.py [SG|VNA] [TM110|TM210]")
        print("python3 Switchcontrol.py [OFF|ALLOFF]")

        sys.exit(1)

    # ========================================================
    # ALL OFF
    # ========================================================

    if sys.argv[1] in ["OFF", "ALLOFF"]:

        all_off()
        return

    # ========================================================
    # 通常モード
    # ========================================================

    if len(sys.argv) != 3:

        print("Usage:")
        print("python3 Switchcontrol.py [SG|VNA] [TM110|TM210]")

        sys.exit(1)

    mode1 = sys.argv[1]
    mode2 = sys.argv[2]

    set_switch(mode1, mode2)


# ============================================================
# 実行
# ============================================================

if __name__ == "__main__":
    main()