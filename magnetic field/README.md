# 磁場監視 → Slack magnetic-probe

既存のMagneticField_Operator.pyとは別プロセスで動く、Kafka Consumerです。既存の測定・Kafka送信コードの変更は不要です。piezoと同じSlack Bot / chat.postMessage方式を使用します。

## セットアップ

既存のautomation用Linux PCのPython環境を使います。Python 3.9以上と `kafka-python` が導入済みで、KafkaおよびSlackへ接続できることが前提です。仮想環境の新規作成は不要です。

```sh
cd "/実際のパス/automation/magnetic field"
```

`magnetic_monitor.py` 冒頭の設定欄に、実際に使うPCでBotトークンを直接入力してください。`.env` の作成・読み込みは不要です。

```python
SLACK_BOT_TOKEN = "xoxb-実際のトークン"
MAGNETIC_SLACK_CHANNEL_ID = "C0CC7H319NX"  # magnetic-probe
```

トークンを記入したファイルは共有・Gitコミットしないでください。Botをmagnetic-probeへ招待し、chat:write権限を設定してください。

Kafkaの初期設定は送信コードに合わせた `10.105.52.103:9092` / `testdb` です。必要な場合のみ環境変数 `MAGNETIC_KAFKA_SERVERS`、`MAGNETIC_KAFKA_TOPIC`、`MAGNETIC_KAFKA_GROUP` で変更できます。

```sh
python3 magnetic_monitor.py --dry-run
# 内容確認後、Ctrl+Cで停止して本番起動
python3 magnetic_monitor.py
```

--dry-runは実際のKafkaを読みますが、Slack送信、状態ファイル保存、Kafkaオフセット更新を行いません。独立して起動するため、本番のConsumer Groupを使用しません。

## 測定データの流れ

`MagneticField_Operator.py` は測定装置が出力した `LastTrendData.csv` の更新を3秒ごとに確認し、最新行のCH1〜CH4の周波数・周波数差をKafkaへ送ります。CSVファイルそのものをSlackへ送る処理ではありません。

`magnetic_monitor.py` はKafkaに届いた測定値を受信し、異常・復帰を判定してSlackへ通知します。すでに測定側でKafka送信が動いている場合、監視PCでは `magnetic_monitor.py` だけ起動してください。

このPCでCSVの読み取りも行う場合は、`MagneticField_Operator.py` の `CSV_PATH` に実際のCSVのパスを設定し、同じフォルダで別ターミナルから起動します。親フォルダの `MuSEUM_KafkaProducer.py` も必要です。

```sh
PYTHONPATH=.. python3 MagneticField_Operator.py
```

## 受信状況の確認

起動後30秒ごとに、CH1〜CH4の最新の周波数・周波数差・測定からの経過秒数をターミナルへ表示します。起動後に対象データがない場合は未受信、最終測定から60秒超の場合は「更新停止/遅延」と表示します。無効な測定値もそのまま表示するため、「受信済み」は正常判定を意味しません。Slackにはこの定期表示を送りません。

## 判定

| 指標 | 正常条件 | 警告 | 復帰 |
| --- | --- | --- | --- |
| frequency | 72390900以上72391100以下 | 範囲外3回連続 | 範囲内3回連続 |
| freq_diff (fdiff) | 絶対値200以下 | 絶対値200超が3回連続 | 絶対値200以下が3回連続 |

CH1〜CH4と各指標を独立に監視します。境界値は正常。異常継続中は再通知しません。復帰後の再異常は改めて3回で通知。起動時正常なら通知しません。

fdiffを正方向の200超だけに限定する場合は `python3 magnetic_monitor.py --fdiff-positive-only --state positive_only_state.json` としてください。保存状態と判定条件が違う場合は起動を停止します。

3回は同じCHの異なる測定時刻の有効データ3件です。同一時刻の再送、過去に戻った時刻はカウントしません。非数値・欠損・NaN・無限値はその指標の連続回数をリセットし、正常復帰とみなしません。

送信形式は既存MuSEUM_KafkaProducer.pyのJSONを使用します。周波数は実機の `proton_frequency` と既存Operatorの `frequency` の両方に対応し、両方ある場合は `proton_frequency` を優先します。

```json
{"device_name":"MagneticField_CH1","data_type":"proton_frequency","value":{"timestamp":1793066400,"channel":1,"frequency":72391000,"freq_diff":0,"date":"2026/10/27","time":"11:00:00"}}
```

## 動作と制限

- 初回起動時はKafkaの最新位置から開始。既存のConsumerとは独立したGroupを使用し、測定側やpiezo側のメッセージを奪いません。この監視は1プロセスで運用してください。
- 通知済み状態、連続回数、最終測定時刻、未送信通知をmonitor_state.jsonに保存。再起動後も継続します。状態保存後にKafkaオフセットを確定します。ファイルを消すと判定がリセットされます。
- 測定から60秒超の古いデータと30秒超未来のデータは判定しません。監視端末と測定端末の時計を合わせてください。60秒超の観測間隔では連続回数をリセットします。
- 再起動後は保存したKafka位置から再開しますが、古いデータの通知は出しません。停止中の異常を遡ってすべて通知する用途ではありません。
- データ途絶アラートはありません。未受信中は3回に数えません。同一秒に複数測定がある場合はタイムスタンプ形式の調整が必要です。
- Slack送信失敗時は未送信通知を残し60秒以上空けて再試行。HTTP 429はRetry-Afterにも従います。警告後に復帰した場合も順番に保持します。最大8件をまとめて送信します。
- Slack受理直後の通信断や状態保存前の終了では重複送信の可能性があります。Slackの通信待機は最大5秒で、その間のKafka値は次回pollで処理します。
- Slack長期障害では未送信通知が蓄積します。Kafka障害・状態ファイル破損ではエラー終了するため、運用時はプロセス監視を別途設定してください。
- 現物のKafka/Slackに対する接続・送信試験は行っていません。実際に使うPCでBotトークンの入力が必要です。チャンネルIDは設定済みです。

仕様参照: https://docs.slack.dev/reference/methods/chat.postMessage/
Kafka: https://kafka-python.readthedocs.io/en/2.3.2/apidoc/KafkaConsumer.html
