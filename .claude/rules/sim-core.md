---
paths:
  - "clipping_point/cp_core/fixed_loop.py"
  - "clipping_point/cp_core/sim.py"
  - "clipping_point/cp_core/rng.py"
  - "tools/fingerprint.py"
  - "tests/test_fixed_loop.py"
  - "tests/test_sim.py"
  - "tests/test_rng.py"
  - "tests/test_fingerprint.py"
---

# 固定刻み、世界、乱数、指紋（cp_core の芯）

## 約束

- `Sim.step(frame)` の1回が1 tick（1/60秒）。引数は、そのtickの入力フレーム（必須。`InputFrame` でなければ `TypeError`）。世界は tick だけを数え、fps、フレーム番号、実時間を読まない。
- 世界は、入力フレームの「押した瞬間」だけを見て動く。「押している」の立ち上がりを、自分では見ない（決まりは `.claude/rules/controls.md`）。
- `cp_core` は pyxel、js、`cp_app`、`cp_ui`、`random`、`time` をimportしない。使ってよい標準ライブラリは、許可した一覧にあるものだけ。
- 実描画の判定（`RenderGate`）は「前回の実描画から2 tick以上、または1 tick以上かつ30 ms以上」。
- `RenderGate` は自分では時計を読まない。実時間は呼ぶ側（`cp_app`）が引数で渡す。
- 実描画の判定は見た目だけに使う。結果を世界の進行へ戻さない。
- `Sim.summary()`（世界の要約＝指紋）は、整数と文字列だけの、入れ子の無い新しい辞書を返す（JSONにそのまま書ける形）。`seed` と、用途ごとの `rng_<用途の名>`（16桁の16進）を含む。
- 乱数は `cp_core/rng.py` だけ。用途ごとの乱数の流れ（`RngSet`）と、ハッシュの抽選（`hash_u64`、`hash_unit`）。組み込みの `hash()` は使わない。
- 新しい仕組みの抽選は、ハッシュの抽選を使い、いまある流れを引かない（後ろの値がずれて、指紋が動く）。1回1〜3マイクロ秒（ブラウザ版は3〜9）かかるので、毎tick、毎輪の内側では呼ばない。
- 集合を回した順に頼らない。文字列の集合は、起動のたびに順が変わる。
- 指紋の写し（`tests/snapshots/fingerprint.json`）を取り直す口は `python3 tools/fingerprint.py --update` だけ。単独のコミットで、理由を添える。合否は要約だけで決め、環境の値の違いは `env=changed` と出すだけ。

## 値を読む口

- 刻みと間引きの定数：`cp_core/fixed_loop.py` の `TICK_HZ`、`RENDER_HZ`、`RENDER_DIVISOR`、`RENDER_MIN_INTERVAL_MS`
- 世界の要約：`Sim.summary()`。`tools/run.py` が、画面なしで回した結果を、参照と、指紋の写しと照らす。
- 入力の要約値：`Sim.input_digest`（要約の `input_digest`）。受け取った入力フレームを、毎tick量子化して畳み込んだ整数。指紋の一部。
- 台本から計算した、世界の要約の参照：`tools/input_reference.py` の `sim_summary()`
- 乱数の用途の名：`rng.py` の `PURPOSES`。世界の種：`cp_app/app.py` の `WORLD_SEED`。指紋の筋書き：`tools/fingerprint.py` の `SCENARIOS`

## Xを足したらYも

- 世界の状態に項目を足したら、`Sim.summary()` と `tests/test_sim.py` に足す。
- `Sim` の作り方や `step()` の引数を変えたら、`clipping_point/cp_app/app.py` の呼び出し、`tools/input_reference.py`、`python3 tools/run.py` を確かめる。
- 要約の項目、乱数の用途（`PURPOSES` の末尾）、筋書き（`SCENARIOS` の末尾）を足したら、指紋の写しを取り直す。

## テストと道具

- テスト `tests/test_fixed_loop.py`：ふつうの進み方で毎秒30回。処理落ちから追い付く間も0回にならない。新しいtickが無ければ描き直さない。実時間の決まりは、アプリと同じ既定の引数の `RenderGate()` で確かめる。
- テスト `tests/test_sim.py`：1回の `step()` で1 tick。要約がJSONに書ける。入力フレームでない引数を受けない。入力の要約値が、入力フレームの順と欠けを拾う。
- テスト `tests/test_rng.py`：参照値、流れどうしが動かし合わない、登録の無い用途の名、状態の保存と戻し。
- 守りのテスト `tests/test_fingerprint.py`：指紋の写しと同じ。1 tick、入力1つ、種の違いを拾う。`PYTHONHASHSEED` を変えた別プロセスで、要約が同じ。
- 守りのテスト `tests/test_arch_guard.py`：層の分離の検査が、持ち込む書き方を拾う。
- 道具 `python3 tools/fingerprint.py`：指紋と、保存する項目の一覧を、ふるまいの写しと照らす。無ければ2。
- 道具 `python3 tools/run.py`：世界のtick、世界の要約（参照と、指紋の写しと同じこと）、実描画の回数を、画面なしで回して照らす。
- アプリが実時間を `RenderGate` へ渡していること（実時間の決まりが実際に働くこと）は、デスクトップ版の道具でも、web-smoke 単体でも見えない（差が出るのは、実描画のある周期が16.7 msを超えるときだけ）。守りのテスト（`tests/test_fixed_loop.py` が `app.py` のソースを読み、`should_render` の引数を見る）と、selftest-break の `web_gate_gets_no_real_time` で見る。走行の場面が載る段0 区切り10で、web-smoke の実描画の回数で見える形に置き換える。

## 落とし穴

- フレーム番号の偶奇で間引くと、処理落ちから追い付く間に偶奇が固定され、実描画が0回になる（実測）。
- 1回の更新で2 tick進める形にしない。入力の読み取りが毎秒30回に落ちる。
- 浮動小数の結果はデスクトップ版とブラウザ版で一致しない前提で作る。要約と保存は整数で持つ。
- 参照（`sim_summary()`）は、いまのコードで計算し直すので、世界の式を変えても落ちない。式の変化を拾うのは、指紋の写し。
