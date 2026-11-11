# 実装役への頼み：段0 区切り5「入力の土台」

> 要約：段0の区切り5を実装役に頼むための文。入力フレーム、台本、入力アダプタ、ブラウザ版の直読み、入力の注入、煙テストの筋書き2本（台本つき、偽のコントローラー）を作る。細目は主のエージェントが決めたもので、実装の途中で合わなければ、報告に書いて直す。

あなたは実装役です。リポジトリは `/home/user/clipping-point`、ブランチは `dev`。日本語で作業し、日本語で報告してください。自分で実装し、サブエージェントは呼びません。

## 最初に読むもの（この順で）

1. `CLAUDE.md`（全文）と、`docs/glossary.md` の2章と3章の「入力と操作補正」「検証」
2. `docs/design/overview.md` の「メインループ」（周期の順の5行と、表）、「入力と操作補正」の頭と「入力アダプタと入力フレーム」、「検証の仕組み」（ブラウザ版の煙テストの段落）。見出しでGrepして、その節だけ読む
3. `docs/plan.md` の「段0：立ち上げ」（区切り5の行）と「検証の組」
4. `docs/canon/planning.md` の「操作・HUD・サウンド」の操作の表（書き換えない）
5. 規則ファイル `.claude/rules/tools.md`、`.claude/rules/sim-core.md`、`.claude/rules/ui.md`、`.claude/rules/web.md`
6. いまのコード：`clipping_point/cp_app/app.py`、`web_bridge.py`、`perf.py`、`canvas_pyxel.py`、`clipping_point/cp_core/sim.py`、`clipping_point/cp_ui/screens.py`
7. いまの道具：`tools/run.py`、`tools/web_smoke.py`、`tools/web/webrun.js`、`tools/verify.py` の `AREAS`、`tools/selftest_break.py`、`tools/budgets.json`
8. 元にする試作（写して組み直す。中は直さない）：
   - `spikes/frameloop/proto/cp_proto/cp_app/input_pyxel.py`（Pyxelの読み方）と `spikes/frameloop/RESULT.json` の、入力に関わる行（81〜98行、134〜136行）
   - `spikes/web/apps/_shared/web_bridge.py` の `read_triggers`（189〜203行）
   - `spikes/web/tools/fake_gamepad.js`（偽のコントローラー）と `spikes/web/results/web_gamepad.extracted.json`（偽のコントローラーでの実測）
   - `spikes/assist/input_assist.py` の6〜12行（舵は左が正、という約束）

## 範囲

【範囲】段0 区切り5：入力の土台
【コミット】しない。gitは `status` と `diff` だけ使う。

## 主が決めた細目

試作の間で食い違っていた所と、設計に書かれていない所を、次のとおりに決めた。

