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
- `web_bridge.py` は pyxel を読み込まない。ブラウザの機能（js のモジュール）は引数で受ける。js をimportするのは `browser_js()` の中だけ。
- 外から渡す値が無ければ、普通に起動する。形が違えば `ValueError`。
- ブラウザ版では `sys.exit` と `pyxel.quit` を呼ばない。結果を出した後も動き続ける。

## 値を読む口

- 外から渡す値の名前と形（`window.CP_PROBE = {ticks, warmup_ticks, script, trace_max}`）、tick の印、結果の行の頭、完了の合図：`cp_app/web_bridge.py` の `PROBE_NAME`、`TICK_NAME`、`RESULT_MARK`、`DONE_MARK`。道具もここから読む。
- `tools/budgets.json` の `web_` で始まる値：毎秒の回数と時間の4つは、計画の通過条件の線（仮の値ではない）。回すtick数、慣らし、実描画の回数の幅、見続ける秒数、時間切れは、仮の値。
- ランタイムの版、置き場、取得元：`tools/web/fetch_runtime.py` の頭の定数。置き場と取得の関数は、`main()` の引数で替えられる。
- 失敗の種類：`tools/web_smoke.py` の `FAILURE_KINDS`（`webrun.js` の頭の注と同じ）
- 結果：`out/web_smoke/`（筋書きごとのJSONと、画面のPNG）

## Xを足したらYも

- 筋書きを足したら、`web_smoke.py` の `SCENARIOS` と判定の関数、`tests/test_web_smoke.py`、`tools/selftest_break.py` の壊す件に足す。
- `webrun.js` に失敗の種類を足したら、`FAILURE_KINDS` に足す（足さないと `other_failure` で落ちる）。
- `webrun.js` でページに問い合わせる所を足したら、時間切れつきの口（`ask`、`within`）を通す。
- 外から渡す値に項目を足したら、`web_bridge.py` の `PROBE_KEYS` と `read_probe()`、`tests/test_web_bridge.py` に足す。
- ランタイムの版を上げたら、`fetch_runtime.py` の版の定数、`SHA256SUMS`、`requirements-dev.txt` をそろえる。
- ブラウザでしか動かないモジュール（入力の直読み、保存先、ファイルの受け渡し）も、js は引数で受け、偽の実装でテストする。

## テストと道具

- テスト `tests/test_web_bridge.py`：値がある、値が無い、形が違う、js が無い（デスクトップ版）。偽の js を渡す。
- テスト `tests/test_web_smoke.py`：判定の関数（失敗の種類ごと、線を外れた値ごと）、node が無い場合、取得と照合（一時の置き場と偽の取得の関数で通す）。ブラウザもネットワークも使わない。
- 道具 web-smoke（`python3 tools/web_smoke.py [--only shipped|probe|script|gamepad|storage_blocked] [--ticks N] [--timeout 秒]`）：筋書きは5本で、約55秒。入力の2本の決まりは `.claude/rules/controls.md`、保存（結果の `storage`）は `save.md`。
- 道具 `python3 tools/web/fetch_runtime.py [--check]`：ランタイムの写しの取得と照合。`bash tools/setup_env.sh` が呼ぶ。
- 道具 selftest-break の `web_` と `fetch_` で始まる件：ブラウザ版でだけ起きる崩れを、web-smoke が拾うこと。

## 落とし穴

- ブラウザ版では、Pythonの例外は画面の表示になるだけで、ページは落ちない。完了の合図と、エラー表示が無いことの両方を見る。
- ブラウザ版でPythonが抜けないループに入ると、ページへの問い合わせ（`page.evaluate`）が返らなくなる。時間切れを付けずに待たない。
- ランタイムは、開始のクリックより前に読み込まれる。クリックするまで、アプリは動かない（音のため）。
- 画面（canvas）はWebGLで、ページの中からは画素を読めない。スクリーンショットの画素を数える。
- JavaScriptの undefined と null は、Pyodideでは別々の物になる。値は `JSON.stringify` で文字列にしてから受け取る。
- ブラウザ版は実時間で回る。600 tickを測るのに10秒かかる。時計は0.1 ms刻み。
- 回数と時間の線は、単独で回したときの値で見る。全体の検証の中で外れたら、単独で1度回し直す。
- 取得の途中で切れた接続は `http.client.IncompleteRead` になる。`OSError` の子ではない。
