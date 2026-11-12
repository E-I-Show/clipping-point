---
paths:
  - "clipping_point/cp_core/fixed_loop.py"
  - "clipping_point/cp_core/sim.py"
  - "clipping_point/cp_core/rng.py"
  - "tools/fingerprint.py"
  - "tools/input_script_drive.json"
  - "tools/input_script_wall.json"
  - "tools/claude/make_drive_scripts.py"
  - "tests/test_fixed_loop.py"
  - "tests/test_sim.py"
  - "tests/test_rng.py"
  - "tests/test_fingerprint.py"
---

# 固定刻み、世界、乱数、指紋（cp_core の芯）

## 約束

- `Sim.step(frame)` の1回が1 tick（1/60秒）。引数は、そのtickの入力フレーム（必須。`InputFrame` でなければ `TypeError`）。世界は tick だけを数え、fps、フレーム番号、実時間を読まない。
- 世界は `Sim(種, 読み込んだ定義, 車の id, コースの id)` で作る。既定の値は置かない（決めるのは、アプリと道具）。定義は、作るときに1度だけ引く。無い id は、分かる文の `ValueError`。
- 1 tickの順：入力の要約値 → 操作補正 → 車両モデル → 照会 → 壁の押し戻し → 進行距離と走行の数え。路面の摩擦係数は、前のtickの照会の値。前回の区間は、世界が持つ。壁に押し戻したtickは、押し戻した後の位置で照会し直す。
- 世界は、入力フレームの「押した瞬間」だけを見て動く。「押している」の立ち上がりを、自分では見ない（決まりは `.claude/rules/controls.md`）。
- `cp_core` は pyxel、js、`cp_app`、`cp_ui`、`random`、`time` をimportしない。使ってよい標準ライブラリは、許可した一覧にあるものだけ。
- 実描画の判定（`RenderGate`）は「前回の実描画から2 tick以上、または1 tick以上かつ30 ms以上」。自分では時計を読まない（実時間は `cp_app` が引数で渡す）。見た目だけに使い、結果を世界の進行へ戻さない。
- `Sim.summary()`（世界の要約＝指紋）は、整数と文字列だけの、入れ子の無い新しい辞書（JSONにそのまま書ける形）。車の状態は `round(値 × 倍率)` の整数で入れる。小数を、そのまま入れない。
- 要約の項目の名、倍率、デスクトップ版とブラウザ版の比べ方（完全一致、許容差つき、折り返した差）は、`sim.py` の `SUMMARY_FIELDS` の1か所。道具とテストは、そこから引く。
- 走行の数え（進行距離、最高速、変速、壁、後退、照会の取り直し）は、要約に入れる。進行距離は減らさない。壁は、当たり始めだけ数える。
- 乱数は `cp_core/rng.py` だけ。用途ごとの乱数の流れ（`RngSet`）と、ハッシュの抽選（`hash_u64`、`hash_unit`）。組み込みの `hash()` は使わない。
- 新しい仕組みの抽選は、ハッシュの抽選を使い、いまある流れを引かない（後ろの値がずれて、指紋が動く）。1回1〜3マイクロ秒（ブラウザ版は3〜9）かかるので、毎tick、毎輪の内側では呼ばない。
- 集合を回した順に頼らない。文字列の集合は、起動のたびに順が変わる。
- 指紋の写し（`tests/snapshots/fingerprint.json`）を取り直す口は `python3 tools/fingerprint.py --update` だけ。単独のコミットで、理由を添える。合否は要約だけで決め、環境の値の違いは `env=changed` と出すだけ。
- 筋書きの走行の下限（`Scenario.floors`）は、要約の値だけで判定する（`floor_problems()`）。満たさなければ、写しと同じでも1。`--update` は、何も書かずに1。
- 走る台本と壁の台本は、入力だけを持つ。作るのは `tools/claude/make_drive_scripts.py`（道具とテストは、読まない）。

## 値を読む口