| # | 決めたこと | 理由 |
| --- | --- | --- |
| 1 | 舵は左が正。Pyxelの左スティックの軸（右が正）は、入力アダプタで符号を反転する | 設計の「舵のアナログ値（−1〜1、左が正）」。試作の frameloop は右が正、assist は左が正で、食い違っていた |
| 2 | 入力フレームは、アナログ値（小数）とデジタル値（整数）を並べて持つ。どちらを使うかは決めない | 設計。決めるのは操作補正（段1） |
| 3 | 「押した瞬間」は、入力アダプタが Pyxel の `btnp`（引数なし）で読む。前のtickとの差からは作らない | 処理落ちの間の短い押し（1回の更新の中で押して離す）を落とさないため。試作の実測では、`btnp` はこの形でも真になる |
| 4 | 台本には「押している」だけを書く。「押した瞬間」は、台本を入力フレームへ直すときに、前のtickで押していなかったボタンとして導く | 台本を小さく保つ。ふつうの押し方では、3番と同じ結果になる |
| 5 | 入力を受ける側（世界、後の区切りの画面の状態）は、「押した瞬間」だけを見て動く。「押している」の立ち上がりを自分では見ない | 3番と4番で、導き方が1通りでないため |
| 6 | 台本は、入力フレームをそのまま差し込む。Pyxelの `set_btn` と `set_btnv` での注入は作らない | 設計の「台本に書いた入力フレームをそのまま差し込む」。入力アダプタを実物のPyxelで通す確かめは、台本なしで回す `run --realtime` と、偽のコントローラーの筋書きで行う |
| 7 | 世界は、受け取った入力フレームを量子化して畳み込んだ整数（入力の要約値）を持ち、要約に出す | 車がまだ無いので、入力が世界へ順のまま届いたことを、ほかに確かめられない |
| 8 | 量子化は、アナログ値を千分率の整数に丸める（`round(x * 1000)`）。ボタンは `BUTTONS` の並びのビット | 比較は整数で行う。丸めの前の計算は、掛け算と割り算だけにする（デスクトップ版とブラウザ版で同じ結果になる） |
| 9 | メニュー操作の割り当て：決定は Z、Enter、Aボタン、START。戻るは X、Esc、Bボタン。上下左右は矢印キーと十字キー | 設計は「上下左右、決定、戻る」までで、割り当てを決めていない。左スティックでのメニュー操作と、長押しの繰り返しは、画面の状態を作る区切りで決める |
| 10 | Esc は、ポーズと戻るの両方に入れる。Enter と START は、ポーズと決定の両方に入れる。どちらを読むかは、画面の状態が決める | 設計の「EscはEnterと同じくポーズに使う」 |
| 11 | ブラウザ版で直読みができたtickは、Pyxel経由のトリガーを読まない | Pyxel経由は2値で届く。デジタル値の側へ入れると、アナログで踏んでいるのにデジタル操作と見なされる |
| 12 | 直読みは、枠の先頭から見て、最初の空でない枠だけを見る。その枠が標準の並びでなければ、直読みしない | Pyxelの「ゲームパッド1」と同じコントローラーを見るため |
| 13 | ペダルの割り当ての切り替え（TRIGGER、BUTTON、R-STICK）は作らない。いまは TRIGGER の形だけ | 計画の段1 区切り4（入力と操作補正）で、操作設定と一緒に作る。入力フレームの形は変わらない |
| 14 | 偽のコントローラーは、アプリが置く tick の印（`window.CP_PROBE_TICK`）を見て、予定を進める。実時間では進めない | 開始のクリックからアプリが動き始めるまでの時間が決まらないため。tick に合わせれば、どのtickで何が見えるはずかを決められる |
| 15 | 規則ファイルは `.claude/rules/controls.md` を足す（入力フレーム、台本、入力アダプタ、直読み、偽のコントローラー）。`web.md` と `tools.md` は上限（6,000バイト）に近いので、足すのは筋書きの数など、要る所だけにする | 計画の分野の表の「controls：操作補正、その定義データ、入力の取り込み」 |

## やること

### 1. 入力フレーム（`clipping_point/cp_core/input_frame.py`）

- `BUTTONS = ("shift_up", "shift_down", "view", "pause", "up", "down", "left", "right", "confirm", "back")`。並びは量子化のビットの順。足すときは末尾に足す。
- `InputFrame`（書き換えられない dataclass）。
  - `steer_analog`：小数、−1〜1、左が正。`steer_digital`：整数、−1、0、1、左が正。
  - `throttle_analog`、`brake_analog`：小数、0〜1。`throttle_digital`、`brake_digital`：整数、0か1。
  - `held`、`pressed`：ボタンの名の `frozenset`（押している、押した瞬間）。
  - 既定はすべて0と空。作るときに、型、範囲、NaN、知らない名前を検査する（`TypeError` か `ValueError`）。デジタル値に bool と小数を受けない。
