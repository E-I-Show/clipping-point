# 実装役への頼み：段0 区切り7「保存と決定性の土台」

> 要約：段0の区切り7を実装役に頼むための文。保存の口と3つの保存先（メモリ、ファイル、localStorage）、保存先が使えないときの切り替え、形式の版と移行の口、保存する項目（設定）と往復のテスト、用途別の乱数、指紋のテストの形を作る。細目は主のエージェントが決めたもので、実装の途中で合わなければ、報告に書いて直す。

あなたは実装役です。リポジトリは `/home/user/clipping-point`、ブランチは `dev`。日本語で作業し、日本語で報告してください。自分で実装し、サブエージェントは呼びません。

## 最初に読むもの（この順で）

1. `CLAUDE.md`（全文）と、`docs/glossary.md` の2章と3章の「構成と時間と描画」「検証」
2. `docs/design/overview.md` の「設計の前提」、「決定性と保存」（全部）、「検証の仕組み」（道具の表の run と web-smoke、ブラウザ版の煙テストの段落）。見出しでGrepして、その節だけ読む
3. `docs/plan.md` の「段0：立ち上げ」（区切り7の行と、初日のチェックリストの割り当ての、乱数とセーブの3行）と「検証の組」
4. 規則ファイル `.claude/rules/sim-core.md`、`.claude/rules/web.md`、`.claude/rules/tools.md`、`.claude/rules/controls.md`、`.claude/rules/ui.md`
5. いまのコード：`clipping_point/cp_core/sim.py`、`cp_core/input_frame.py`、`cp_core/flow.py`、`clipping_point/cp_app/app.py`、`cp_app/web_bridge.py`、`cp_app/input_web.py`（js を引数で受けて、例外を捕まえる形の先例）、`clipping_point/cp_ui/screens.py`、`cp_ui/fixtures.py`
6. いまの道具：`tools/run.py`、`tools/input_reference.py`、`tools/web_smoke.py`、`tools/web/webrun.js`、`tools/web/fake_gamepad.js`（差し込むスクリプトの先例）、`tools/verify.py` の `AREAS`、`tools/selftest_break.py`、`tools/arch_check.py`（純Pythonの層で使ってよいimportの一覧）、`tools/canon_guard.py` と `tools/claude/canon_digest.py`（ふるまいの写しを照らす道具と、取り直す口の先例）
7. 元にする試作（写して組み直す。中は直さない）：
   - `spikes/harness/repo/app/cp_core/storage.py`（保存先の口、封筒、メモリとファイルの保存先、保存の口）、`cp_core/profile.py`（保存する項目）、`cp_core/rng.py`（乱数）、`cp_core/world.py`（世界の要約）
   - `spikes/harness/repo/app/cp_app/storage_web.py`（localStorage の保存先）
   - `spikes/harness/repo/tests/test_storage.py`、`test_profile.py`、`test_rng.py`、`test_world_fingerprint.py`、`snapshot.py`
   - `spikes/web/apps/_shared/bench_core.py` の325〜368行（数学関数の試し値）
   - `spikes/harness/RESULT.json` の65〜77行、117〜120行と、`spikes/web/RESULT.json` の9行、15行、23行

## 範囲

【範囲】段0 区切り7：保存と決定性の土台
【コミット】しない。gitは `status` と `diff` だけ使う。

## 主が決めた細目

