"""描画命令の実行。cp_ui.canvas が記録した列を、Pyxelの画像（裏画面）へ描く。

描く先は引数で受ける。このモジュール自身は pyxel をimportしない。
"""


def execute(commands, target) -> int:
    """commands を順に target（pyxel.Image）へ描き、実行した命令の数を返す。"""
    for command in commands:
        if command.kind == "text":
            target.text(command.x, command.y, command.text, command.col)
        elif command.kind == "rect":
            target.rect(command.x, command.y, command.w, command.h, command.col)
        else:
            raise ValueError(f"unknown draw command kind: {command.kind!r}")
    return len(commands)
