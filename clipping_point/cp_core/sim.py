"""世界の状態と1 tickの進行（純Python）。

いまは tick を数え、受け取った入力フレームを畳み込むだけの最小の世界。車、コース、乱数は後の区切りで足す。
"""
from cp_core.input_frame import DIGEST_START, InputFrame, fold, quantize


class Sim:
    """世界。step() の1回が1 tick（1/60秒）。fps、フレーム番号、実時間は読まない。"""

    def __init__(self) -> None:
        self.tick = 0  # 始まってから進めたtickの数（整数）
        self.input_digest = DIGEST_START  # 入力の要約値。受け取った入力フレームを、毎tick量子化して畳み込んだ整数

    def step(self, frame: InputFrame) -> None:
        """世界を1 tick進める。frame は、このtickの入力フレーム（必須）。"""
        if not isinstance(frame, InputFrame):
            raise TypeError(f"Sim.step takes an InputFrame, got {type(frame).__name__}")
        # 割り切り：車が無い間、入力フレームが世界へ順のまま届いたことを見るための仕組み。全車の状態の要約ではない。
        # 指紋の形を作る段0 区切り7で、指紋に入れるかを見直す。
        self.input_digest = fold(self.input_digest, quantize(frame))
        self.tick += 1

    def summary(self) -> dict:
        """読める要約を返す。値は整数と文字列だけにし、JSONにそのまま書ける形にする。"""
        return {"tick": self.tick, "input_digest": self.input_digest}