| # | 決めたこと | 理由 |
| --- | --- | --- |
| 1 | 保存は二段にする。下の段は保存先（読む、書く、消す、鍵の一覧。値はバイト列、鍵は短いASCII）。上の段は保存の口（`SaveStore`。封筒を付けて、保存先へ渡す）。出荷するコードは、保存の口だけを使う | 設計の「保存先は1つの口で包み、ロジックは保存先の違いを知りません」。試作の形 |
| 2 | 封筒は、試作の形にする：印（`CPSV`）、形式の版（16ビット）、本体の長さ（32ビット）、本体、チェックサム（crc32）。読めない封筒（短い、印が違う、長さが違う、チェックサムが違う）は、壊れた値 | 試作で、全バイトの1ビット反転と、全位置の切り詰めを拾えた |
| 3 | 失敗は、1つの親の型（`StorageError`）で返す。子は、壊れた値（`CorruptError`）と、書けない（`StorageFull`） | 設計の「書き込みの失敗は1つの型で返す」 |
| 4 | 置き場：保存先の口の決まり、封筒、メモリの保存先、保存の口は `cp_core/storage.py`（純Python）。ファイルの保存先は `cp_app/storage_file.py`。localStorage の保存先は `cp_app/storage_web.py`（js は引数で受ける） | ファイルと os を、純Pythonの層に持ち込まない（層の検査の、許可した一覧を変えない）。試作は、ファイルの保存先も `cp_core` に置いていた |
| 5 | localStorage の値は、base64 の文字列。鍵の頭に `clippingpoint/` を付ける。無い鍵は、文字列でなければ「無い」と読む | 試作の実測（無い鍵は、`None` でなく `jsnull` で返る） |
| 6 | ブラウザ版は、起動時に試し書きをする（試しの鍵を書いて、読んで、消す）。容量超過のほかの例外か、localStorage が無ければ、メモリの保存先に切り替えて、知らせの1行を出す。容量超過なら、localStorage のまま使う（読みは生きている。書き込みは、失敗として返る） | 設計の「起動時に試し書きをし、使えなければメモリ上の保存先に切り替えて1行で知らせ」。試作に無い |
| 7 | デスクトップ版のファイルの置き場は、環境変数 `CP_SAVE_DIR`（絶対パス）。無ければ、メモリの保存先（保存は残らない） | デスクトップ版は、開発とテストにだけ使う（配布物はHTML）。利用者のホームに、黙ってファイルを作らない。道具は、`out/` の下を渡す。設定の画面を作る段1で見直す |
| 8 | 保存する項目は `cp_core/profile.py`。段0は「設定」だけ：効果音の音量、BGMの音量、変速（AT／MT）、アシスト（ON／OFF）、視点（後方追従／バンパー）、レースの通し番号。中身は仮で、段1で足したり変えたりする（公開までは、形式の版を1のままにしてよい） | 設計の「保存するもの」の表。項目の細かい形は、使う所を作る段1で決まる |
| 9 | 読み込みの結果は、値、知らせの1行、その鍵に書いてよいか、の3つ。鍵が無い → 既定値。古い版 → 移行を順に通す。新しい版 → 既定値で動かし、その鍵には書かない。壊れた値 → `<鍵>.bad` へ退避して、その鍵を既定値で書き直す。知らない項目、足りない項目、型や範囲の外も、壊れた値として扱う | 設計の4つの扱い。試作は、新しい版も退避していた |
| 10 | 移行は、`{旧い版: 関数}` の表。いまは空。仕組みは、作り物の旧い版の見本でテストする | 実在する旧い版が、まだ無い |
| 11 | 往復のテスト：全部の項目を、既定値と違う値にして、保存して読み直す（見本が既定値と違うこと自体も確かめる）。保存しない項目の一覧（`NOT_SAVED`。理由つき）。保存する項目の一覧の写し（`tests/snapshots/profile_schema.json`）。項目を足す、消す、型を変えると、テストが落ちる | 試作の形。設計の「項目を足し忘れるとテストが落ちる形」 |
| 12 | 乱数は `cp_core/rng.py`。splitmix64（状態は整数1個）。用途ごとの流れ（`RngSet`。用途の名は、定数に登録する。登録の無い名は例外）と、種と鍵から決まるハッシュの抽選（`hash_u64`、`hash_unit`） | 試作の形。整数だけで作るので、デスクトップ版とブラウザ版で同じ列になる |
| 13 | 世界（`Sim`）は、種を受けて、用途ごとの流れを持ち、世界の要約に、流れの状態を16進の文字列で入れる。いまは、乱数を引く所が無い（AIを作る段3から） | 要約は、整数と文字列だけ。64ビットの整数を、JavaScriptを通っても欠けない形にする |
| 14 | 指紋は、世界の要約。筋書き（台本、回すtick数、種）を決め、要約を、ふるまいの写し（`tests/snapshots/fingerprint.json`）と比べる。写しには、Pythonの版と、数学関数の試し値も入れる。要約が違ったとき、環境の値も違えば「環境が変わった」と出す | 設計。車が入る区切り9から、要約に浮動小数が入る |
| 15 | 写しを取り直す口は `python3 tools/fingerprint.py --update` だけ。テストと道具は、写しが無ければ失敗にする（黙って作らない） | ふるまいの写しは、単独のコミットで、理由を添えて取り直す決まり |
| 16 | 文字列の集合の順に頼っていないことは、`PYTHONHASHSEED` を変えた別プロセス（3通り）で、同じ要約になることで見る | 設計。層の検査は、集合の順への頼りを拾えない |
| 17 | 区切り5で入れた入力の要約値は、指紋（世界の要約）の一部として残す。割り切りの印は外す | 区切り5の割り切りの「区切り7で見直す」 |
| 18 | 段0では、設定を変える画面が無い。保存の往復は、検証の口（画面なしで回す口と、外から渡す値）のときだけ、アプリが回して、結果に入れる。ふつうの起動は、試し書きと、設定の読み込みだけを行い、設定は書かない | 設定の画面は段1 |
| 19 | 知らせの1行は、仮の表示に出す（印字できるASCII） | 設計の「1行で知らせ」。本物の通知は、画面の状態を作る段1 |
| 20 | 再読み込みをまたいで保存が残ることは、この区切りでは確かめない | 設定を実際に保存する画面ができる段1で、筋書きを足す。試作で、再読み込みの後も残ることは実測してある |
| 21 | 規則ファイルは `save.md` を足す（保存の口、保存先、保存する項目）。乱数と指紋の決まりは `sim-core.md` に足す | 計画の規則ファイルの表 |

