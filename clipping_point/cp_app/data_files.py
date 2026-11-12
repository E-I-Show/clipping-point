"""定義データのファイルを読む所。pyxel も js もimportしない。環境の辞書と、ブラウザの機能（js のモジュール）は、引数で受ける。

読むだけで、検査はしない。読み込み検査と、試験用データの重ね方は cp_core/datadefs.py（ファイルに触れない）。
  出荷する定義データ    このモジュールの場所から引く（clipping_point/data/）。作業ディレクトリに頼らない（pyxel.init が変える）。
                        ブラウザ版でも、展開された出荷物の中の、同じ場所から読める（段0 区切り8の実測）。
  試験用データ          リポジトリの根の testpacks/<名>/（出荷物の外）。デスクトップ版だけが、次の環境変数で重ねる。
      CP_DATA_PACK=<名>   1つだけ。名は id と同じ字で、43字まで。デスクトップ版の、どの起動でも読む（ふつうの起動、
                          画面なしで回す口、巡回の口）。名に当たる置き場が無い、置き場にファイルが1つも無い、名の字が違う、
                          のどれでも、重ねずに、起動時に ValueError。ブラウザ版は、環境の辞書を読まない。
置き場の下のファイルは、全部を読んで、名を挙げて渡す（2つの形に当たらない名も。問題にするのは datadefs）。
読めなかったファイル（OSError、UTF-8でない）は、値を None にして渡す。
呼ぶのは cp_app/app.py の main()。道具は、外から入った CP_DATA_PACK を子プロセスへ渡さない（tools/_common.py の APP_ENV_PREFIXES）。
"""
import os

from cp_core import datadefs

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # clipping_point/（出荷物の根）
DATA_DIR = os.path.join(APP_DIR, "data")  # 出荷する定義データの置き場
PACKS_ROOT = os.path.join(os.path.dirname(APP_DIR), datadefs.PACKS_DIR)  # 試験用データの根。出荷物には無い
PACK_ENV = "CP_DATA_PACK"  # デスクトップ版の、重ねる試験用データの名


def read_sources(directory) -> dict:
    """置き場の下の、全部のファイルを読む。返すのは「相対の名（/ 区切り）→ 文」の辞書（名を整列した順）。

    読めなかったファイルは、値が None。置き場が無ければ、空の辞書。
    """
    directory = os.fspath(directory)
    found = []
    # 割り切り：ディレクトリへのシンボリックリンクは、たどらない（その下のファイルは、名を挙げない）。空のディレクトリも、名を挙げない。
    # 定義データの置き場に、リンクを置く必要が出た時に見直す。
    for folder, dirs, names in os.walk(directory):
        dirs.sort()
        rel = os.path.relpath(folder, directory)
        parts = [] if rel == os.curdir else rel.split(os.sep)
        found += [("/".join([*parts, name]), os.path.join(folder, name)) for name in names]
    sources = {}
    for name, path in sorted(found):
        try:
            with open(path, encoding="utf-8") as f:
                sources[name] = f.read()
        except (OSError, ValueError):  # 読めない、UTF-8でない
            sources[name] = None
    return sources


def read_pack(name, root) -> tuple:
    """試験用データ（root/<名>/）を読む。返すのは (名, 「相対の名 → 文」の辞書)。

    名の字が違う、置き場が無い、置き場にファイルが1つも無い、のどれでも ValueError（空の置き場を、重ねたことにしない）。
    """
    datadefs.check_pack_name(name)
    directory = os.path.join(os.fspath(root), name)
    if not os.path.isdir(directory):
        raise ValueError(f"{PACK_ENV}: there is no test pack directory {datadefs.PACKS_DIR}/{name}")
    files = read_sources(directory)
    if not files:
        raise ValueError(f"{PACK_ENV}: the test pack directory {datadefs.PACKS_DIR}/{name} has no files (nothing would be overlaid)")
    return name, files


def load(env, js, data_dir=DATA_DIR, packs_root=PACKS_ROOT) -> datadefs.GameData:
    """定義データを読んで、読み込み検査を通す。問題があれば datadefs.DataError（全部の行を並べる）。

    js は、ブラウザの機能（デスクトップ版では None）。env は、環境の辞書（os.environ）。デスクトップ版だけが、
    CP_DATA_PACK を読んで、試験用データを重ねる。
    """
    sources = read_sources(data_dir)
    pack = None
    if js is None:
        name = env.get(PACK_ENV, "")
        if name:
            pack = read_pack(name, packs_root)
    return datadefs.load_game_data(sources, pack)