- `NEUTRAL`：何も押していない入力フレーム。
- `quantize(frame)`：8個の整数の組を返す。順は、舵のアナログ値、舵のデジタル値、アクセルのアナログ値、アクセルのデジタル値、ブレーキのアナログ値、ブレーキのデジタル値、`held` のビット、`pressed` のビット。
- `fold(digest, values)`：整数の列を、32ビットの整数に畳み込む。式は `digest = ((digest ^ (v & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF` を値ごとに。始まりの値は `DIGEST_START = 2166136261`。

### 2. 台本（`clipping_point/cp_core/input_script.py`）

- 形は、JSONにそのまま書ける辞書：`{"segments": [{"ticks": 30, "steer_analog": 0.5, "throttle_digital": 1, "held": ["shift_up"]}, …]}`。
  - `ticks`（必須、1以上の整数）は、その入力が続くtick数。ほかの鍵は、入力フレームの6つの値と `held`。省けば0と空。`pressed` は書けない。
  - 知らない鍵、型の違い、範囲の外、空の `segments` は `ValueError`。
- `parse(value)` が、検査済みの台本を返す。`frame_at(tick)` が、tick（0始まり。世界のtickが n のときに渡すのが n 番目）の入力フレームを返す。台本を過ぎたら `NEUTRAL`。`total_ticks` を持つ。
- `pressed` は、区間の最初のtickで、前の区間（頭なら何も押していない状態）で押していなかったボタン。
- ファイルを読むのは `cp_app` と道具。`cp_core` は辞書を受けるだけにする。

### 3. 世界（`clipping_point/cp_core/sim.py`）

- `Sim.step(frame)`。引数は必須。`InputFrame` でなければ `TypeError`。
- `Sim.input_digest`（始まりは `DIGEST_START`）。毎tick、`fold(self.input_digest, quantize(frame))` で進める。`Sim.summary()` に `input_digest` を足す。
- 畳み込みの所に、割り切りの印を付ける：車が無い間、入力が届いたことを見るための仕組み。指紋の形を作る段0 区切り7で、指紋に入れるかを見直す。

### 4. 入力アダプタ（`clipping_point/cp_app/input_pyxel.py`）と直読み（`clipping_point/cp_app/input_web.py`）

どちらのモジュールも、pyxel と js をimportしない。引数で受ける（偽の実装でテストするため）。

- `input_pyxel`：キーの対応は、Pyxelの定数の名前（文字列）の表で持つ。作るとき（起動時）に、全部の名前を `getattr` で引く（無い名前は、起動時に落ちる）。
  - 読み方は、ボタンとキーが `btn`（押している）と `btnp`（押した瞬間）、軸が `btnv`。取り違えると、Pyxelの中で落ちる。
  - 割り当ては次の表。同じキーが2つの値に入る所がある（矢印の左右は舵とメニュー、Z は アクセルと決定）。

| 入力フレームの値 | キーボード | ゲームパッド1 |
| --- | --- | --- |
| 舵のデジタル値（左が+1、右が−1、両方は0） | `KEY_LEFT`、`KEY_RIGHT` | `BUTTON_DPAD_LEFT`、`BUTTON_DPAD_RIGHT` |
| 舵のアナログ値 | なし | `AXIS_LEFTX`。`-値 / 32767` を −1〜1 に丸める |
| アクセルのデジタル値 | `KEY_Z` | `BUTTON_A` |
| ブレーキのデジタル値 | `KEY_X` | `BUTTON_B` |
| アクセルのアナログ値 | なし | 右トリガー（下の3通り） |
| ブレーキのアナログ値 | なし | 左トリガー（下の3通り） |
| `shift_up` | `KEY_S` | `BUTTON_X` |
| `shift_down` | `KEY_A` | `BUTTON_Y` |
| `view` | `KEY_C` | `BUTTON_BACK` |
| `pause` | `KEY_RETURN`、`KEY_ESCAPE` | `BUTTON_START` |
| `up`、`down`、`left`、`right` | `KEY_UP`、`KEY_DOWN`、`KEY_LEFT`、`KEY_RIGHT` | `BUTTON_DPAD_UP`、`BUTTON_DPAD_DOWN`、`BUTTON_DPAD_LEFT`、`BUTTON_DPAD_RIGHT` |
| `confirm` | `KEY_Z`、`KEY_RETURN` | `BUTTON_A`、`BUTTON_START` |
| `back` | `KEY_X`、`KEY_ESCAPE` | `BUTTON_B` |

  - トリガーの読み方は3通り。読む関数は、ブラウザ版かどうかと、直読みの結果を引数で受ける。
    - デスクトップ版：`btnv(AXIS_TRIGGERRIGHT) / 32767` と `btnv(AXIS_TRIGGERLEFT) / 32767` を 0〜1 に丸めて、アナログ値に入れる。
    - ブラウザ版で、直読みができた：直読みの値（左がブレーキ、右がアクセル）を 0〜1 に丸めて、アナログ値に入れる。Pyxel経由のトリガーは読まない。
    - ブラウザ版で、直読みができない：Pyxel経由のトリガーが0より大きければ、デジタル値を1にする。アナログ値は0のまま。
  - 値の範囲をそろえるだけにする。遊びの除去と応答カーブは入れない（操作補正に置く）。