## やること

### 1. 保存の口（`clipping_point/cp_core/storage.py`）

- 例外：`StorageError`、その子の `CorruptError`（壊れた値）、`StorageFull`（書けない。何も変わっていない）。
- 鍵の検査 `check_key`：小文字のASCII、数字、`_ . -`。48字まで。外れたら `StorageError`。
- 封筒 `wrap(payload, version)` と `unwrap(blob)`（細目の2番）。`unwrap` は `(版, 本体)` を返す。
- 保存先の決まり：`read(key)`（バイト列か、無ければ `None`）、`write(key, data)`、`delete(key)`（無い鍵でも、黙る）、`keys()`（整列した一覧）。
- `MemoryBackend(capacity=None)`：辞書で持つ。`capacity` を渡すと、合計が上限を超える書き込みを、何も変えずに `StorageFull` にする。
- `SaveStore(backend, namespace="main")`：`put(key, payload, version)`、`get(key)`（`(版, 本体)` か `None`。壊れていれば `CorruptError`）、`quarantine(key)`（`<key>.bad` へ写して、元の鍵を消す。退避の書き込みが失敗したら、元の鍵は消さずに `StorageFull`）、`delete(key)`、`keys()`、`used_bytes()`。保存先での鍵は `<名前空間>.<鍵>`。

### 2. 2つの保存先（`clipping_point/cp_app/storage_file.py`、`clipping_point/cp_app/storage_web.py`）

- `FileBackend(directory)`：1つの鍵を、1つのファイル（`<鍵>.sav`）に持つ。書き込みは、一時ファイルに全部を書く → `flush` → `fsync` を1回 → `os.replace`。`OSError` は、一時ファイルを消して `StorageFull`。読むときの、ファイルが無いほかの `OSError` は `StorageError`。残った一時ファイルは、鍵の一覧に出さない。
- `WebStorageBackend(js)`：`js.localStorage` を使う（細目の5番）。js は引数で受け、このモジュールでは js をimportしない。
  - 書き込みの例外は、容量超過（JavaScriptの例外の名が `QuotaExceededError`）なら `StorageFull`、ほかは `StorageError`。
  - 読んだ値が、base64 として読めなければ `CorruptError`。
  - `probe()`：試し書き（細目の6番）。返すのは、使える、容量超過、使えない（理由の文つき）の3通り。例外を外へ出さない。
- 保存先を選ぶ関数（置き場は `cp_app`）：ブラウザ版は、`WebStorageBackend` の試し書きの結果で、localStorage かメモリかを決める。デスクトップ版は、`CP_SAVE_DIR` があればファイル、無ければメモリ。返すのは、保存先、保存先の名（`localstorage`、`file`、`memory`）、知らせの1行（切り替えたときだけ）。

### 3. 保存する項目（`clipping_point/cp_core/profile.py`）