- 刻みと間引きの定数：`cp_core/fixed_loop.py` の `TICK_HZ`、`RENDER_HZ`、`RENDER_DIVISOR`、`RENDER_MIN_INTERVAL_MS`
- 世界の要約：`Sim.summary()`。比べ方は `summary_compare()`、折り返す項目の1周の長さは `Sim.summary_periods()`
- 入力の要約値：`Sim.input_digest`。受け取った入力フレームを、毎tick量子化して畳み込んだ整数
- 車、車の値、コースの表、直近の照会の値：`Sim.car`、`spec`、`track`、`s`、`lateral`、`surface`、`mu`、`on_wall`
- 車を置き直す口（テストと道具用）：`Sim.place_car(x, z, 向き, 速さ)`
- 台本から計算した参照と、道具の世界：`tools/input_reference.py` の `sim_summary()`、`make_sim()`。車とコースの id の既定も、そこ
- 乱数の用途の名：`rng.py` の `PURPOSES`。世界の種と、車とコースの id：`cp_app/app.py` の `WORLD_SEED`、`CAR_ID`、`TRACK_ID`。指紋の筋書き：`tools/fingerprint.py` の `SCENARIOS`

## Xを足したらYも

- 世界の状態に項目を足したら、`SUMMARY_FIELDS` の末尾、`Sim.summary()`、`tests/test_sim.py` に足す。
- `Sim` の作り方や `step()` の引数を変えたら、`cp_app/app.py` の呼び出し、`tools/input_reference.py`、`python3 tools/run.py` を確かめる。
- 要約の項目、乱数の用途（`PURPOSES` の末尾）、筋書き（`SCENARIOS` の末尾）を足すか、世界の式を変えたら、指紋の写しを取り直す。
- 台本が成り立たなくなったら（走行の下限を満たさない）、補助で作り直し、下限と、指紋の写しを置き直す。

## テストと道具

- テスト `tests/test_fixed_loop.py`：ふつうの進み方で毎秒30回。処理落ちから追い付く間も0回にならない。実時間の決まりは、既定の引数の `RenderGate()` で確かめる。
- テスト `tests/test_sim.py`：1回の `step()` で1 tick。入力の要約値。要約の項目の表。路面の摩擦係数が1 tick遅れで変わる。壁。進行距離。無い id。
- テスト `tests/test_rng.py`：参照値、流れどうしが動かし合わない、登録の無い用途の名、状態の保存と戻し。
- 守りのテスト `tests/test_fingerprint.py`：指紋の写しと同じ。1 tick、入力1つ、種の違いを拾う。走行の下限。`PYTHONHASHSEED` を変えた別プロセスで、要約が同じ。
- 道具 `python3 tools/fingerprint.py`：指紋、走行の下限、保存する項目の一覧を照らす。写しが無ければ2。
- 道具 `python3 tools/run.py`：世界のtick、世界の要約（参照、指紋の写し、車とコースの id、走行の下限）、実描画の回数を、画面なしで照らす。全体の検証の `run-drive` と `run-wall` が、走る台本と壁の台本を通す。
- アプリが実時間を `RenderGate` へ渡していることは、守りのテスト（`tests/test_fixed_loop.py` が `app.py` のソースを読む）と、selftest-break の `web_gate_gets_no_real_time` で見る。実描画が重い場面ができた段で、見直す（走行の場面で、実描画のある周期が、1 tickの長さを超えるのは、600〜840 tickに0〜1回。結果の `perf` の `cycles_over_tick`）。

## 落とし穴

- フレーム番号の偶奇で間引くと、処理落ちから追い付く間に偶奇が固定され、実描画が0回になる（実測）。
- 1回の更新で2 tick進める形にしない。入力の読み取りが毎秒30回に落ちる。
- 浮動小数の結果はデスクトップ版とブラウザ版で一致しない前提で作る。要約と保存は整数で持つ。
- 参照（`sim_summary()`）は、いまのコードとデータで計算し直すので、世界の式や車の値を変えても落ちない。変化を拾うのは、指紋の写し。
- 止まったままの筋書きでは、何を変えても、車の項目が動かない。式の変化を拾うのは、走る台本と壁の台本の筋書き。