- `input_web`：ブラウザのGamepad APIから、トリガーを直読みする。js は引数で受ける。js が `None`（デスクトップ版）なら、いつも `None` を返す。
  - `navigator.getGamepads()` の枠を先頭から見て、最初の空でない枠を使う。その枠が、標準の並び（`mapping` が `standard`）で、ボタンが8個以上なら、`(ボタン6の value, ボタン7の value)`（左、右）を返す。そうでなければ `None`。
  - 未接続（枠が全部空、枠が0個）、途中の切断、標準でない並び、ボタンの不足、`getGamepads` が無い、呼ぶと例外になる（埋め込み先が入力を許していない）のどれでも、例外を外へ出さずに `None` を返す。例外を捕まえたときは、最初の1度だけ `console.warn` で知らせる。
  - 空の枠は、Pyodideでは `None` でなく別の物（jsnull）に見えることがある（保存先での実測）。見分け方を、偽の js と、偽のコントローラーの筋書きの両方で確かめる。
  - 1 tickに呼ぶのは1度だけ。

### 5. アプリ（`clipping_point/cp_app/app.py`、`web_bridge.py`）と仮の表示

- `App.update()` の順：入力フレームを1度だけ作る（台本があれば台本の `frame_at(世界のtick)`、無ければ入力アダプタ）→ `sim.step(frame)` → 入力の跡を取る（頼まれたときだけ）→ 回した更新の数を進める → tickの印を置く（頼まれたときだけ）。
- デスクトップ版の、画面なしで回す口に足す。
  - 環境変数 `CP_SMOKE_SCRIPT=<台本のJSONファイルの絶対パス>`。`CP_SMOKE` があるときだけ読む。相対パス、読めないファイル、形の違う台本は、起動時に例外にする。
  - 結果ファイルに `input_source`（`"script"` か `"adapter"`）と `adapter_reads`（入力アダプタを呼んだ回数）を足す。
- ブラウザ版の、外から渡す値（`window.CP_PROBE`）に、2つ足す。
  - `script`：台本（辞書）。省くか null なら、入力アダプタから読む。形が違えば `ValueError`。
  - `trace_max`：0以上の整数（省けば0）。1以上なら、入力の跡を、この件数まで取る。あわせて、更新のたびに `window.CP_PROBE_TICK` へ、回した更新の数を置く。
  - 結果の1行に、`input_source`、`adapter_reads` と、`trace_max` が1以上のときは `inputs` を足す。形は `{"changes": [[tick, [量子化した8個の整数]], …], "truncated": false}`。`changes` は、量子化した値が前のtickと違ったtickだけを並べる（頭のtick 0は必ず入る）。件数が `trace_max` に届いたら、`truncated` を true にして、後は取らない。
