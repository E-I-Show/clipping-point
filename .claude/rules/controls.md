---
paths:
  - "clipping_point/cp_core/input_frame.py"
  - "clipping_point/cp_core/input_script.py"
  - "clipping_point/cp_app/input_pyxel.py"
  - "clipping_point/cp_app/input_web.py"
  - "clipping_point/cp_app/input_trace.py"
  - "tools/input_reference.py"
  - "tools/input_script_smoke.json"
  - "tools/web/fake_gamepad.js"
  - "tests/test_input_frame.py"
  - "tests/test_input_script.py"
  - "tests/test_input_pyxel.py"
  - "tests/test_input_web.py"
  - "tests/test_input_trace.py"
---

# 入力の取り込み（入力フレーム、台本、入力アダプタ、直読み）

## 約束

- 入力フレームは、1 tickに1度だけ作る。台本があれば台本から、無ければ入力アダプタから。台本のときは、入力アダプタも直読みも呼ばない。
- 舵は左が正。Pyxelの左スティックの軸（右が正）は、入力アダプタで符号を反転する。
- 入力フレームは、アナログ値（小数）とデジタル値（整数）を並べて持つ。どちらを使うかは、操作補正（段1）が決める。
- 入力アダプタは、値の範囲をそろえるだけ。遊びの除去と応答カーブは入れない。
- 「押した瞬間」は、入力アダプタが `btnp`（引数なし）で読み、台本は区間の頭で導く。受ける側（世界、画面の状態）は、押した瞬間だけを見て動く。「押している」の立ち上がりを、自分では見ない。
- アナログ値は、bool でない整数も受けて小数に直す。デジタル値は、bool と小数を受けない。
- 比較は、量子化した整数で行う（アナログ値は千分率。丸めの前の計算は、掛け算と割り算だけ）。
- `input_pyxel`、`input_web`、`input_trace` は、pyxel と js をimportしない。引数で受け、偽の実装でテストする。
- ブラウザ版で直読みができたtickは、Pyxel経由のトリガーを読まない。直読みは、最初の空でないコントローラーの枠だけを見る。
- 直読みは、例外を捕まえたら、印の付いた警告を出す。煙テストは、どの筋書きでも、この警告が0件であることを見る。
- 台本は、入力フレームをそのまま差し込む。Pyxelの `set_btn` での注入は作らない。

## 値を読む口

- ボタンの名とビットの順、量子化の並び、畳み込み：`cp_core/input_frame.py` の `BUTTONS`、`QUANTIZED_FIELDS`、`quantize()`、`fold()`
- 台本の形：`cp_core/input_script.py` の頭の注。道具の台本は `tools/input_script_smoke.json`
- キーの割り当て（Pyxelの定数の名前）：`cp_app/input_pyxel.py` の表。元は、正本の操作の表
- 直読みの警告の印：`cp_app/input_web.py` の `WARN_MARK`
- 入力の跡の形と戻し方：`cp_app/input_trace.py` の頭の注と `expand()`
- 台本からの参照（世界の要約、tickごとの値）：`tools/input_reference.py`
- 偽のコントローラーの予定と、判定に使う値：`tools/web_smoke.py` の `PAD_STAGES`。予定の区間の長さと、判定しないtick数は `tools/budgets.json`
- 結果に出す入力の値（`input_source`、`adapter_reads`、`direct_reads`）：`cp_app/app.py` の `input_report()`。2つの回数は、台本なら0、入力アダプタなら回したtickと同じ

## Xを足したらYも

- ボタンを足したら、`BUTTONS` の末尾、`input_pyxel.py` の `BUTTON_KEYS`、道具の台本、`tests/test_input_pyxel.py` の `ONE_KEY` に足す。
- 入力フレームに値を足したら、`QUANTIZED_FIELDS`、`quantize()`、台本の `VALUE_KEYS`、仮の表示、道具の台本に足す。
- 割り当てを変えたら、`ONE_KEY` を直す。正本の操作の表と違えるなら、改訂案を起こす。
- 偽のコントローラーの予定を変えたら、`PAD_STAGES` の `expect` を、実測して置き直す。

## テストと道具

- テスト `tests/test_input_frame.py`、`test_input_script.py`、`test_input_pyxel.py`、`test_input_web.py`、`test_input_trace.py`：型と範囲、押した瞬間の導き方、割り当て、トリガーの3通り、空のコントローラーの枠、打ち切り。
- 道具 `python3 tools/run.py`：台本を渡して回し、世界の要約を参照と照らす。`--realtime` は、入力アダプタを実物のPyxelで毎tick呼ぶ。
- 道具 web-smoke の筋書き `script` と `gamepad`：ブラウザ版で、台本と偽のコントローラーの値が、入力フレームになって世界へ届くこと。

## 落とし穴

- 軸のキーを `btn` で、ボタンのキーを `btnv` で読むと、Pyxelの中で落ちる。
- 空のコントローラーの枠は、ブラウザ版のPythonでは `None` でなく `jsnull`（型の名が `JsNull`）。属性を読むと `AttributeError`。`undefined` は `None`。
- JavaScriptを通った `1.0` は、Pythonでは整数の `1` で届く。
- ブラウザ版のトリガーは、Pyxel経由では0か最大かの2値。標準でない並びのコントローラーでも同じ。
- ブラウザ版のランタイムは、接続の後の最初の軸の変化を、Pyxelへ届けない。偽のコントローラーは、先に軸をわずかに動かす。
- 偽のコントローラーには、Gamepad APIの形を全部持たせる。欠けると、ランタイムが落ちる。
- 切断すると、Pyxel経由の値は、次のtickで0へ戻る。
- コントローラーを1台だけつないだときは、どのコントローラーの枠に入っても、直読みとPyxel経由が同じ機器を見る（偽のコントローラーを2番目の枠に置いた実測）。2台以上つないだときは、確かめていない。
