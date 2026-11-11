# 実装役への頼み：段0 区切り3「環境とブラウザ版の煙テスト」

> 要約：段0の区切り3を実装役に頼むための文。週の使用率が90%に届いたので、頼まずに置いてある。再開したら、週の使用率とClaudeのモデルを確かめてから、この文をそのまま実装役に渡す。細目は主のエージェントが決めたもので、実装の途中で合わなければ、報告に書いて直す。

あなたは実装役です。リポジトリは `/home/user/clipping-point`、ブランチは `dev`。日本語で作業し、日本語で報告してください。自分で実装し、サブエージェントは呼びません。

## 最初に読むもの（この順で）

1. `CLAUDE.md`（全文）と `docs/glossary.md` の2章
2. `docs/design/overview.md` の「メインループ」の末尾（ブラウザ版でタブが隠れたときの段落まで）、「検証の仕組み」、「ビルドと配布」。見出しでGrepして、その節だけ読む
3. `docs/plan.md` の「段0：立ち上げ」（区切り3の行と通過条件）と「検証の組」
4. 規則ファイル `.claude/rules/tools.md`、`.claude/rules/sim-core.md`、`.claude/rules/ui.md`
5. いまの道具：`tools/_common.py`、`tools/run.py`、`tools/export.py`、`tools/selftest_break.py`、`clipping_point/cp_app/app.py`
6. 元にする試作：`spikes/web/tools/webrun.js`（合否の判定つきのブラウザ実行）、`spikes/web/tools/fetch_runtime.sh` と `build_mirror.sh`（ランタイムの写しの取得と組み立て）、`spikes/web/vendor/SHA256SUMS`（照合用の一覧）、`spikes/harness/repo/tools/web_smoke.py` と `verify.py`、`spikes/web/RESULT.json` の `recommendations`

`spikes/` の中は直しません。写して組み直します。

## 範囲

【範囲】段0 区切り3：環境とブラウザ版の煙テスト
【コミット】しない。gitは `status` と `diff` だけ使う。

## やること

### 1. 版を固定した依存の一覧と、環境のセットアップ

- `requirements-dev.txt`：`pyxel==3.0.1`、`pytest==9.2.0`。
- `tools/web/fetch_runtime.py`：ランタイムの写しを `.cache/pyxel_web/` に取得し、`tools/web/SHA256SUMS` と照合し、写しを組み立てる。取得元は `raw.githubusercontent.com/kitao/pyxel/v3.0.1/wasm/` と `registry.npmjs.org/pyodide/-/pyodide-314.0.7.tgz` だけ。kitao.dev と cdn.jsdelivr.net には触れない。照合が合わなければ1、取得できなければ2。既にそろっていて照合が通れば、取得し直さない。
- `tools/setup_env.sh`：新しいコンテナで1度回すスクリプト。`python3 -m pip install -r requirements-dev.txt` と `python3 tools/web/fetch_runtime.py`。何度回しても同じ結果になること。対話を求めないこと。
- 環境への登録は、主のエージェントが行う（承認の画面が出る）。実装役は登録しない。登録する文は、報告に案として書く。形は次のとおり：`if [ -f clipping-point/tools/setup_env.sh ]; then (cd clipping-point && bash tools/setup_env.sh) || echo "clipping-point: setup failed"; fi`

主のエージェントが試した結果：いまの環境から、取得は約3秒、約26 MBで、照合は通った。PyxelとpytestはPyPIから約10秒で入る。追加のネットワークの許可は要らない。

### 2. ブラウザ版の煙テスト（道具 web-smoke）

- `tools/web/webrun.js`：ヘッドレスのChromiumでHTMLを開き、コンソール、ページのエラー、読み込みの失敗を集めて、結果をJSONに書く。ランタイムへの要求は、写しへ差し替える（写しの外へ出る要求は失敗にする）。Playwrightは環境に入っているものを使う。
- `tools/web_smoke.py [--only <筋書き>]`：筋書きを順に回す。終了コードと最後の1行は、ほかの道具とそろえる。写しが無い、nodeが無い、ビルドできない場合は2（合格にしない）。
- 開くのは、`tools/export.py` が作った `dist/clipping_point.html` そのもの（同じバイト列）。煙テスト用に作り直したHTMLを開かない。
- 筋書きは2本。
  - `shipped`：何も渡さずに開く。見るもの：Pythonの例外が無い、エラー表示が無い、読み込みの失敗が無い、決めた秒数の間に画面が描かれている（画面の画素が背景だけでない）。
  - `probe`：ページを開く前に差し込むスクリプトで、回すtick数を置いて開く（例：`window.CP_PROBE = {ticks: 600}`）。アプリは、ブラウザ版でこの値を読めたら、決まったtickの後に、コンソールへ結果の1行（JSON）と完了の合図を出す。見るもの：回したtick、世界の要約がデスクトップ版と同じ、実描画の回数、更新と実描画の毎秒の回数、更新1回と実描画1回の時間（95%点）、ブラウザ版であること（`sys.platform` が `emscripten`）、Pythonの版。
