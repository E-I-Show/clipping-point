"""描画命令の実行。cp_ui.canvas がためた描画命令の列を、Pyxelの画像（裏画面）へ描く。

描く先は引数で受ける。このモジュール自身は pyxel をimportしない。
囲み（Canvas.boxes）は描かない。受けるのは、描く命令の列（Canvas.commands）だけ。
"""


def execute(commands, target, ox: int = 0, oy: int = 0) -> int:
    """commands を順に target（pyxel.Image）へ描き、実行した命令の数を返す。

    ox、oy は、描く位置のずらし（巡回が、余白つきの検査用の裏画面へ描くのに使う）。
    """
    for command in commands:
        if command.kind == "text":
            target.text(command.x + ox, command.y + oy, command.text, command.col)
        elif command.kind == "rect":
            target.rect(command.x + ox, command.y + oy, command.w, command.h, command.col)
        elif command.kind == "rectb":
            target.rectb(command.x + ox, command.y + oy, command.w, command.h, command.col)
        elif command.kind == "line":
            target.line(command.x1 + ox, command.y1 + oy, command.x2 + ox, command.y2 + oy, command.col)
        else:
            raise ValueError(f"unknown draw command kind: {command.kind!r}")
    return len(commands)