- 入力の跡を取る所は、`clipping_point/cp_app/input_trace.py` に置く。pyxel も js もimportしない（`perf.py` と同じ扱い）。
- 仮の表示（`cp_ui/screens.py` の `build_placeholder`）に、入力フレームの値を出す2行を足す。1行目は舵、アクセル、ブレーキのアナログ値とデジタル値、2行目は押しているボタンの名（大文字）。英数字と記号だけにし、画面の内に収める（10個とも押した状態でも）。実機で、実物のコントローラーの値を見ていただくための表示。

### 6. 道具

- `tools/input_script_smoke.json`：道具が使う台本。合計は100 tick以内。舵、アクセル、ブレーキのアナログ値とデジタル値、10個のボタンのどれも、1度は0でない値になること。同じボタンを、間を空けて2度押す区間を入れる（押した瞬間が2度立つこと）。
- 台本から、純Pythonで世界の要約を計算する関数（参照）を、道具の側に1つ置く（`cp_core` をimportして、`Sim` に `frame_at` の入力フレームを流す）。`run.py` と `web_smoke.py` の両方が使う。同じ計算を2か所に書かない。
- `tools/run.py`
  - 既定（速い経路）は、上の台本を `CP_SMOKE_SCRIPT` で渡して回す。足す確かめ：`input_source` が `script`。世界の要約が、参照と同じ。
  - `--realtime` は、台本を渡さずに回す（入力アダプタを、実物のPyxelで毎tick呼ぶ）。足す確かめ：`input_source` が `adapter`。`adapter_reads` が回したtickと同じ。世界の要約が、何も押していない入力での参照と同じ。
  - 最後の1行に `input=script|adapter` を足す。引数 `--script FILE` と `--no-script` で、どちらの経路でも入れ替えられるようにする。
- `tools/web_smoke.py`：筋書きを2本足す（`SCENARIOS` は `shipped`、`probe`、`script`、`gamepad` の順）。どちらも、処理時間と回数の線は見ない（見るのは `probe`）。慣らしは0。
  - `script`：`window.CP_PROBE` に、回すtick数、上の台本、`trace_max` を置いて開く。見るもの：どの筋書きでも見ること（`page_checks`）、ブラウザ版であること、回したtick、`input_source` が `script`、世界の要約が、デスクトップ版（同じ台本を渡して回した）と同じで、参照とも同じ、入力の跡が、台本を入力フレームへ直して量子化した列と、全tickで同じ、入力の跡が打ち切られていない。
  - `gamepad`：差し込むスクリプトは、予定を置く1行（`window.CP_FAKE_PAD_PLAN = …`）と、`tools/web/fake_gamepad.js` の中身をつないだもの。`window.CP_PROBE` には、回すtick数と `trace_max` を置く（台本は渡さない）。予定と、判定に使う値は、`web_smoke.py` の1か所に持つ。
    - 予定の段（各段の長さは `tools/budgets.json` の値。下の8段）：
      1. 未接続（枠が全部空）
      2. 標準の並び。軸もボタンも0
      3. 右トリガー（ボタン7）が0.3
      4. 右トリガーが1.0、左トリガー（ボタン6）が0.6
      5. トリガーは0。左スティックを左いっぱい（軸0が−1）、Aボタン（ボタン0）、十字キーの上（ボタン12）
      6. 切断（枠が全部空）
      7. 標準でない並び（`mapping` が空の文字列）。ボタン6が0.6、ボタン7が1.0
      8. 切断
    - 見るもの：`page_checks`（例外が出ていないこと）、ブラウザ版であること、回したtick、`input_source` が `adapter`、`adapter_reads` が回したtickと同じ、入力の跡が打ち切られていない、入力の跡から計算し直した入力の要約値が、世界の要約と同じ（アプリが読んだ入力フレームが、そのまま世界へ渡っている）。
    - 段ごとに、頭の数tick（`tools/budgets.json` の値）を除いた全tickで、入力の跡から戻した値が次のとおり：
      - 段1、2、6、8：全部0。
      - 段3：アクセルのアナログ値が300。アクセルのデジタル値は0。
      - 段4：アクセルのアナログ値が1000、ブレーキのアナログ値が600。デジタル値は0。
      - 段5：舵のアナログ値が+1000、アクセルのデジタル値が1、`held` に `up` と `confirm` がある。アクセルとブレーキのアナログ値は0。
      - 段7：アクセルとブレーキのアナログ値が0。デジタル値と `held` は判定に入れず、見えた値を最後の1行に出す（標準でない並びが、Pyxel経由でどう届くかは、分かっていない）。
    - `pressed` に `confirm` が立つのは、段5の頭の1 tickだけ。
