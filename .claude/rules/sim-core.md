---
paths:
  - "clipping_point/cp_core/fixed_loop.py"
  - "clipping_point/cp_core/sim.py"
  - "tests/test_fixed_loop.py"
  - "tests/test_sim.py"
---

# 固定刻みと世界（cp_core の芯）

## 約束

- `Sim.step()` の1回が1 tick（1/60秒）。世界は tick だけを数え、fps、フレーム番号、実時間を読まない。
- `cp_core` は pyxel、js、`cp_app`、`cp_ui`、`random`、`time` をimportしない。使ってよい標準ライブラリは、許可した一覧にあるものだけ。
- 実描画の判定（`RenderGate`）は「前回の実描画から2 tick以上、または1 tick以上かつ30 ms以上」。
- `RenderGate` は自分では時計を読まない。実時間は呼ぶ側（`cp_app`）が引数で渡す。
- 実描画の判定は見た目だけに使う。結果を世界の進行へ戻さない。
- `Sim.summary()` は、整数と文字列だけの新しい辞書を返す（JSONにそのまま書ける形）。

## 値を読む口

- 刻みと間引きの定数：`cp_core/fixed_loop.py` の `TICK_HZ`、`RENDER_HZ`、`RENDER_DIVISOR`、`RENDER_MIN_INTERVAL_MS`
- 世界の要約：`Sim.summary()`。`tools/run.py` が、画面なしで回した結果の中でこれを照らす。

## Xを足したらYも

- 世界の状態に項目を足したら、`Sim.summary()` と `tests/test_sim.py` に足す。
- `Sim` の作り方や `step()` の引数を変えたら、`clipping_point/cp_app/app.py` の呼び出しと `python3 tools/run.py` を確かめる。

## テストと道具

- テスト `tests/test_fixed_loop.py`：ふつうの進み方で毎秒30回。処理落ちから追い付く間も0回にならない。新しいtickが無ければ描き直さない。実時間の決まりは、アプリと同じ既定の引数の `RenderGate()` で確かめる。
- テスト `tests/test_sim.py`：1回の `step()` で1 tick。要約がJSONに書ける。
- 守りのテスト `tests/test_arch_guard.py`：層の分離の検査が、持ち込む書き方を拾う。
- 道具 `python3 tools/run.py`：世界のtickと実描画の回数を、画面なしで回して照らす。
- アプリが実時間を `RenderGate` へ渡していること（実時間の決まりが実際に働くこと）は、デスクトップ版の道具では見えない。ブラウザ版の煙テストの実描画の回数で見る（段0 区切り3から）。

## 落とし穴

- フレーム番号の偶奇で間引くと、処理落ちから追い付く間に偶奇が固定され、実描画が0回になる（実測）。
- 1回の更新で2 tick進める形にしない。入力の読み取りが毎秒30回に落ちる。
- 浮動小数の結果はデスクトップ版とブラウザ版で一致しない前提で作る。要約と保存は整数で持つ。
