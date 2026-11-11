"""tools/ の全道具の共通部。パス、終了コード、最後の1行の出し方。

終了コード：0＝合格、1＝問題あり、2＝回り切れない・何も調べていない。2を合格として扱わない。
どの道具も、最後に件数つきの1行を finish() で出す（例：check: OK syntax=12 arch=9 rules=2 canon=1 problems=0）。
パスはすべて絶対パスで扱い、作業ディレクトリに頼らない。
"""
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "clipping_point"  # 出荷するアプリ
TESTS = ROOT / "tests"
TOOLS = ROOT / "tools"
OUT = ROOT / "out"  # 道具の出力先。gitの外
DIST = ROOT / "dist"  # ビルドの出力先。gitの外
BUDGETS = TOOLS / "budgets.json"
PURE_PACKAGES = ("cp_core", "cp_ui")  # 純Pythonの層
OK, FAIL, INCOMPLETE = 0, 1, 2
WORD = {OK: "OK", FAIL: "FAILED", INCOMPLETE: "INCOMPLETE"}
NOISE_PREFIXES = ("ALSA lib ",)  # 音の出口が無い環境でPyxelが標準エラーに出す行の頭。行の途中の語では除かない


def child_env(**extra) -> dict:
    """子プロセスの環境。外から入った CP_SMOKE* を除き、__pycache__ を作らせない。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("CP_SMOKE")}
    env.pop("PYTHONUNBUFFERED", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.update({k: str(v) for k, v in extra.items()})
    return env


def run(cmd, timeout=300, env=None, cwd=None):
    """子プロセスを回す。返すのは (終了コード, 標準出力, 標準エラー)。時間切れのときは終了コードが None。"""
    try:
        p = subprocess.run(
            [str(c) for c in cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env if env is not None else child_env(),
            cwd=str(cwd or ROOT),
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as exc:
        return None, _text(exc.stdout), _text(exc.stderr)


def _text(data) -> str:
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data or ""


def tail(text: str, lines: int = 25) -> str:
    """出力の終わりの数行。Pyxelの音の出口の行は除く。"""
    kept = [line for line in text.strip().splitlines() if not line.startswith(NOISE_PREFIXES)]
    return "\n".join(kept[-lines:])


def show_tail(out: str, err: str = "", lines: int = 25) -> None:
    """子プロセスの出力の終わりを見せる。何も無ければ何も出さない。"""
    text = tail(out + "\n" + err, lines)
    if text:
        print(text)


def load_budgets() -> dict:
    """仮の上限の一覧（tools/budgets.json）。"""
    return json.loads(BUDGETS.read_text(encoding="utf-8"))


def finish(tool: str, code: int, summary: str) -> int:
    """最後の1行を出し、終了コードを返す。"""
    print(f"{tool}: {WORD[code]} {summary}")
    return code