- `tools/web/fake_gamepad.js`：`navigator.getGamepads` を差し替える。呼ばれるたびに `window.CP_PROBE_TICK`（無ければ0）を見て、予定の段を選ぶ。段が替わって、空から接続へ変わったら `gamepadconnected`、接続から空へ変わったら `gamepaddisconnected` を、`window` へ送る（`getGamepads` の中から直に送らず、後回しにして送る）。ボタンは17個、軸は4個。`pressed` は、試作と同じく値が0.1を超えたら真。
- `tools/budgets.json`：足す値に、仮の値の注を付ける（`script` で回すtick数、`gamepad` の段の長さ、段の頭で判定しないtick数、入力の跡の件数の上限）。
- `tools/verify.py` の `AREAS`：分野「操作補正と入力」を足す（入力フレーム、台本、入力アダプタ、入力の跡と、そのテスト。足す手順は run と web-smoke）。`input_web.py` とそのテストは「ブラウザ連携」に足す。
- `tools/selftest_break.py`：壊す件を足す。少なくとも次の形。件の時間を縮めるため、ブラウザを開く件は要るものに絞る。
  - アプリが、入力フレームの代わりに `NEUTRAL` を世界へ渡す（`run` が1）
  - 台本を1 tickずらして読む（`run` が1）
  - 入力アダプタを1 tickに2度呼ぶ（`run --realtime` が1）
  - 軸のキーを `btn` で読む（`run --realtime` が1。落ち方は実測して、期待を決める）
  - 舵のアナログ値の符号を反転しない（`test` が1、`web_smoke --only gamepad` が1）
  - 左右のトリガーを取り違える（`web_smoke --only gamepad` が1）
  - 直読みができたtickに、Pyxel経由のトリガーをデジタル値へ入れる（`web_smoke --only gamepad` が1）
  - 空の枠を見分けずに属性を読む（`web_smoke --only gamepad` が1）
  - ブラウザ版でだけ、台本を読まずに入力アダプタから読む（`web_smoke --only script` が1）
  - 入力の跡が打ち切られる（`trace_max` が小さい。合格にしない）
  - 古い結果ファイルが残っている（合格にしない。いまの件の形に合わせる）

### 7. 規則ファイルとテスト

