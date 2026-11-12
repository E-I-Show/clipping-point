---
paths:
  - "clipping_point/cp_app/web_bridge.py"
  - "tools/web/**"
  - "tools/web_smoke.py"
  - "tests/test_web_bridge.py"
  - "tests/test_web_smoke.py"
---

# ブラウザ版の煙テストとブラウザ連携

## 約束

- 開くのは `tools/export.py` が作った `dist/clipping_point.html` そのもの（同じバイト列）。煙テスト用に作り直したHTMLを開かない。値は、ページを開く前に差し込むスクリプトで外から渡す。
- ランタイムへの要求は、ランタイムの写し（`.cache/pyxel_web/mirror/`）へ差し替える。そこに無いファイルへの要求と、その外への要求は、通さずに失敗にする。
- ランタイムの写しの取得元は、GitHubのPyxelリポジトリ（v3.0.1）とnpmのPyodide 314.0.7だけ。kitao.dev と cdn.jsdelivr.net には触れない。`tools/web/SHA256SUMS` と照合する。
- ランタイムの写しが無い、node が無い、ビルドできない、完了の合図が出ないときは2。合格にしない。ページが返らないとき（失敗の種類 `unresponsive`）は1。
- 合否を決めるのは `tools/web_smoke.py`。ブラウザの実行役（`tools/web/webrun.js`）は、起きたことを集めてJSONに書くだけ。ページが返らなくても、集めた分を書いてから終わる。
- 線の判定に使うのは、慣らしを除いた値。慣らしを入れた値も、結果の1行（`with_warmup`）に出す。
- 世界の要約の、デスクトップ版との突き合わせ（probe の `sim`、script と drive の `sim` と `sim_reference`）は、1つの関数（`summary_check()`）で、項目ごとに比べる（完全一致、許容差つき、折り返した差。比べ方の表は `cp_core/sim.py` の `SUMMARY_FIELDS`）。表に無い項目が要約にあれば、見ずに通さず、2にする。
- 筋書き `script` は、同じ値で、もう1度開き、2回の要約が、完全に同じことを見る（`sim_repeat`）。
- 筋書き `shipped` は、画面の色の数も見る（3Dの絵が載っている。`web_shipped_colors_min`）。
- 筋書き `drive`（走行の場面）は、走る台本を、指紋の筋書き `drive_900` と同じtick数で回す（走行の下限が掛かる）。線と、3Dの絵の確かめ（`render.md`。向きの符号の誤りを拾う）を見る。線を見るのは `probe` と `drive`。
- `web_bridge.py` は pyxel を読み込まない。ブラウザの機能（js のモジュール）は引数で受ける。js をimportするのは `browser_js()` の中だけ。
- 外から渡す値が無ければ、普通に起動する。形が違えば `ValueError`。
- ブラウザ版では `sys.exit` と `pyxel.quit` を呼ばない。結果を出した後も動き続ける。

## 値を読む口

- 外から渡す値の名前と形（`window.CP_PROBE = {ticks, warmup_ticks, script, trace_max}`）、tick の印、結果の行の頭、完了の合図：`cp_app/web_bridge.py` の `PROBE_NAME`、`TICK_NAME`、`RESULT_MARK`、`DONE_MARK`。道具もここから読む。
- `tools/budgets.json` の `web_` で始まる値：毎秒の回数と時間の4つは、計画の通過条件の線（仮の値ではない）。回すtick数、慣らし、実描画の回数の幅、見続ける秒数、時間切れ、要約の許容差（`web_summary_tolerance`。量子化の刻みで数える）は、仮の値。
- 要約の、デスクトップ版との差の最大（許容差の余裕）：最後の1行の `probe_gap=`、`script_gap=`、`drive_gap=`。比べる関数は `tools/input_reference.py` の `summary_differences()`
- ランタイムの版、置き場、取得元：`tools/web/fetch_runtime.py` の頭の定数。置き場と取得の関数は、`main()` の引数で替えられる。
- 失敗の種類：`tools/web_smoke.py` の `FAILURE_KINDS`（`webrun.js` の頭の注と同じ）
- 結果の `data`（`tables`、`warnings`、`pack`、`namespace`）：筋書き `probe` が、道具が自分で数えた件数（`tools/data_reference.py`）と照らす。ブラウザ版は、試験用データを重ねない（`pack` は null、`namespace` は `main`）。決まりは `.claude/rules/data.md`
- 結果：`out/web_smoke/`（筋書きごとのJSONと、画面のPNG。走行の絵は `drive.png`）

