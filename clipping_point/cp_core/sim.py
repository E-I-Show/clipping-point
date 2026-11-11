"""世界の状態と1 tickの進行（純Python）。

いまは tick を数え、受け取った入力フレームを畳み込み、用途ごとの乱数の流れを持つだけの最小の世界。車とコースは後の区切りで足す。
世界の要約（summary）が、指紋。決まった筋書きで回した要約を、ふるまいの写し（tests/snapshots/fingerprint.json）と比べる
（tools/fingerprint.py と tests/test_fingerprint.py）。
"""
from cp_core.input_frame import DIGEST_START, InputFrame, fold, quantize
from cp_core.rng import RngSet

RNG_STATE_FORMAT = "016x"  # 乱数の流れの状態（64ビットの整数）を、要約に入れる形。16桁の16進の文字列


class Sim:
    """世界。step() の1回が1 tick（1/60秒）。fps、フレーム番号、実時間は読まない。"""

    def __init__(self, seed: int = 0) -> None:
        """seed は、世界の種（bool でない整数）。用途ごとの乱数の流れの、始まりの状態を決める。"""
        self.rng = RngSet(seed)  # 用途ごとの乱数の流れ。いまは、引く所が無い（AIを作る段3から）
        self.seed = self.rng.seed  # 世界の種
        self.tick = 0  # 始まってから進めたtickの数（整数）
        self.input_digest = DIGEST_START  # 入力の要約値。受け取った入力フレームを、毎tick量子化して畳み込んだ整数

    def step(self, frame: InputFrame) -> None:
        """世界を1 tick進める。frame は、このtickの入力フレーム（必須）。"""
        if not isinstance(frame, InputFrame):
            raise TypeError(f"Sim.step takes an InputFrame, got {type(frame).__name__}")
        # 入力の要約値は、指紋（世界の要約）の一部。入力フレームが、世界へ、順のまま、欠けずに届いたことを見る。
        self.input_digest = fold(self.input_digest, quantize(frame))
        self.tick += 1

    def summary(self) -> dict:
        """世界の要約（指紋）を返す。値は整数と文字列だけの、入れ子の無い辞書にし、JSONにそのまま書ける形にする。

        乱数の流れの状態は、用途ごとの「rng_<用途の名>」に、16桁の16進の文字列で入れる
        （64ビットの整数を、JavaScriptを通っても欠けない形にする）。
        """
        summary = {"tick": self.tick, "input_digest": self.input_digest, "seed": self.seed}
        for name, state in self.rng.state().items():
            summary[f"rng_{name}"] = format(state, RNG_STATE_FORMAT)
        return summary