- `.claude/rules/controls.md` を足す。書式は、いまの4つにそろえる（約束、値を読む口、Xを足したらYも、テストと道具、落とし穴）。当て先は、入力フレーム、台本、入力アダプタ、直読み、入力の跡、偽のコントローラーと、そのテスト。根のCLAUDE.mdの「規則ファイルの目次」に1行足す（直してよいのは、この表だけ）。
- `.claude/rules/web.md`、`tools.md`、`sim-core.md` は、変えた所に合わせて直す（筋書きの数、`Sim.step()` の引数、外から渡す値の項目）。上限を超えるなら、入力の決まりを `controls.md` へ寄せる。それでも収まらなければ、直さずに報告に書く。
- テスト：
  - `tests/test_input_frame.py`：範囲と型の検査、量子化、畳み込み（同じ列から同じ値、順を替えると違う値）。
  - `tests/test_input_script.py`：入力フレームへの直し方、押した瞬間が区間の頭の1 tickだけ立つこと、間を空けた2度押し、台本を過ぎたら `NEUTRAL`、形の検査。道具の台本（`tools/input_script_smoke.json`）が、上の「どれも1度は0でない」を満たすこと。
  - `tests/test_input_pyxel.py`：偽の pyxel を渡す。割り当ての表のとおりに読むこと（正本の操作の表と照らす）、舵の符号、丸め、軸のキーを `btn` で読まないこと（偽の pyxel が例外を出す）、トリガーの3通り、無い定数の名前で起動時に落ちること。
  - `tests/test_input_web.py`：偽の js を渡す。標準の並び、未接続、空の枠、途中の切断、標準でない並び、ボタンの不足、`getGamepads` が無い、例外、js が `None`。
  - `tests/test_input_trace.py`：変わり目だけを取ること、打ち切り、戻した列が元と同じこと。
  - `tests/test_sim.py`、`tests/test_web_bridge.py`、`tests/test_web_smoke.py`、`tests/test_screens.py`：変えた所に合わせて足す（`step` の引数、入力の要約値、外から渡す値の2項目、2本の筋書きの判定の関数、仮の表示の2行）。

## 実測して、報告に書くこと

- 空の枠が、ブラウザ版のPythonからどう見えるか（`None` か、別の物か）。
- 標準でない並びのコントローラーが、Pyxel経由でどう届くか（段7で見えたデジタル値と `held`）。
- 軸のキーを `btn` で読んだときの、デスクトップ版（画面なし）での落ち方。
- `probe` の筋書きの、更新1回の時間（95%点）が、入力アダプタと直読みを入れる前後でどう変わったか。
- `web_smoke.py` の全体と、`verify.py --all`、`selftest_break.py` にかかった秒数。

## 回す検証

1本ずつ回す：`python3 tools/check.py`、`python3 tools/test.py`、`python3 tools/run.py`、`python3 tools/run.py --realtime`、`python3 tools/export.py`、`python3 tools/web_smoke.py`、最後に `python3 tools/verify.py --all --selftest`。各道具の最後の1行を、そのまま報告に写す。

## 範囲の外（直さずに報告する）

- 操作補正、ペダルの割り当ての切り替え、操作設定（段1 区切り4）。画面の状態とメニュー（後の区切り）。左スティックでのメニュー操作と、長押しの繰り返し。
- はみ出しの検査と巡回（区切り6）。保存、乱数、指紋（区切り7）。定義データ（区切り8）。車とコース（区切り9、10）。
- 何も渡さずに開く筋書き（`shipped`）を、タイトルまで進める形にすること。
- `docs/` の文書（言葉の表には、主が「直読み」「標準の並び」「入力の要約値」「入力の跡」「偽のコントローラー」を足してある）と、根のCLAUDE.mdの「規則ファイルの目次」の表のほかの節。直す必要があれば、何をどう直すかを報告に書く。
- `spikes/` の中。

## 書き方の約束

- 根のCLAUDE.mdの「書き方の約束」と、言葉の表の決めを守る（「写し」「記録」「枠」「モデル」は単独で使わない。入力フレームの中の値は「アナログ値」「デジタル値」）。
- 出荷するコードに置く仮の値には、`# 仮の値：<根拠>。<合わせる時>` の注を付ける。道具の値は `tools/budgets.json` に出す。
- 新しいパッケージは入れない。テストを通すためだけの特別扱いをしない。落ちるテストを弱めない。

## 報告の形

1. 変えたファイル（作ったものは、ディスクにあることを確かめてから書く）
2. 設計と、この文の細目からのずれ・変えた値・新しく足した割り切り
3. 回した検証（各道具の最後の1行と件数）
4. 回せなかったこと・確かめられなかったこと・範囲の外で直す必要がある所（無ければ「無し」）
5. 推奨の案で決めた細目
6. 「実測して、報告に書くこと」の5点
