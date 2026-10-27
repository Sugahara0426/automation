#!/usr/bin/env python3
"""Independent Kafka -> Slack magnetic-field monitor. Python 3.9+."""
import argparse
import fcntl
import json
import logging
import math
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

LOG = logging.getLogger("magnetic_monitor")
BASE = Path(__file__).resolve().parent

# 実際に使うPCで入力してください。トークン記入後のファイルは共有・コミットしないでください。
SLACK_BOT_TOKEN = ""
MAGNETIC_SLACK_CHANNEL_ID = "C0CC7H319NX"  # magnetic-probe

RULES = {"frequency_min": 72380000, "frequency_max": 72397000,
         "fdiff_limit": 200, "absolute_fdiff": True, "consecutive": 3}


class Monitor:
    def __init__(self, rules=None, state=None, max_age=60):
        self.rules = dict(RULES if rules is None else rules)
        self.state = state if state is not None else {
            "rules": self.rules, "channels": {}, "outbox": []}
        if self.state.get("rules") != self.rules:
            raise ValueError("Rules differ from saved state; use a new --state path")
        if not isinstance(self.state.get("channels"), dict) or not isinstance(self.state.get("outbox"), list):
            raise ValueError("Invalid state file")
        self.max_age = max_age

    def handle(self, payload, now=None):
        if not isinstance(payload, dict):
            return False
        match = re.fullmatch(r"MagneticField_CH([1-4])", str(payload.get("device_name", "")))
        if not match or payload.get("data_type") != "proton_frequency":
            return False
        value = payload.get("value")
        if not isinstance(value, dict):
            return False
        channel = match.group(1)
        if str(value.get("channel")) != channel:
            LOG.warning("Ignoring channel/device mismatch")
            return False
        try:
            timestamp = float(value["timestamp"])
            if not math.isfinite(timestamp):
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            LOG.warning("Ignoring measurement without valid timestamp")
            return False
        now = time.time() if now is None else now
        if now - timestamp > self.max_age or timestamp > now + 30:
            LOG.warning("Ignoring old/future measurement CH%s", channel)
            return False
        ch = self.state["channels"].setdefault(channel, {"last_timestamp": None, "metrics": {}})
        if ch["last_timestamp"] is not None and timestamp <= ch["last_timestamp"]:
            return False  # replay, duplicate, or out-of-order sample
        previous = ch["last_timestamp"]
        ch["last_timestamp"] = timestamp
        for metric, key in (("frequency", "frequency"), ("fdiff", "freq_diff")):
            status = ch["metrics"].setdefault(metric, {"abnormal": False, "count": 0})
            if previous is not None and timestamp - previous > self.max_age:
                status["count"] = 0
            try:
                raw = value.get(key)
                if isinstance(raw, bool):
                    raise ValueError()
                number = float(raw)
                if not math.isfinite(number):
                    raise ValueError()
            except (TypeError, ValueError):
                status["count"] = 0
                LOG.warning("Invalid %s CH%s; consecutive count reset", metric, channel)
                continue
            r = self.rules
            if metric == "frequency":
                bad = not r["frequency_min"] <= number <= r["frequency_max"]
                normal = f'{r["frequency_min"]} <= frequency <= {r["frequency_max"]}'
            else:
                compared = abs(number) if r["absolute_fdiff"] else number
                bad = compared > r["fdiff_limit"]
                label = "abs(fdiff)" if r["absolute_fdiff"] else "fdiff"
                normal = f'{label} <= {r["fdiff_limit"]}'
            if bad == status["abnormal"]:
                status["count"] = 0
                continue
            status["count"] += 1
            if status["count"] < r["consecutive"]:
                continue
            status.update(abnormal=bad, count=0)
            label = "⚠️ 磁場異常" if bad else "✅ 磁場復帰"
            measured = f'{value.get("date", "")} {value.get("time", "")}'.strip()
            text = (f'{label} CH{channel}: {metric}={number:g}\n'
                    f'正常条件: {normal}\n{r["consecutive"]}回連続で確認\n'
                    f'測定時刻: {measured or timestamp} (Unix: {timestamp:g})')
            self.state["outbox"].append(text)
            LOG.info("%s CH%s %s=%s", label, channel, metric, number)
        return True


