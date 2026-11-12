---
paths:
  - "clipping_point/cp_ui/**"
  - "clipping_point/cp_core/flow.py"
  - "clipping_point/cp_app/canvas_pyxel.py"
  - "clipping_point/cp_app/tour.py"
  - "tools/screen_check.py"
  - "tools/tour.py"
  - "tests/test_canvas.py"
  - "tests/test_screens.py"
  - "tests/test_ui_check.py"
  - "tests/test_fixtures.py"
  - "tests/test_flow.py"
  - "tests/test_tour.py"
  - "tests/test_screen_tools.py"
---

# 2Dの描画（cp_ui、描画命令の実行、はみ出しの検査と巡回）

## 約束

- 2Dの描画は必ず `cp_ui.canvas.Canvas` の描画命令を通す。Pyxelの描画関数を直に呼ばない。
- 画面は `(canvas, 表示用の値)` を受ける関数。`cp_ui/screens.py` に置き、`SCREENS` に登録する。`cp_app` は、画面の状態（`cp_core/flow.py`）の名で引いて呼ぶだけ。
- 表示用の値は、画面ごとの、書き換えられない dataclass。型は `cp_core/flow.py` に置く。
- `Canvas` は描画命令を呼ばれた順にためるだけ。命令は色を含めて持つ。描くのは `cp_app.canvas_pyxel.execute()`。
- パネル、一覧の行、HUDのまとまりは、囲み（`with canvas.box(名, x, y, w, h):`）にする。囲みは何も描かず、入れ子にできる。
- `cp_ui` は pyxel、js、`cp_app`、`random`、`time` をimportしない。`cp_core` は呼んでよい。
- 座標、大きさ、色の番号は整数。小数と bool は `TypeError`。引数の並びは、Pyxelの同名の関数と同じ。
- 画面に出す文字は、印字できるASCII（文字の番号が32〜126）と改行だけ。
- 仮の表示の知らせの1行：`PlaceholderView.notice` は省けない項目（無ければ空の文字列。渡し忘れると、作る時に落ちる）。空でないときだけ、囲み `notice` を作って1行で出す（収まるのは78字まで）。文は `cp_core/storage.py` の `NOTICES` に置く（決まりは `.claude/rules/save.md`）。
- 仮の表示の車の値の2行：`PlaceholderView.car`（`CarView`。省けない）。値は、整数と文字列だけ（速度は km/h の整数、位置は 0.1 m 刻みの整数、後退のギアは −1）。世界から作るのは `cp_core/flow.py` の `car_view()`。描く側で、小数を丸めない。
- 仮の表示の処理時間の2行：`PlaceholderView.perf`（`PerfView`。省けない）。値は、0.1 刻みの整数か None（測れていない。「-」と出す）。作るのは `cp_app/perf.py` の `view_of()`（桁いっぱいで頭打ち。桁は `screens.py` の `MS_DIGITS` など）。
- 仮の表示は、3Dの絵の上に重ねる。上の帯と下の帯に分け、画面の中ほどを隠さない。文字の後ろに、囲みごとに、暗い矩形を敷く。色の番号は、役割の名（`cp_core/palette.py`）で引く。
- `cp_app/canvas_pyxel.py` と `cp_app/tour.py` は pyxel をimportしない。描く先とPyxelは引数で受ける。
- 巡回の口は、デスクトップ版で、環境変数 `CP_TOUR` があるときだけ動く。結果ファイルは、全部の画面を回した後にだけ書く。合否は `tools/tour.py` が決める。

## 値を読む口

- 画面と文字の大きさ：`cp_ui/canvas.py` の `SCREEN_W`、`SCREEN_H`、`FONT_W`、`FONT_H`、`text_size()`（インクの箱）
- 描画命令（`text`、`rect`、`rectb`、`line`）：`Canvas.commands`。種類は `kind`、矩形は `bounds`、囲みの番号は `box`（−1 は画面）。囲みは `Canvas.boxes`
- はみ出しの種類：`cp_ui/check.py` の `KINDS`。数えるのは `find_violations()`
- 画面の名：`cp_core/flow.py` の `SCREEN_NAMES`。見本データ：`cp_ui/fixtures.py` の `VARIANTS`、`build()`
- 仮の表示の文字と色：`cp_ui/screens.py` の `TITLE`、`COL_BACK`、`COL_BAR`、`COL_PANEL`、`COL_TEXT`、`COL_EDGE`。字は `car_lines()`、`perf_lines()`
- 巡回の環境変数、余白、結果の形：`cp_app/tour.py` の頭の注。画像は `out/tour/<画面の名>_<変種>.png`