- `Settings`（書き換えられない dataclass）。項目と既定値（どれも仮の値。注を付ける）：
  - `sfx_volume`、`bgm_volume`：0〜10 の整数。既定は 5
  - `transmission`：`"AT"` か `"MT"`。既定は `"AT"`
  - `assist`：bool。既定は真
  - `view`：`"chase"` か `"bumper"`。既定は `"chase"`
  - `race_serial`：0以上の整数。既定は 0
- 作るときに、型と範囲を検査する。
- `SETTINGS_KEY = "settings"`、`SETTINGS_VERSION = 1`、`MIGRATIONS = {}`（細目の10番）、`NOT_SAVED = {}`（`"クラス.項目": "理由"`。細目の11番）。
- 本体は、JSON（鍵の順をそろえ、空白を入れない。UTF-8）。読むときは、知らない項目、足りない項目、型や範囲の外を、どれも読めない値として扱う（半分だけ読まない）。
- `save_settings(store, settings)` と `load_settings(store, migrations=MIGRATIONS)`。読み込みの結果は、細目の9番の3つ（値、知らせの1行、書いてよいか）。知らせの文は、印字できるASCII（例：`SAVE DATA UNREADABLE. USING DEFAULTS`、`SAVE DATA IS FROM A NEWER VERSION. NOT SAVING`）。
- 書いてよくない結果を渡して保存しようとしたら、書かずに、失敗として返す。

### 4. 乱数（`clipping_point/cp_core/rng.py`）と世界（`clipping_point/cp_core/sim.py`）

- `rng.py`：試作の式のまま（`hash_u64`、`hash_unit`、`RngStream`、`RngSet`）。用途の名は `PURPOSES = ("ai",)`。足すときは、末尾に足す。鍵に bool と小数を渡したら `TypeError`。
- `Sim(seed=0)`：種を受けて `RngSet` を持つ。`Sim.summary()` に、`seed` と、流れの状態（`rng`。用途の名 → 16桁の16進の文字列）を足す。
- 区切り5の、入力の要約値の割り切りの注を直す（細目の17番）。

### 5. 指紋（`tools/fingerprint.py`、`tests/snapshots/fingerprint.json`）

- `tools/fingerprint.py`：筋書きの一覧（名、台本、回すtick数、種）、要約の計算（`cp_core` だけを読む。pyxel は読み込まない）、環境の値（Pythonの版と、数学関数の試し値）、写しの読み書きを持つ。
  - 筋書きは2本：道具の台本（`tools/input_script_smoke.json`）を120 tick回すもの（`run.py` が回す形と同じ）と、台本なしで600 tick回すもの。
  - 数学関数の試し値：`sin`、`cos`、`tan`、`atan2`、`exp`、`sqrt`、`hypot` を、決まった入力の列で回し、結果を並べたバイト列の要約値（先頭16字）を、関数ごとに持つ。
  - `python3 tools/fingerprint.py`：写しと照らす。同じなら0、違えば1（どの筋書きの、どの項目が、何から何へ変わったかを出す。環境の値も違えば、そのことを先に出す）、写しが無い・読めないなら2。
  - `python3 tools/fingerprint.py --update`：写しを書く。
- `tests/test_fingerprint.py`：写しと同じこと。1 tick多く回すと、要約が変わること。入力を1つ変えると、変わること。種を変えると、流れの状態が変わること。`PYTHONHASHSEED` を `0`、`1`、`12345` にした別プロセスで、要約が同じこと（細目の16番）。
- 新しく置く写し（`fingerprint.json`、`profile_schema.json`）は、この区切りのコミットに入れる。区切りの途中で値が変わったら、取り直してよい（報告に書く）。

### 6. アプリ（`clipping_point/cp_app/app.py`、`cp_app/web_bridge.py`）と仮の表示

- 起動時に、保存先を選び（やること2）、設定を読み込む。知らせの1行（保存先の切り替え、読めない保存）があれば、仮の表示に出す（`PlaceholderView` に項目を足す。見本データの極端な値は、いちばん長い知らせの文）。
- 世界の種は、いまは 0（レースを作る段で、レースの通し番号と設定から決める）。
- 検証の口のとき（`CP_SMOKE` があるとき、`window.CP_PROBE` があるとき）だけ、保存の往復を回して、結果に入れる：既定値と違う設定を書く → 読み直して同じ → 元の状態へ戻す（書いた鍵を消す）。結果の形は `{"backend": 保存先の名, "ok": 真偽, "notice": 知らせの1行, "detail": 失敗の理由}`。
- デスクトップ版の、画面なしで回す口は、`CP_SAVE_DIR`（絶対パス）を読む。相対パスは、起動時に `ValueError`。