def save_state(path, state):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(state, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


class SlackSender:
    def __init__(self, token, channel):
        self.token, self.channel = token, channel
        self.next_attempt = 0

    def flush(self, state):
        if not state["outbox"] or time.monotonic() < self.next_attempt:
            return False
        batch = state["outbox"][:8]
        request = Request("https://slack.com/api/chat.postMessage",
            data=json.dumps({"channel": self.channel, "text": "\n\n".join(batch)},
                            ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json; charset=utf-8"}, method="POST")
        delay = 60
        try:
            with urlopen(request, timeout=5) as response:
                result = json.load(response)
            if result.get("ok") is not True:
                LOG.error("Slack rejected message: %s", result.get("error", "unknown"))
                self.next_attempt = time.monotonic() + delay
                return False
        except HTTPError as exc:
            if exc.code == 429:
                try:
                    delay = max(60, float(exc.headers.get("Retry-After", 60)))
                except (ValueError, TypeError):
                    pass
            LOG.error("Slack HTTP error %s; keeping notification", exc.code)
            self.next_attempt = time.monotonic() + delay
            return False
        except Exception as exc:
            LOG.error("Slack delivery failed (%s); keeping notification", type(exc).__name__)
            self.next_attempt = time.monotonic() + delay
            return False
        del state["outbox"][:len(batch)]
        self.next_attempt = time.monotonic() + 1.1
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Kafka -> console only; no Slack/state/offset commits")
    parser.add_argument("--state", type=Path, default=BASE / "monitor_state.json")
    parser.add_argument("--fdiff-positive-only", action="store_true", help="Use fdiff > 200 instead of abs(fdiff) > 200")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token, channel = SLACK_BOT_TOKEN, MAGNETIC_SLACK_CHANNEL_ID
    if not args.dry_run and (not token.startswith("xoxb-") or not re.fullmatch(r"[CG][A-Z0-9]+", channel)):
        parser.error("Set SLACK_BOT_TOKEN and MAGNETIC_SLACK_CHANNEL_ID in magnetic_monitor.py")
    from kafka import KafkaConsumer
    from kafka.structs import OffsetAndMetadata, TopicPartition
    rules = dict(RULES, absolute_fdiff=not args.fdiff_positive_only)
    # One monitor per state file on macOS/Linux. Keep this handle open.
    lock = None
    if not args.dry_run:
        lock = args.state.with_suffix(".lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Another monitor is already using this state file")
    state = None
    if not args.dry_run and args.state.exists():
        state = json.loads(args.state.read_text(encoding="utf-8"))
    monitor = Monitor(rules, state)
    sender = SlackSender(token, channel)
    consumer = KafkaConsumer(
        os.getenv("MAGNETIC_KAFKA_TOPIC", "testdb"),
        bootstrap_servers=os.getenv("MAGNETIC_KAFKA_SERVERS", "10.105.52.103:9092").split(","),
        group_id=None if args.dry_run else os.getenv("MAGNETIC_KAFKA_GROUP", "magnetic-probe-slack-v1"),
        auto_offset_reset="latest", enable_auto_commit=False,
        max_poll_records=100,
    )
    LOG.info("Monitoring MagneticField_CH1-CH4; dry_run=%s", args.dry_run)
    try:
        while True:
            records = consumer.poll(timeout_ms=1000)
            offsets = {}
            dirty = False
            for partition, batch in records.items():
                for record in batch:
                    try:
                        payload = json.loads(record.value.decode("utf-8"))
                    except (UnicodeDecodeError, ValueError):
                        LOG.warning("Skipping malformed Kafka JSON")
                    else:
                        dirty = monitor.handle(payload) or dirty
                    offsets[TopicPartition(record.topic, record.partition)] = OffsetAndMetadata(record.offset + 1, "")
            if args.dry_run:
                for text in monitor.state["outbox"]:
                    print(text, flush=True)
                monitor.state["outbox"].clear()
                continue
            # Persist transitions and outbox before advancing Kafka offsets.
            if dirty:
                save_state(args.state, monitor.state)
            if offsets:
                consumer.commit(offsets=offsets)
            if sender.flush(monitor.state):
                save_state(args.state, monitor.state)
    except KeyboardInterrupt:
        LOG.info("Stopped")
    finally:
        consumer.close()
        if lock:
            lock.close()


if __name__ == "__main__":
    main()