## Xを足したらYも

- 筋書きを足したら、`web_smoke.py` の `SCENARIOS` と判定の関数、`tests/test_web_smoke.py`、`tools/selftest_break.py` の壊す件に足す。
- `webrun.js` に失敗の種類を足したら、`FAILURE_KINDS` に足す（足さないと `other_failure` で落ちる）。
- `webrun.js` でページに問い合わせる所を足したら、時間切れつきの口（`ask`、`within`）を通す。
- 外から渡す値に項目を足したら、`web_bridge.py` の `PROBE_KEYS` と `read_probe()`、`tests/test_web_bridge.py` に足す。
- 世界の要約に項目を足したら、`SUMMARY_FIELDS` に比べ方を書く（無いと、probe と script が2になる）。
- ランタイムの版を上げたら、`fetch_runtime.py` の版の定数、`SHA256SUMS`、`requirements-dev.txt` をそろえる。
- ブラウザでしか動かないモジュール（入力の直読み、保存先、ファイルの受け渡し）も、js は引数で受け、偽の実装でテストする。

## テストと道具

- テスト `tests/test_web_bridge.py`：値がある、値が無い、形が違う、js が無い（デスクトップ版）。偽の js を渡す。
- テスト `tests/test_web_smoke.py`：判定の関数（失敗の種類ごと、線を外れた値ごと）、node が無い場合、取得と照合（一時の置き場と偽の取得の関数で通す）。ブラウザもネットワークも使わない。
- 道具 web-smoke（`python3 tools/web_smoke.py [--only 筋書きの名] [--ticks N] [--timeout 秒]`）：筋書きは6本（名は `SCENARIOS`）で、約90秒（`script` は、2度開く）。入力の2本の決まりは `controls.md`、保存は `save.md`。
- 道具 `python3 tools/web/fetch_runtime.py [--check]`：ランタイムの写しの取得と照合。`bash tools/setup_env.sh` が呼ぶ。
- 道具 selftest-break の `web_` と `fetch_` で始まる件：ブラウザ版でだけ起きる崩れを、web-smoke が拾うこと。

## 落とし穴

- ブラウザ版では、Pythonの例外は画面の表示になるだけで、ページは落ちない。完了の合図と、エラー表示が無いことの両方を見る。定義データの読み込み検査の例外（起動時）も、エラー表示で拾う。
- ブラウザ版でPythonが抜けないループに入ると、ページへの問い合わせ（`page.evaluate`）が返らなくなる。時間切れを付けずに待たない。
- ランタイムは、開始のクリックより前に読み込まれる。クリックするまで、アプリは動かない（音のため）。
- 画面（canvas）はWebGLで、ページの中からは画素を読めない。スクリーンショットの画素を数える。
- JavaScriptの undefined と null は、Pyodideでは別々の物になる。値は `JSON.stringify` で文字列にしてから受け取る。
- ブラウザ版は実時間で回る。600 tickを測るのに10秒かかる。時計は0.1 ms刻み。
- 回数と時間の線は、単独で回したときの値で見る。全体の検証の中で外れたら、単独で1度回し直す。
- 要約の、デスクトップ版との差は、段0 区切り9と10の実測では0。走行の絵の画素も、同じ（`drive_picture=same`）。それでも、位置や速度に完全一致を求めない（丸めの境目で、1刻み違いうる）。回数の項目は、許容差つきにしない。
- 取得の途中で切れた接続は `http.client.IncompleteRead` になる。`OSError` の子ではない。
