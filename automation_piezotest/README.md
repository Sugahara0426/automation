# Piezo基準位置方式の実機テスト用コード

このフォルダ内のコードは実機を動かすコードです。模擬テスト用の機器ではありません。
既存automationおよび202610beamtime_1portのファイルは変更していません。

## 構成
- piezo_tune_test.py: 新しい調整処理（関数名はtune_piezoのまま）。直接実行せずcontrollerから使います。
- frequency_controller_piezotest.py: 新しい調整処理を呼ぶ受信側。
- frequency_command.py: 既存の送信側をそのままコピー。
- vna_tools.py: 既存のVNA操作をそのままコピー。

## 基準位置と動作
位置の単位はm。pylablibの軸番号は0始まりです。
- TM110: 本体CH2 / axis 1 / 0.007115193 m（7115.193 µm）
- TM210: 本体CH3 / axis 2 / 0.004126160 m（4126.160 µm）
- POSITION_TOLERANCE = 50e-6（±50 µm）。この範囲内なら復帰移動を省略します。

1. 調整しない方の軸を読み、基準から50 µmを超えていれば戻します。
2. 復帰は最大30秒で到達を待ち、停止後に1秒待って位置を再確認します。
3. その後、指定モードの共鳴をVNAで測ります。
4. 共鳴が見つかれば、調整軸を基準へ戻さず現在位置から調整します。
5. 共鳴が見つからなければ、調整軸も基準へそろえ、再測定します。
6. 復帰失敗・再測定でも共鳴なしなら、調整を開始せず終了します。
従来の共鳴検出（S11振幅0.5以下）、±10 kHz、±10 stepの試行、最大50回は維持します。
調整中の異常時にも、既存の復帰処理が上記基準位置を使います。
基準への復帰位置を再現できるか、50 µmが適切かは実機で確認してください。

## 実行
RF出力・パワーフィードバックは停止し、既存スイッチコードでVNA経路に設定してください。
1port運用ではTM110側入力に固定し、2port運用では測定モードに対応する入力を選択します。
スイッチ切替やRF停止はこのテストコード内では行いません。
ANC350は従来どおり初期化してLinux PCへUSB接続します。
このフォルダでシェルを開き、普段の実験用Python環境で実行します。

    python frequency_controller_piezotest.py

Waiting for frequency command...の表示を待ちます。別タブで同じフォルダを開き、Pythonで:

    from frequency_command import FrequencyCommandProducer
    producer = FrequencyCommandProducer()
    producer.send_target("TM110", 1897400)
    # TM210の例: producer.send_target("TM210", 2565900)
    producer.close()

送信単位はkHz。調整・復帰で両方の軸が動き得るため、初回は実機を確認しながら実行してください。
受信側の終了はCtrl+C。終了後も、処理中に動かした軸の位置は自動では元へ戻しません。

## Kafkaと保存先
Kafkaは既存のfrequency_controlを使います。新規トピック作成・既存トピック削除は行いません。
従来版とテスト版のcontrollerは同時に起動しないでください。同じ指令に両方が反応します。
テスト指令もKafkaの通常の保存対象です。
CSV・PNGはこのフォルダのdata/YYYYMMDD内に保存され、名前にpiezotestが入ります。PNGと保存名に入力ポートの固定表示はしません。
必要な外部ライブラリ・機器接続は従来と同じです。このフォルダだけではWindows用初期化は行えません。
