---
paths:
  - "clipping_point/cp_ui/**"
  - "clipping_point/cp_app/canvas_pyxel.py"
  - "tests/test_canvas.py"
  - "tests/test_screens.py"
---

# 2Dの描画（cp_ui と描画命令の実行）

## 約束

- 2Dの描画は必ず `cp_ui.canvas.Canvas` の描画命令を通す。Pyxelの描画関数を直に呼ばない。
- 画面の組み立て（どこに何を描くか）は `cp_ui/screens.py` に置く。`cp_app` は呼ぶだけにする。
- `Canvas` は描画命令を呼ばれた順にためるだけで、絵は描かない。ためた列を `cp_app.canvas_pyxel.execute()` が裏画面へ描く。
- `cp_ui` は pyxel、js、`cp_app`、`random`、`time` をimportしない。`cp_core` は呼んでよい。
- 座標、大きさ、色の番号は整数（画素の単位）。小数と bool は `TypeError` にする。
- 画面に出す文字は英数字のみ。
- 描画命令の引数の並びは、Pyxelの同名の関数と同じにする（`text(x, y, s, col)`、`rect(x, y, w, h, col)`）。
- `cp_app/canvas_pyxel.py` は pyxel をimportしない。描く先は引数で受ける。テストから偽の描き先で確かめるため。

## 値を読む口

- 画面の大きさ：`cp_ui/canvas.py` の `SCREEN_W`、`SCREEN_H`（320×240）
- ためた描画命令の列：`Canvas.commands`（`TextCommand` と `RectCommand`。種類は `kind`）
- 仮の表示の文字と色：`cp_ui/screens.py` の `TITLE`、`COL_BACK`、`COL_BAR`、`COL_TEXT`

## Xを足したらYも

- 描画命令の種類を足したら、`cp_ui/canvas.py`（命令のクラスと `Canvas` の口）、`cp_app/canvas_pyxel.py`（実行）、`tests/test_canvas.py` の3か所に足す。
- 画面を足したら、`cp_ui/screens.py` と `tests/test_screens.py` に足す。

## テストと道具

- テスト `tests/test_canvas.py`：描画命令が呼んだ順にたまる。整数でない値を受けない。`execute()` が全命令を順に描き、知らない種類を例外にする。
- テスト `tests/test_screens.py`：仮の表示の文字。英数字だけであること。画面の内に収まること。
- 道具 `python3 tools/run.py`：実際の画素を見る（裏画面が空でないこと、画面が裏画面と同じこと）。
- 道具 `python3 tools/test.py`：`cp_app/canvas_pyxel.py` が pyxel を読み込むと、`reason=pyxel_loaded` で落ちる。

## 落とし穴

- 内蔵フォントは、英数字と記号のほかの文字を描かない。エラーにもならない。
- いまは最小の形。はみ出しの検査、枠、線、画像は段0 区切り6で足す。文字の大きさの計算もまだ無い。