### 7. 道具

- `tools/run.py`：`CP_SAVE_DIR` に `out/run/saves` を渡す。足す確かめ：保存の往復が通っていて、保存先の名が `file`。世界の要約が、指紋の写しの、同じ筋書きの要約と同じ。`not_yet` から、`fingerprint` と `save` を外す。
- `tools/web_smoke.py`：
  - `probe` の筋書きに足す：保存の往復が通っていて、保存先の名が `localstorage`。知らせの1行が空。
  - 筋書きを1本足す（`storage_blocked`）。差し込むスクリプト（`tools/web/block_storage.js`）で、`localStorage` に触れると例外になるようにして開く。見るもの：どの筋書きでも見ること（例外が出ていない）、保存先の名が `memory`、知らせの1行が空でない、メモリの上での往復が通っている、回したtick。処理時間と回数の線は見ない。
  - `localStorage` に触れると例外になるときに、Pythonから見える例外の型と名を、先に実測して、切り替えの判定を固める。
- `tools/verify.py`：`STEPS` に、指紋の照合（`fingerprint`）を足す（test の後）。`AREAS` は、計画の「検証の組」の表のとおりに（保存と乱数は「メインループと世界の状態」の行。`storage_web.py` は「ブラウザ連携」。違えるなら、理由を行の注に書く）。
- `tools/selftest_break.py`：壊す件を足す。少なくとも次の形。
  - 封筒のチェックサムを見ない（`test` が1）
  - ファイルの保存先が、最後の1バイトを落として書く（`test` が1、`run` が1）
  - 設定の項目を1つ、保存の本体から落とす（`test` が1）
  - 設定に項目を足して、写しを直さない（`test` が1）
  - `NOT_SAVED` に、無い項目の名を足す（`test` が1）
  - 新しい版の値を、退避して上書きする（`test` が1）
  - 世界の式を変える（入力の要約値の畳み込みの定数。`test` が1、`fingerprint` が1、`run` が1）
  - 指紋の写しを消す（`test` が1、`fingerprint` が2）
  - 流れの順を、文字列の集合から取る（`test` が1。`PYTHONHASHSEED` のテスト）
  - 純Pythonの層で、組み込みの `hash()` を使う（`check` が1。いまある件があれば、それでよい）
  - localStorage の保存先が、読んだ値の最後の1バイトを落とす（`web_smoke --only probe` が1）
  - 試し書きをせずに、localStorage を使う（`web_smoke --only storage_blocked` が1）
  - 保存先を切り替えても、知らせを出さない（`web_smoke --only storage_blocked` が1）
  - 古い結果ファイルが残っている（合格にしない。いまの件の形に合わせる）

### 8. 規則ファイルとテスト

- `.claude/rules/save.md` を足す。書式は、いまの5つにそろえる。当て先は、`cp_core/storage.py`、`cp_core/profile.py`、`cp_app/storage_file.py`、`cp_app/storage_web.py`、`tools/web/block_storage.js` と、そのテスト。根のCLAUDE.mdの「規則ファイルの目次」に1行足す（直してよいのは、この表だけ）。
- `.claude/rules/sim-core.md` に、乱数と指紋の決まりを足す（新しい仕組みの抽選は、ハッシュの抽選を使い、いまある流れを引かない。ハッシュの抽選は1回1〜3マイクロ秒かかるので、毎tick、毎輪の内側では呼ばない。写しの取り直しは、単独のコミットで、理由を添える）。当て先に、`cp_core/rng.py`、`tools/fingerprint.py` と、そのテストを入れる。
- `.claude/rules/web.md` と `tools.md` は、上限（6,000バイト）に近い。足すのは、要る所だけにする（筋書きの数、外から渡す値の結果の項目）。
- テスト：
  - `tests/test_storage.py`：封筒（全バイトの1ビット反転と、全位置の切り詰めを、壊れた値にする）、鍵の検査、メモリの保存先の容量超過（何も変わらない）、名前空間が混ざらない、退避。
  - `tests/test_storage_file.py`：一時の置き場で。往復、一時ファイルが残らない、残った一時ファイルがあっても古い保存が読める、`fsync` は1回、書けない置き場は `StorageFull`。
  - `tests/test_storage_web.py`：偽の js で。往復、無い鍵（`jsnull` の形の偽物）、容量超過、ほかの例外、base64 として読めない値、鍵の一覧、試し書きの3通り、`localStorage` に触れると例外。
  - `tests/test_profile.py`：細目の11番の3つ。読み込みの4つの扱い（鍵が無い、古い版を移行、新しい版は書かない、壊れた値を退避）。知らせの文が、印字できるASCIIで、仮の表示に収まること。
  - `tests/test_rng.py`：参照値（始めの数個の値を、数字で固定する）、流れを1つ引いても、ほかの流れが動かない、登録の無い用途の名、状態の保存と戻し、ハッシュの抽選の鍵の型。
  - `tests/test_fingerprint.py`：やること5のとおり。
  - `tests/test_sim.py`、`tests/test_web_smoke.py`、`tests/test_screens.py`、`tests/test_fixtures.py` ほか：変えた所に合わせて足す。