## Xを足したらYも

- 描画命令の種類を足したら、`cp_ui/canvas.py`（クラス、`bounds`、`Canvas` の口）、`cp_app/canvas_pyxel.py`、`tests/test_canvas.py`、`tests/test_tour.py` の偽の画像に足し、どれかの画面で使う（使わない種類は、実物の画素と照らされない）。
- 画面を足したら、`cp_core/flow.py`（`SCREEN_NAMES`、表示用の値の型）、`cp_ui/screens.py`（関数、`SCREENS`）、`cp_ui/fixtures.py`（`BUILDERS`。2つの変種）、テストに足す。`screen_check.py --only 名` と `tour.py --only 名` を回し、画像を見る。
- はみ出しの種類か、巡回の判定を足したら、`tools/selftest_break.py` に壊す件を足す。
- パレットは、場面の `build()` が当てる（`render.md`）。巡回の口も、そこを通す。

## テストと道具

- テスト：`test_canvas.py`（命令、囲み、文字の大きさ、ずらし）、`test_ui_check.py`（6種類、端に接する矩形、入れ子）、`test_screens.py` と `test_fixtures.py`（全画面×全変種が、はみ出し無し。突き合わせ）、`test_flow.py`、`test_tour.py`（画素を照らす関数。巡回の流れは偽の Pyxel で通す）、`test_screen_tools.py`（2本の道具の判定）。
- 突き合わせ：ロジックの画面の名、`SCREENS` の鍵、見本データのある画面が、同じ集まり。
- 守りのテスト（`tests/test_screens.py` の `test_screens_app_…`。`app.py` のソースを読む。道具からは見えない配線）：仮の表示へ、世界へ渡したのと同じ入力フレーム、知らせ（結果の知らせも、表示用の値から取る。道具では、筋書き `storage_blocked` でしか落ちない）、進めている世界の車の値（`car_view(self.sim)`）、処理時間の輪の値（`view_of()`）が、渡っていること。段1で、入力で画面を進める巡回に置き換える。
- 走る台本と壁の台本の全tickで、仮の表示を組み立てられること（後退、芝、壁）は、`tests/test_screens.py` と `tests/test_flow.py`、道具の `run-drive` と `run-wall` が見る。
- 道具 `python3 tools/screen_check.py [--only 名]`：全画面×全変種を、Pyxelなしで組み立て、はみ出しを数える。
- 道具 `python3 tools/tour.py [--only 名|scene]`：実物のPyxelで、命令を1つずつ描き、矩形の外の画素と、内に画素が無い命令を数える。余白の画素、画像の大きさ、照らした命令の数も見る。3Dの絵（`scene`）は `render.md`。
- 道具 `python3 tools/run.py`：アプリが描く道（`app.py` の `render()`）の、2Dの描画命令の矩形の内の画素を見る（確かめ `back_ink`）。
- 道具 `python3 tools/test.py`：`cp_app` の2つのモジュールが pyxel を読み込むと、`reason=pyxel_loaded` で落ちる。

## 落とし穴

- 内蔵フォントは、印字できるASCIIのほかの文字を描かない。エラーにもならない。
- screen-check は、文字の大きさの計算を間違えても通る。実物の画素と照らすのは tour。
- 極端な値でだけ起きるはみ出しがある。両方の変種で回す。
- `with` を付けずに `canvas.box()` を呼ぶと、囲みは開かれない。はみ出しの検査が `box_not_entered` で数える。
- 機械の検査は、描く順の誤り（文字が、後から描いた下地に隠れる）を拾わない。巡回の画像を見て、見た枚数と見ていない枚数を報告に書く。
- 画素は `data_ptr()` でまとめて読む。`pget` は約260倍遅い（実測）。
- 画像（`blt`）、文字数の上限は、まだ無い。
- 上の帯の2つの囲みは、横に並ぶ。文字を長くすると、隣の文字と重なる（`selftest_break.py` の、文字を長くする件は、この幅に頼る）。
