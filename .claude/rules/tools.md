---
paths:
  - "tools/**"
  - "tests/test_arch_guard.py"
  - "tests/test_rules_guard.py"
  - "tests/test_canon_guard.py"
  - "tests/test_export_inspect.py"
  - "tests/test_verify.py"
  - "tests/test_claude_tools.py"
---

# 検証の道具（tools/）

## 約束

- 終了コードは全道具でそろえる。0＝合格、1＝問題あり、2＝回り切れない・何も調べていない。2を合格として扱わない。
- 最後に件数つきの1行を `_common.finish()` で出す（`<道具>: OK|FAILED|INCOMPLETE 名=値 …`）。調べた件数が0なら2にする。
- 出力先は `out/`、ビルドは `dist/`。パスは `_common` の絶対パスを使い、作業ディレクトリに頼らない。
- Pyxelを通す確かめは別プロセスで回す。道具自身と pytest のプロセスに pyxel を読み込ませない。
- 道具は1本ずつ回す。`out/` と `dist/` を取り合うため。
- 層の分離は、ソースをASTで解析して許可した一覧と照らす。実行時のimportの見張りには頼らない。
- 正本の要約値の写しを取り直す口は `tools/claude/canon_digest.py --update` だけ。check と見張りには付けない。

## 値を読む口

- パス、終了コード、子プロセスの回し方：`tools/_common.py`
- 仮の上限（HTMLの大きさ、規則ファイルの大きさ、実描画の回数の幅、全体の検証を絞り始める目安）：`tools/budgets.json`。`web_` で始まる値（ブラウザ版の煙テストの線）の読み方は `.claude/rules/web.md`
- 分野ごとの組の表（分野、当たるファイル、テストの絞り、足す手順）：`tools/verify.py` の `AREAS`。出すのは `python3 tools/verify.py --list`
- 全体の検証で回す手順と順：`tools/verify.py` の `STEPS`。まだ無い手順は `NOT_YET`
- 純Pythonの層で使ってよいimportの一覧：`tools/arch_check.py` の `STDLIB_ALLOWED` と `LAYER_ALLOWED`
- テストの件数の下限：`tests/count_floor.txt`（増えたら自動で上がる。下げるのは `tools/test.py --update-floor`）
- 画面なしで回す口の環境変数（`CP_SMOKE`、`CP_SMOKE_TICKS`、`CP_SMOKE_DRIVER`）：`clipping_point/cp_app/app.py` の頭の注

## Xを足したらYも

- 検査や失敗の条件を足したら、`tools/selftest_break.py` に壊す件を足す。
- 道具を足したら、根の `CLAUDE.md` の「コマンド」の表と、`tools/verify.py` の `STEPS`（全体の検証に入れる道具）に足す。
- 出荷するコードかテストのファイルを足したら、`tools/verify.py` の `AREAS` に足す（足さないと check の areas が落ちる）。ファイルは1つずつ並べ、`**` でまとめない。
- 純Pythonの層で新しい標準ライブラリを使うときは、許可した一覧に理由つきで足す。ファイル、環境、時刻、乱数に届くもの（os、pathlib、io）は、使う所を1つに絞り、os は使う属性も縛る。
- 出荷物に新しい種類のファイルを入れるときは、`tools/export.py` の `SHIP_SUFFIXES` に足す。

## テストと道具

- 守りのテスト `tests/test_arch_guard.py`、`tests/test_rules_guard.py`、`tests/test_canon_guard.py`：見張りが崩れを拾うことと、いまのリポジトリが見張りを通ること。
- テスト `tests/test_export_inspect.py`：配布物の検査の関数（入ってはいけないもの、HTML内のデータの一致）。
- 守りのテスト `tests/test_verify.py`：ファイルから分野を引く所、表の手順とテストの語が実在すること、回す手順の決め方、落ちた手順の数え方、基点の選び方、変更したファイルをgitから読む所（一時のリポジトリで回す）。
- 道具 verify（`python3 tools/verify.py --all [--selftest]`、`--touched [--base REV]`）：`--touched` の基点の既定は、直近の区切りのコミット（題が「段N 区切りM：」で始まり「（途中）」を含まない）。
- テスト `tests/test_claude_tools.py`：作業の補助（`tools/claude/`）。控えの差し込みの出し分け、レビューの集計の未評価、週の使用率の線。使い方は `tools/claude/README.md`。
- 道具 selftest-break（`python3 tools/selftest_break.py`）：道具か検査の決まりに触れた区切りで回す。壊す件が1つでも落ちなければ不合格。古い結果ファイルを読んで合格にしないことも、ここで見る。

## 落とし穴

- `pyxel.quit()` は常に終了コード0で終わる。終了コードだけで合格にせず、全tickの後に書く結果ファイルを見る。
- pytest は、全件スキップ、`-k` の片方の語の打ち間違い、スレッドの中だけの例外を合格で通す。必ず `tools/test.py` を通す。
- 画面なしでもPyxelは実時間で待つ。速い確かめは自前のループ（`run.py` の既定）、本番と同じ経路は `run.py --realtime`。
- `pyxel package` は対象ディレクトリの中身をほぼ全部入れる。`clipping_point/` にテスト、文書、道具を置かない。
- selftest-break は、件ごとにリポジトリを `out/selftest/` へ複製する。ランタイムの写し（`.cache/`）は複製せず、本物へのリンクを置く。複製の中で回す件に、`.cache/` へ書き込む道具（`--check` なしの `fetch_runtime.py`）を足さない。
- selftest-break の複製は、gitの作業ツリーの根ではない。`verify --touched` は、そこでは2（`reason=git_failed`）で止まる。
- テストのファイルを足して確かめる壊す件がある。いまのリポジトリの状態を見る守りのテストを足すときは、その件が別の理由で落ちないかを selftest-break で確かめる。
