"""世界の状態と1 tickの進行（純Python）。

いまは tick を数えるだけの最小の世界。車、コース、乱数は後の区切りで足す。
"""


class Sim:
    """世界。step() の1回が1 tick（1/60秒）。fps、フレーム番号、実時間は読まない。"""

    def __init__(self) -> None:
        self.tick = 0  # 始まってから進めたtickの数（整数）

    def step(self) -> None:
        """世界を1 tick進める。"""
        self.tick += 1

    def summary(self) -> dict:
        """読める要約を返す。値は整数と文字列だけにし、JSONにそのまま書ける形にする。"""
        return {"tick": self.tick}