- 処理時間と回数の線は `tools/budgets.json` に置く（更新が毎秒59回以上、実描画が毎秒29回以上、更新1回が4 ms以内、実描画1回が12 ms以内）。段0の通過条件は走行の場面（区切り10）で見るので、いまは仮の表示で測る。
- アプリの側：外から渡された値を読む所は `clipping_point/cp_app/web_bridge.py` に置く。ブラウザの機能（jsのモジュール）は引数で受け、偽の実装を渡してテストできる形にする。ブラウザ版では `sys.exit` と `pyxel.quit` を呼ばない。値が無ければ、ふつうに起動する。
- 更新1回と実描画1回の時間を測る所は `cp_app` に置く。測った値を世界（`Sim`）へ渡さない。
- 実描画の回数で、アプリが実時間を `RenderGate` へ渡していることも見る（`.claude/rules/sim-core.md` の最後の行）。

### 3. 道具 verify

- `tools/verify.py --all`：check → test → run → run --realtime → export → web-smoke を、この順で1本ずつ回し、表を1つ出す。1つ落ちても最後まで回し、落ちたものがあれば失敗にする。回らなかった手順は失敗に数える。`--selftest` を付けると、最後に selftest-break も回す。
- `tools/verify.py --touched`：変更したファイル（`git diff --name-only <基点>` と未コミットの分）から、触れた分野を引く。分野ごとの組の表は、このファイルの1か所にだけ持つ。全体が3分を超えるまでは、どの分野でも全体を回す（表と、ファイルから分野を引く仕組みは置く）。
- `tools/verify.py --list`：分野ごとの組の表を出す。
- 出荷するコード（`clipping_point/`）とテスト（`tests/`）のすべてのファイルが、どれかの分野か「全部」に当たることを、check で見張る。当たらないファイルがあれば1。

### 4. 規則ファイル、テスト、壊す件

- `.claude/rules/web.md`（当て先：`clipping_point/cp_app/web_bridge.py`、`tools/web/**`、`tools/web_smoke.py`、そのテスト）。書式は、いまの3つの規則ファイルにそろえる（約束、値を読む口、Xを足したらYも、テストと道具、落とし穴）。根のCLAUDE.mdの「規則ファイルの目次」に1行足す（直してよいのは、この表だけ）。
- テスト：`web_bridge` の、値がある、値が無い、形が違う、jsが無い（デスクトップ版）の場合。verify の、ファイルから分野を引く所。
- `tools/selftest_break.py` に壊す件を足す。少なくとも：ブラウザ版でだけ起きるPythonの例外（web-smoke が1）、完了の合図が出ない（2）、ランタイムの写しが無い（2）、写しの外への要求（1）、tickが足りない（1）、世界の要約がデスクトップ版と違う（1）、verify の中の1本が落ちる（verify が1）、どの分野にも当たらないファイル（check が1）、古い結果ファイルが残っている（合格にしない）。

## 回す検証

1本ずつ回す：`python3 tools/check.py`、`python3 tools/test.py`、`python3 tools/run.py`、`python3 tools/run.py --realtime`、`python3 tools/export.py`、`python3 tools/web_smoke.py`、`python3 tools/verify.py --all`、`python3 tools/selftest_break.py`。各道具の最後の1行を、そのまま報告に写す。全体の検証にかかった秒数も書く。

## 範囲の外（直さずに報告する）

- サブエージェントの型と Claude Codeの設定（区切り4）。入力（区切り5）。はみ出しの検査と巡回（区切り6）。保存、乱数、指紋（区切り7）。定義データ（区切り8）。車とコース（区切り9、10）。
- `docs/` の文書と、根のCLAUDE.mdの「規則ファイルの目次」の表のほかの節。直す必要があれば、何をどう直すかを報告に書く。
- `spikes/` の中。環境への登録。

## 書き方の約束

- 根のCLAUDE.mdの「書き方の約束」と、言葉の表の決めを守る（「写し」「記録」「枠」「モデル」は単独で使わない。道具は「ラッパー」と書かない）。
- 新しいパッケージは入れない（Pyxel、pytest、Playwrightは入っている）。
- テストを通すためだけの特別扱いをしない。落ちるテストを弱めない。

## 報告の形

1. 変えたファイル（作ったものは、ディスクにあることを確かめてから書く）
2. 設計からのずれ・変えた値・新しく足した割り切り
3. 回した検証（各道具の最後の1行と件数）
4. 回せなかったこと・確かめられなかったこと・範囲の外で直す必要がある所（無ければ「無し」）
5. 推奨の案で決めた細目
6. 環境に登録するスクリプトの案と、根のCLAUDE.mdの「コマンド」の表に足す行の案
