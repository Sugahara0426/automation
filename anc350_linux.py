"""
Linux から USB 経由で ANC350 (v2) を安定して接続するための pylablib ラッパー。

pylablib の Attocube.ANC350.__init__ は接続時に
    flush_read() -> read(512) -> sync -> get_hardware_id() -> enable_updates(False)
を行う。read(512) はデバイスが自発的に送る定期更新 (TELL) パケットを待つが、
同じ初期化の中で enable_updates(False) により定期更新を止めてしまい、close() でも戻さない。
そのため 2 回目以降の接続では何も届かず read(512) がタイムアウトして失敗する。
(Windows DLL で接続すると定期更新が再び有効になるので、1 回だけ繋がるようになる)

このクラスは自発パケットを待たずに初期化し、前回セッションの残りパケットや
ずれたパケットを読み飛ばす。close() 時には定期更新を元に戻す
(素の pylablib や Windows 側のソフトで次に繋いでも動くようにするため)。

使い方:
    from anc350_linux import ANC350
    atc = ANC350()
    print(atc.get_position(1))
    atc.close()
"""

import struct
import time

import usb.core
import usb.util
from pylablib.core.devio import comm_backend
from pylablib.devices.Attocube import anc350 as _anc350
from pylablib.devices.Attocube.base import AttocubeError, AttocubeBackendError

VID = 0x16C0
PID = 0x055B
EP_READ = 0x86
EP_WRITE = 0x02


def _drain(instr, timeout=0.05, max_packets=1000):
    """IN エンドポイントに溜まっているパケットを読み捨てる"""
    n = 0
    with instr.using_timeout(timeout):
        for _ in range(max_packets):
            try:
                instr.read(512)
                n += 1
            except Exception:  # タイムアウト = 空になった
                break
    return n


def usb_reset():
    """USB ポートリセット (ケーブルの抜き差し相当)。通常の接続で失敗したときの最終手段"""
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        raise AttocubeError("ANC350 (16c0:055b) が見つかりません")
    dev.reset()
    usb.util.dispose_resources(dev)
    time.sleep(1.0)


class ANC350(_anc350.ANC350):
    """
    再接続できる ANC350。引数は pylablib の Attocube.ANC350 と同じ。

    Args:
        conn: 何台目の ANC350 か (1 台なら 0)
        timeout (float): 通信タイムアウト [s]
        retries (int): 初期化の再試行回数。最後の再試行の前に USB リセットを行う
        restore_updates (bool): close() 時に定期更新 (TELL) を有効に戻すか
    """

    def __init__(self, conn=0, timeout=5., retries=3, restore_updates=True):
        self._restore_updates = restore_updates
        last_error = None
        for attempt in range(retries):
            if attempt == retries - 1 and attempt > 0:
                usb_reset()
            try:
                self._connect(conn, timeout)
                return
            except (AttocubeError, ValueError) as e:
                last_error = e
                try:
                    self.instr.close()
                except Exception:
                    pass
                time.sleep(0.5)
        raise AttocubeError("ANC350 に接続できませんでした: {!r}".format(last_error))

    def _connect(self, conn, timeout):
        if isinstance(conn, int):
            # Ubuntu には libusb-0.1 が無いので libusb1 を明示する
            conn = (VID, PID, conn, EP_READ, EP_WRITE, "libusb1")
        instr = comm_backend.new_backend(conn, backend="pyusb", timeout=timeout,
                                         check_read_size=False, reraise_error=AttocubeBackendError)
        self._corr_number = 0
        self._tell_telegrams = {}
        # 親の ANC350.__init__ (自発パケット待ちを含む) は飛ばし、その基底クラスを初期化する
        super(_anc350.ANC350, self).__init__(instr)
        self.open()
        _drain(self.instr)
        self.set_value(0x000A, 0, 0)  # sync request
        time.sleep(0.05)
        _drain(self.instr)
        self.get_hardware_id()
        self.enable_updates(False)
        _drain(self.instr)
        self._add_info_variable("hardware_id", self.get_hardware_id)
        self._add_settings_variable("voltages", self.get_voltage, lambda v: self.set_voltage("all", v))
        self._add_settings_variable("offsets", self.get_offset, lambda v: self.set_offset("all", v))
        self._add_settings_variable("frequencies", self.get_frequency, lambda v: self.set_frequency("all", v))
        self._add_status_variable("status", self.get_status)
        self._add_status_variable("positions", self.get_position)
        self._add_status_variable("target_positions", self.get_target_position)
        self._add_status_variable("sensor_voltage", self.get_sensor_voltage)
        self._add_status_variable("capacitance", lambda: self.get_capacitance(measure=False), priority=-5)

    def _read_telegram(self, corr_number=None):
        """壊れたパケットや前回セッションの古い ACK は読み飛ばす (Windows DLL の sync 相当)"""
        deadline = time.time() + self.instr.timeout
        while True:
            if time.time() > deadline:
                raise AttocubeError("timeout while read")
            data = self.instr.read(512)
            if len(data) < 20:
                continue
            l, opcode, address, index, corr = struct.unpack("<IIIII", data[:20])
            if len(data) != l + 4:
                continue
            tg = self.Telegram(opcode, address, index, data[20:], corr)
            if opcode == 3:  # ACK
                if corr_number is None or corr == corr_number:
                    return tg
            elif opcode == 4:  # TELL
                self._tell_telegrams[(address, index)] = tg

    def close(self):
        try:
            if self.is_opened():
                if self._restore_updates:
                    self.enable_updates(True)
                    time.sleep(0.05)
                _drain(self.instr)
        except Exception:
            pass
        super().close()


if __name__ == "__main__":
    # 接続テスト (読み出しのみ、ピエゾは動かさない)
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    for i in range(n):
        atc = ANC350()
        print("[{}] hwid={} position={}".format(i + 1, atc.get_hardware_id(), atc.get_position()))
        atc.close()
    print("OK: {} 回連続で接続できました".format(n))
