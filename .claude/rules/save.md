---
paths:
  - "clipping_point/cp_core/storage.py"
  - "clipping_point/cp_core/profile.py"
  - "clipping_point/cp_app/storage_file.py"
  - "clipping_point/cp_app/storage_web.py"
  - "clipping_point/cp_app/storage_select.py"
  - "tools/web/block_storage.js"
  - "tests/test_storage.py"
  - "tests/test_storage_file.py"
  - "tests/test_storage_web.py"
  - "tests/test_storage_select.py"
  - "tests/test_profile.py"
---

# 保存（保存の口、保存先、保存する項目）

## 約束

- 出荷するコードは、保存の口（`cp_core/storage.py` の `SaveStore`）だけを使う。ファイルと `js.localStorage` を、直に触らない。
- 保存の口が封筒（印、形式バージョン、長さ、本体、crc32）を付け、保存先（読む、書く、消す、鍵の一覧）へ渡す。
- 保存先は、メモリ（`cp_core`）、ファイル（`cp_app/storage_file.py`）、localStorage（`cp_app/storage_web.py`）。`cp_core` に、ファイルと os を持ち込まない。
- 失敗は `StorageError` かその子で返す。壊れた値は `CorruptError`、書けないは `StorageFull`、新しい形式バージョンの値がある鍵への書き込みは `NewerVersionError`。
- 新しい形式バージョンの値を上書きしない守りは、`SaveStore.put` に置く。読み込みの結果の「書いてよいか」は、画面のための知らせで、守りではない。
- 読み込み（`load_settings`）は、`StorageError` を外へ出さない。場合ごとの扱いは、`cp_core/profile.py` の頭の表。
- 壊れた値は、保存先のバイト列のまま `<鍵>.bad` へ退避してから、既定値で書き直す。黙って上書きしない。
- 読むときは、知らない項目、足りない項目、型や範囲の外を、どれも壊れた値にする（半分だけ読まない）。bool と整数は `type(...) is` で見分ける。
- ブラウザ版は、起動時に試し書きをする。容量超過のほかの例外か、localStorage が無ければ、メモリへ切り替えて知らせを出す。容量超過なら、localStorage のまま使う。
- デスクトップ版は、どの起動でも `CP_SAVE_DIR`（絶対パス）を読む。無ければメモリ。相対パスは `ValueError`。
- `storage_file`、`storage_web`、`storage_select` は、pyxel と js をimportしない。js と環境の辞書は、引数で受ける。
- 知らせの文は、全部 `cp_core/storage.py` の定数に置く。一度に出すのは、多くて1つ（保存先の切り替えが先）。
- 保存の往復（`profile.selfcheck`）は、検証の口のときだけ、名前空間 `selfcheck` で回す。`main` に触れない。段0のふつうの起動は、保存しない。
- ふつうの保存の名前空間は `main`。試験用データを重ねている間は `pack_<名>`（`GameData.save_namespace`。決まりは `.claude/rules/data.md`）。アプリは、設定を読む保存の口（`App.store`）を1つだけ作り、そこへ渡す。往復の名前空間は、変えない。

## 値を読む口

- 封筒の形、鍵に使える字と長さ、知らせの文（`NOTICES`）：`cp_core/storage.py` の頭の定数
- 保存する項目、形式バージョン、移行の表、保存しない項目、往復の見本：`cp_core/profile.py` の `Settings`、`SETTINGS_VERSION`、`MIGRATIONS`、`NOT_SAVED`、`SELFCHECK_SETTINGS`
- 保存する項目の一覧：`profile.schema()`。一覧の写しは `tests/snapshots/profile_schema.json`（照らすのは、道具 fingerprint と守りのテスト）
- 保存先の名（`localstorage`、`file`、`memory`）と環境変数の名：`cp_app/storage_select.py`
- localStorage での鍵の頭（`clippingpoint/`）と、実測した見え方：`cp_app/storage_web.py` の頭の注
- 結果に出す値（`storage` の `backend`、`ok`、`notice`、`detail`）：`cp_app/app.py` の `storage_report()`。`notice` は、表示用の値から取る
- 結果に出す名前空間（`data` の `namespace`）：`cp_app/app.py` の `data_report()`。設定を読んだ保存の口（`SaveStore.namespace`）から取る

## Xを足したらYも

- 保存する項目を足す、消す、型を変えたら、形式バージョンを上げるか、`NOT_SAVED` に理由つきで入れるかを決め、往復の見本も直す。一覧の写しの取り直しは `python3 tools/fingerprint.py --update`（単独のコミットで、理由を添える）。
- 形式バージョンを1のままにしてよいのは、人にHTMLを渡す前（段0の間）だけ。渡した後（段0の仕上げから後）は、保存する項目、型、範囲、選べる値を変えるたびに上げる。据え置くと、前のHTMLが、新しいHTMLの設定を退避し、次の起動で、退避した値も上書きされる。
- 範囲と、選べる値の変更は、一覧の写しでは拾えない（`schema()` の割り切り。持つのは、項目の名と型だけ）。変えたら、自分で上げる。
- 公開（段4の終わり）までは、移行を書かずに、古い形式バージョンの値を退避でよい（人の試しのデータ）。公開の後は、上げるたびに `MIGRATIONS` に、前の形式バージョンからの関数を足し、その見本でテストする。移行の関数は、残し続ける。
- 保存する型を足したら、`SAVED_CLASSES` に足す（保存する項目の一覧と、保存しない項目の突き合わせは、ここから作る）。
- 知らせの文を足したら、`NOTICES` に足す（見本データとテストが、そこから引く）。
- 保存先を足したら、4つの口（`BACKEND_METHODS`）を持たせ、`tests/test_profile.py` の `backends()` に足す。

## テストと道具

- テスト：`test_storage.py`（封筒、鍵、容量超過、退避、`put` の守り、知らせの文）、`test_storage_file.py`、`test_storage_web.py` と `test_storage_select.py`（偽の js）、`test_profile.py`（往復、保存しない項目、一覧の写し、読み込みの表の1行ずつ、作り物の見本での移行）。
- 道具 run：置き場（`out/run/saves`）を渡し、書かれたファイルを自分で読んで、往復の見本と比べる。`main` のファイルが無いことも見る。読む関数のテストは `tests/test_run_tool.py`。
- 道具 web-smoke の筋書き `probe`（localStorage の値を、道具が自分で読む）、`storage_blocked`（`block_storage.js` で、触れると例外にする）、`shipped`（ふつうの起動の後の localStorage に、`clippingpoint/` の鍵が1つも無い。試し書きの鍵も残さない）。

## 落とし穴

- localStorage の無い鍵は、`None` でなく `jsnull`。文字列でなければ「無い」と読む。
- 容量超過は `JsException` で、`name` が `QuotaExceededError`（`js_name` は無い）。
- 保存先に触れたときの例外は、型も名も決まらない（実測は `storage_web.py` の頭の注）。切り替えの判定は、容量超過かどうかだけを見る。
- 読みで例外にすると、退避のための読みも例外になる。base64 として読めない値は、バイト列で返し、封筒の検査に任せる。
- 再読み込みをまたいで保存が残ることは、まだ確かめていない（段1）。
