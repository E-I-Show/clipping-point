# CLIPPING POINT 設計時の試作一式

> 要約：実装設計と開発計画を書くために作った試作と実測の記録。本実装の土台ではなく、設計の裏付けと、段0・段1で作り直すときの参考。数値はすべて仮の値。

各領域の `RESULT.json` に、確かめたこと（証拠つき）、数値、推奨、確かめられなかったことがある。設計書の記述はここから引いている。

| ディレクトリ | 領域 | 主なファイル |
| --- | --- | --- |
| `spikes/frameloop/` | 毎秒60回の更新と30 fpsの描画、裏画面、ビルド | `proto/cp_proto/cp_core/fixed_loop.py`、`proto/tools/` |
| `spikes/web/` | ブラウザ版の実行、保存、ゲームパッド | `tools/webrun.js`（合否判定つきのブラウザ実行）、`tools/fetch_runtime.sh`、`apps/` |
| `spikes/render/` | Pyxel Cubeの描画、パレット、車のモデル生成 | `e10_proto.py`、`world.py`、`out/*.png`（試作画面） |
| `spikes/vehicle/` | 車両モデル（4輪、車輪回転なし） | `vehicle.py`、`t1_stability.py` ほか検証スクリプト |
| `spikes/track/` | コースの表、照会、周回判定、当たり | `track.py`、`akane_short.json`、`akane_short_map.png` |
| `spikes/assist/` | 操作補正とアシスト | `input_assist.py`、`assist_config.json`、`t_laps.py` ほか |
| `spikes/replay/` | リプレイの記録、再生、`.cpr` 形式 | `replay.py`、`replay_cam.py`、`golden_v1_0.cpr` |
| `spikes/audio/` | エンジン音の方式、チャンネル、BGM | `proto/`、`exp/wav/*.wav`（試聴用） |
| `spikes/harness/` | 検証の道具9本と、わざと壊す検査 | `repo/tools/` |
| `spikes/brief/BRIEF.md` | 試作の担当に渡した共通の前提 | |
| `spikes/wf/` | 調査、批評、確かめのワークフローの台本 | `spikes2.js`、`critique.js`、`confirm.js` |

## 注意

- 記録の中の作業用ディレクトリの絶対パスは、`<scratchpad>` などの印に置き換えてある。数値と判定には手を入れていない。
- 試作は領域ごとに独立していて、互いの口はそろえていない。本実装では実装設計の口に合わせて作り直す。
- `spikes/web/` のブラウザ版ランタイムの写し（約45 MB）は入れていない。`spikes/web/tools/fetch_runtime.sh` で取得し直せる。
- Pyxelのソースの写し、ビルドの生成物、録音の生データも入れていない。
- 試聴は `spikes/audio/exp/wav/demo_full_scenario.wav`（19秒。メニューのBGM、カウントダウン、アイドリングと空ぶかし、加速と変速、スライド、縁石と接触、路外、一時停止、リプレイ、リザルトの順）から。