## 実測して、報告に書くこと

- ブラウザ版で、`localStorage` に触れると例外になるときに、Pythonから見える例外の型と、名。`localStorage` が無い（`undefined`）ときの見え方。
- 試し書きにかかる時間（ブラウザ版）。
- `probe` の筋書きの、更新1回の時間（95%点）が、この区切りの前後でどう変わったか（世界の要約に、流れの状態を足した分）。
- 乱数の `unit()` と、ハッシュの抽選の、1回の時間（デスクトップ版。できれば、ブラウザ版も）。
- `verify.py --all` と `selftest_break.py` にかかった秒数。

## 回す検証

1本ずつ回す：`python3 tools/check.py`、`python3 tools/test.py`、`python3 tools/fingerprint.py`、`python3 tools/screen_check.py`、`python3 tools/run.py`、`python3 tools/run.py --realtime`、`python3 tools/tour.py`、`python3 tools/export.py`、`python3 tools/web_smoke.py`、最後に `python3 tools/verify.py --all --selftest`（約13分）。各道具の最後の1行を、そのまま報告に写す。道具の出力をパイプに通して、終了コードを見失わないこと。

## 範囲の外（直さずに報告する）

- 設定を変える画面、操作設定、記録、セッティング、リプレイの目次と本体、ゴーストの保存（段1から後）。リプレイの棚の容量の扱い（段2）。
- 再読み込みをまたいで保存が残ることの確かめ（段1）。ファイルへの書き出しの案内（段2）。
- 世界の種を、レースの通し番号と設定から決めること（レースを作る段）。乱数を引く所（AI。段3）。見た目だけの乱数（`cp_app` の側。使う所を作る区切り）。
- 定義データ（区切り8）。車とコース（区切り9、10）。
- `docs/` の文書（言葉の表には、主が「保存先」「封筒」「形式の版」「乱数の流れ／ハッシュの抽選」を足し、「保存の口」「指紋テスト」を直してある。設計のモジュールの表には、主が `cp_app` の `storage_file` を足してある）と、根のCLAUDE.mdの「規則ファイルの目次」の表のほかの節（「コマンド」の表は、主が直す）。直す必要があれば、何をどう直すかを報告に書く。
- `spikes/` の中。

## 書き方の約束

- 根のCLAUDE.mdの「書き方の約束」と、言葉の表の決めを守る（「写し」「記録」「枠」「モデル」「段」は、決めた意味のほかに単独で使わない。保存するファイルの基準は「ふるまいの写し」、ランタイムの写しは「ランタイムの写し」）。
- 出荷するコードに置く仮の値には、`# 仮の値：<根拠>。<合わせる時>` の注を付ける。道具の値は `tools/budgets.json` に出す。
- 新しいパッケージは入れない。テストを通すためだけの特別扱いをしない。落ちるテストを弱めない。

## 報告の形

1. 変えたファイル（作ったものは、ディスクにあることを確かめてから書く）
2. 設計と、この文の細目からのずれ・変えた値・新しく足した割り切り
3. 回した検証（各道具の最後の1行と件数）
4. 回せなかったこと・確かめられなかったこと・範囲の外で直す必要がある所（無ければ「無し」）
5. 推奨の案で決めた細目
6. 「実測して、報告に書くこと」の5点
