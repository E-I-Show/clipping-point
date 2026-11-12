"""定義データの読み込み検査と、試験用データの重ね方（純Python）。決まりは docs/design/overview.md の「データと読み込み検査」。

ファイルには触れない。受けるのは「相対の名（/ 区切り）→ JSONの文」の辞書。ファイルを読むのは cp_app/data_files.py。
ファイルの形は2通りで、表の定義（TABLES）が、表ごとに持つ。
  1ファイル1表    <表>.json        中身は {"<表>": [項目, …]}。ほかの鍵は、注（_ で始まる鍵）だけ
  1ファイル1項目  <表>/<id>.json   中身は、項目そのもの。ファイルの名と id が同じ
表の定義は、表ごとに、ファイルの形と、項目の鍵ごとの規則の部品を持つ。規則の部品は、値を受けて、問題の文（無ければ None）を返す。
  Int、Num、Bool、Enum、Ident（id）、Label（表示名）、Ref（参照）、ListOf（並び）、Obj（入れ子の項目）、Opt（省ける項目）
  型は type(...) is で見る。bool を整数や数として受けない。文字列の数字を受けない。NaN と無限大は、数として受けない。
  並びと入れ子の項目の中は、読み込み検査が、鍵の道を付けて、最初の1件で止めずに並べる。
  Opt は、項目の鍵の規則にだけ使う（並びの中には置かない）。
読み込み検査が問題にするもの（最初の1件で止めず、全部を DataError に並べる。並びは、いつも同じ順）：
  読めないファイル、JSONでない文、重複した鍵、NaN と Infinity、ファイルの頭の形の誤り、知らないファイル（2つの形に当たらない名）、
  表のファイルが無い、表が空、知らない鍵、足りない鍵、型、範囲、id の重複、無い id への参照、ファイルの名と id の食い違い。
  参照は、全部の表を読んでから照らす（表を読む順に頼らない）。
  例外：JSONでない文、重複した鍵、NaN と Infinity のあるファイルは、項目を検査へ渡さない（並ぶのは、そのファイルの問題の行だけ）。
  項目をまたぐ検査（車の値の矛盾、コースの形の誤り）。表の定義が、関数（項目 → [(鍵の道, 問題の文)]）として持つ（TableDef.check）。
  呼ぶのは、鍵ごとの規則を全部通った項目だけ。関数が、計算の例外（0で割る、など）を出したら、その項目の問題の行に直す。
  車の検査は cp_core/vehicle.py、コースの検査は cp_core/track.py に置く（そちらからは、ここを読み込まない）。
問題の行の形：「cars.json:cars[0].name: …」「tracks/test_loop.json:name: …」。試験用データの中の問題は、頭に testpacks/<名>/ が付く。
警告：参照される側の表で、どこからも参照されていない定義。出荷するデータは0件（テストと道具 check が見張る）。
注：_ で始まる鍵は、どの階でも注。検査の外で、使う側へも渡さない。根拠の薄い値は、同じファイルの頭の _notes に
「仮の値：<根拠>。<合わせる時>」と書く。
試験用データ（testpacks/<名>/）は、同じ相対の名のファイルを重ねる。重ねた結果を、同じ読み込み検査に通す。元のデータは変えない。
  1ファイル1表    id が同じ項目を差し替え、新しい id を末尾に足す
  1ファイル1項目  同じ名のファイルで差し替え、新しい名で足す
  ファイルの頭の形が合わないファイルは、重ねない（問題にして並べる）。表のファイルが1つも無い試験用データも、問題にする。
重ねている間、ふつうの保存の名前空間は pack_<名>（main の代わり。GameData.save_namespace）。
読み込んだ定義（GameData）は、引くたびに、入れ子と並びの奥まで、新しい複製を渡す。使う側は、起動時やレースの開始時に
1度引いて持つ（毎tick引かない）。
"""
import json
import math
from dataclasses import dataclass

from cp_core import storage, track, vehicle

NAME_MAX = 14  # 表示名（車名、コース名）の字数の上限。変えるときは、画面と一緒に変える
ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")  # id に使える字（小文字のASCII、数字、_）
NOTE_PREFIX = "_"  # この字で始まる鍵は、どの階でも注
SUFFIX = ".json"  # 定義データのファイルの名の終わり
ONE_TABLE, ONE_ENTRY = "one_table", "one_entry"  # ファイルの形。1ファイル1表と、1ファイル1項目
ID_KEY = "id"  # どの表の項目も持つ鍵
PACKS_DIR = "testpacks"  # 試験用データの置き場の名（リポジトリの根の直下）。問題の行の頭に付ける
PACK_NAMESPACE_PREFIX = "pack_"  # 試験用データを重ねている間の、保存の名前空間の頭
# 試験用データの名の長さの上限（字）。保存の名前空間（48字まで）から、頭の pack_ の5字を引いた。
PACK_NAME_MAX = storage.KEY_MAX - len(PACK_NAMESPACE_PREFIX)


class DataError(ValueError):
    """読み込み検査の問題の一覧を持つ例外。文には、件数と、全部の行。"""

    def __init__(self, problems) -> None:
        self.problems = tuple(problems)
        super().__init__(f"{len(self.problems)} data problem(s):\n  " + "\n  ".join(self.problems))


def _kind(value) -> str:
    return type(value).__name__


# --- 規則の部品。check(値) は、問題の文を返す。無ければ None ---
class Int:
    """整数。low 以上（high があれば、high 以下）。bool、小数、文字列の数字を受けない。"""

    def __init__(self, low: int, high=None) -> None:
        self.low, self.high = low, high

    def check(self, value):
        if type(value) is not int:
            return f"expected an integer, got {_kind(value)}"
        if value < self.low or (self.high is not None and value > self.high):
            return f"{value} is outside {self.low}..{'' if self.high is None else self.high}"
        return None


class Num:
    """数（整数か小数）。low 以上、high 以下。bool、文字列の数字、NaN、無限大を受けない。"""

    def __init__(self, low, high) -> None:
        self.low, self.high = low, high

    def check(self, value):
        if type(value) not in (int, float):
            return f"expected a number, got {_kind(value)}"
        if type(value) is float and not math.isfinite(value):
            return f"{value} is not a finite number"
        if not self.low <= value <= self.high:
            return f"{value} is outside {self.low}..{self.high}"
        return None


class Bool:
    """真偽。整数の0と1を受けない。"""

    def check(self, value):
        return None if type(value) is bool else f"expected true or false, got {_kind(value)}"


class Enum:
    """列挙。決めた文字列のどれか。"""

    def __init__(self, *choices: str) -> None:
        self.choices = choices

    def check(self, value):
        if type(value) is not str or value not in self.choices:
            return f"{value!r} is not one of {list(self.choices)}"
        return None


class Ident:
    """id。小文字のASCII、数字、_ だけの、空でない文字列。"""

    def check(self, value):
        if type(value) is not str or not value or not all(char in ID_CHARS for char in value):
            return f"{value!r} is not an id (lowercase ASCII, digits, _)"
        return None


class Label:
    """表示名。内蔵フォントで出せる字（印字できるASCII）だけの、空でない文字列。字数は max_len まで。"""

    def __init__(self, max_len: int) -> None:
        self.max_len = max_len

    def check(self, value):
        if type(value) is not str or not value:
            return f"expected a non-empty text, got {value!r}"
        if not all(32 <= ord(char) <= 126 for char in value):
            return f"{value!r} has characters outside printable ASCII"
        if len(value) > self.max_len:
            return f"{value!r} is {len(value)} characters (at most {self.max_len})"
        return None


class Ref:
    """参照。表 table の、どれかの項目の id。あるかどうかは、全部の表を読んでから照らす。"""

    def __init__(self, table: str) -> None:
        self.table = table

    def check(self, value):
        return None if type(value) is str else f"expected an id of {self.table}, got {_kind(value)}"


class ListOf:
    """並び。長さは min_len 以上、max_len 以下。中の値は、item の規則で、1つずつ照らす。"""

    def __init__(self, item, min_len: int, max_len: int) -> None:
        self.item, self.min_len, self.max_len = item, min_len, max_len

    def check(self, value):
        if type(value) is not list:
            return f"expected a list, got {_kind(value)}"
        if not self.min_len <= len(value) <= self.max_len:
            return f"expected a list of {self.min_len}..{self.max_len} items, got {len(value)}"
        return None


class Obj:
    """入れ子の項目。鍵ごとの規則を持つ辞書。知らない鍵と足りない鍵は、問題。_ で始まる鍵は、注。"""

    def __init__(self, fields: dict) -> None:
        self.fields = dict(fields)

    def check(self, value):
        return None if type(value) is dict else f"expected an object, got {_kind(value)}"


class Opt:
    """省ける項目。鍵があれば、inner の規則で照らす。項目の鍵の規則にだけ使う。"""

    def __init__(self, inner) -> None:
        self.inner = inner


@dataclass(frozen=True)
class TableDef:
    """表の定義。"""

    layout: str  # ファイルの形。ONE_TABLE（<表>.json）か、ONE_ENTRY（<表>/<id>.json）
    fields: dict  # 項目の鍵 → 規則の部品。id（Ident）は、どの表も持つ
    # 項目をまたぐ検査。関数（項目 → [(項目の中の鍵の道, 問題の文)]）。無ければ None。鍵ごとの規則を全部通った項目にだけ呼ぶ。
    check: object = None


# 車の項目の鍵。鍵の名の終わりは単位。意味は cp_core/vehicle.py の CarSpec。0で割ることになる値は、範囲で0を外す。
CAR_FIELDS = {
    ID_KEY: Ident(), "name": Label(NAME_MAX), "data_version": Int(1),
    "body": Obj({
        "mass_kg": Num(100.0, 5000.0), "wheelbase_m": Num(1.0, 5.0), "track_m": Num(0.8, 3.0), "front_weight": Num(0.2, 0.8),
        "cg_height_m": Num(0.05, 1.5), "yaw_inertia_k": Num(0.3, 3.0), "half_length_m": Num(0.5, 5.0), "half_width_m": Num(0.3, 2.0),
    }),
    "steering": Obj({"max_steer_rad": Num(0.1, 1.2)}),
    "engine": Obj({
        "power_ps": Num(10.0, 2000.0), "idle_rpm": Num(300.0, 3000.0), "redline_rpm": Num(2000.0, 20000.0), "launch_rpm": Num(300.0, 20000.0),
        "torque_step_rpm": Num(5.0, 200.0), "engine_brake_k": Num(0.0, 1.0), "rpm_smooth_s": Num(0.001, 1.0),
        "torque_curve": ListOf(Obj({"rpm": Num(0.0, 20000.0), "ratio": Num(0.01, 2.0)}), 2, 32),
    }),
    "drivetrain": Obj({
        "front_drive": Num(0.0, 1.0), "gears": ListOf(Num(0.2, 10.0), 1, 8), "reverse_gear": Num(0.2, 10.0), "final_gear": Num(0.5, 10.0),
        "efficiency": Num(0.1, 1.0), "wheel_radius_m": Num(0.1, 1.0), "shift_up_rpm": Num(500.0, 20000.0),
        "shift_down_k": Num(0.1, 0.95), "shift_down_first_k": Num(0.1, 0.95), "shift_time_s": Num(0.0, 2.0),
    }),
    "lsd": Obj({"lock": Num(0.0, 1.0), "coupling_n_s_per_m": Num(0.0, 100000.0), "preload_n": Num(0.0, 10000.0), "ramp": Num(0.0, 2.0)}),
    "tires": Obj({
        "mu": Num(0.1, 3.0), "grip_front": Num(0.1, 2.0), "grip_rear": Num(0.1, 2.0), "peak_slip_rad": Num(0.02, 0.6),
        "curve_c": Num(1.05, 1.95), "ellipse_k": Num(0.0, 1.0), "spin_k": Num(0.0, 50.0), "slide_force": Num(0.1, 1.0),
        "slide_full_inv": Num(0.1, 100.0), "load_k": Num(0.0, 0.9), "rolling_resistance": Num(0.0, 0.2), "low_speed_reg_m_s": Num(0.05, 10.0),
    }),
    "suspension": Obj({"load_transfer_s": Num(0.005, 2.0), "roll_front": Num(0.0, 1.0)}),
    "brakes": Obj({"force_g": Num(0.1, 5.0), "front_share": Num(0.3, 0.95)}),
    "aero": Obj({"drag_area_m2": Num(0.0, 5.0), "lift_area_m2": Num(0.0, 10.0), "front_share": Num(0.0, 1.0)}),
    "rest": Obj({"speed_m_s": Num(0.0, 1.0), "yaw_rate_rad_s": Num(0.0, 1.0)}),
    "outputs": Obj({
        "slip_min_speed_m_s": Num(0.0, 10.0), "slip_speed_floor_m_s": Num(0.01, 10.0),
        "limit_min_speed_m_s": Num(0.0, 10.0), "yaw_ref_min_speed_m_s": Num(0.0, 50.0),
    }),
}
# コースの項目の鍵。意味は cp_core/track.py。制御点は、頭の点を、末尾に繰り返さない。
TRACK_FIELDS = {
    ID_KEY: Ident(), "name": Label(NAME_MAX), "data_version": Int(1),
    "table": Obj({"sample_step_m": Num(0.5, 8.0), "dense_step_m": Num(0.05, 1.0)}),
    "width_m": Num(4.0, 30.0),
    "grass_m": Num(0.0, 60.0),
    "surface_mu": Obj({track.SURFACE_ASPHALT: Num(0.05, 2.0), track.SURFACE_GRASS: Num(0.05, 2.0)}),
    "wall": Obj({"restitution": Num(0.0, 1.0), "friction": Num(0.0, 2.0)}),
    "start": Obj({"s_m": Num(0.0, track.MAX_LENGTH_M), "lateral_m": Num(-30.0, 30.0)}),
    "control_points": ListOf(Obj({"x_m": Num(-track.MAX_LENGTH_M, track.MAX_LENGTH_M), "z_m": Num(-track.MAX_LENGTH_M, track.MAX_LENGTH_M)}), track.MIN_POINTS, 2000),
}
# 操作補正の項目の鍵。意味は cp_core/controls.py の ControlParams。いまは、仮の1組だけ（段階と既定の組は、段1）。
STEER_SET_FIELDS = {"limit_ka": Num(0.0, 5.0), "limit_km": Num(0.0, 2.0), "full_time_s": Num(0.01, 5.0)}
ASSIST_FIELDS = {
    ID_KEY: Ident(),
    "steer": Obj({
        "limit_mu_min": Num(0.05, 2.0), "limit_min_speed_m_s": Num(0.1, 50.0),
        "analog": Obj(STEER_SET_FIELDS), "digital": Obj(STEER_SET_FIELDS),
    }),
    "reverse": Obj({"stop_speed_m_s": Num(0.01, 10.0), "brake_hold_s": Num(0.0, 10.0), "pedal_press_min": Num(0.001, 1.0)}),
}
# 実物の表の定義。表を足す、項目を足すときは、実物のファイルと、壊した場合のテスト（tests/test_datadefs.py）も足す。
TABLES = {
    "cars": TableDef(ONE_TABLE, CAR_FIELDS, vehicle.spec_problems),
    "tracks": TableDef(ONE_ENTRY, TRACK_FIELDS, track.shape_problems),
    "assists": TableDef(ONE_TABLE, ASSIST_FIELDS),
}


def check_pack_name(name) -> str:
    """試験用データの名の検査。id と同じ字で、1〜43字（保存の名前空間 pack_<名> が、48字に収まる）。外れたら ValueError。"""
    if type(name) is not str or not name or len(name) > PACK_NAME_MAX or not all(char in ID_CHARS for char in name):
        raise ValueError(f"bad test pack name {name!r} (lowercase ASCII, digits, _ ; 1 to {PACK_NAME_MAX} characters)")
    return name


class GameData:
    """読み込んだ定義。読み込み検査を通ったものだけが、これになる。"""

    def __init__(self, entries: dict, warnings, pack) -> None:
        self._entries = entries  # {表: {id: 項目}}。並びは、ファイルの順。注の鍵は、落としてある
        self.warnings = tuple(warnings)  # 警告の一覧（どこからも参照されていない定義）
        self.pack = pack  # 重ねた試験用データの名。無ければ None

    @property
    def save_namespace(self) -> str:
        """ふつうの保存の名前空間。試験用データを重ねている間は pack_<名>（ふだんの保存に触れない）。"""
        return storage.DEFAULT_NAMESPACE if self.pack is None else PACK_NAMESPACE_PREFIX + self.pack

    def counts(self) -> dict:
        """表ごとの件数。{表: 項目の数}。"""
        return {table: len(rows) for table, rows in self._entries.items()}

    def ids(self, table: str) -> tuple:
        """表の id の並び（ファイルの順）。無い表は KeyError。"""
        return tuple(self._entries[table])

    def entry(self, table: str, ident: str) -> dict:
        """項目1つ。入れ子と並びの奥まで、新しい複製。無い表と、無い id は KeyError。毎tick引かない（1度引いて持つ）。"""
        return _copy(self._entries[table][ident])


def _copy(value, drop_notes: bool = False):
    """辞書と並びを、奥まで作り直す。ほかの値は、そのまま。drop_notes なら、注の鍵を落とす。"""
    if type(value) is dict:
        return {key: _copy(item, drop_notes) for key, item in value.items() if not (drop_notes and key.startswith(NOTE_PREFIX))}
    if type(value) is list:
        return [_copy(item, drop_notes) for item in value]
    return value


def _line(label: str, path: tuple, message: str) -> str:
    """問題の行。label はファイル、path は鍵の道（鍵の名と、並びの中の番号）。"""
    where = ""
    for part in path:
        where += f"[{part}]" if type(part) is int else f".{part}" if where else part
    return f"{label}:{where}: {message}" if where else f"{label}: {message}"


def _ref_targets(rule, found: list) -> None:
    """規則の部品の中の、参照の先の表の名を、found に足す。"""
    if isinstance(rule, Opt):
        _ref_targets(rule.inner, found)
    elif isinstance(rule, ListOf):
        _ref_targets(rule.item, found)
    elif isinstance(rule, Obj):
        for inner in rule.fields.values():
            _ref_targets(inner, found)
    elif isinstance(rule, Ref):
        found.append(rule.table)


def _check_tables(tables: dict) -> list:
    """表の定義そのものの検査。返すのは、参照される側の表の名（表の定義の順）。誤りは ValueError（データの問題ではない）。"""
    found = []
    for name, table in tables.items():
        if table.layout not in (ONE_TABLE, ONE_ENTRY):
            raise ValueError(f"table {name!r}: unknown layout {table.layout!r}")
        if not isinstance(table.fields.get(ID_KEY), Ident):
            raise ValueError(f"table {name!r}: every table needs the key {ID_KEY!r} with the rule Ident()")
        for rule in table.fields.values():
            _ref_targets(rule, found)
    strange = [target for target in found if target not in tables]
    if strange:
        raise ValueError(f"a reference points to a table that is not defined: {strange}")
    return [name for name in tables if name in found]


def _parse_json(text: str) -> tuple:
    """JSONの文を読む。返すのは (値, 問題の文の一覧)。重複した鍵と、NaN、Infinity も、問題にする。"""
    # 割り切り：重複した鍵か、NaN・無限大のあるファイルは、JSONとして読めないファイルと同じ扱いにする。そのファイルの項目は、
    # 検査へ渡さない。並ぶのは、そのファイルの、JSONの文を読む所の問題の行だけで、同じファイルのほかの問題は、直して回し直すまで
    # 出ない（その表を参照する側には「無い id への参照」が並ぶ）。後勝ちの値で検査を続けると、誤った値を検査して、原因と違う行が
    # 並ぶので、続けない。問題の行は、ファイルと鍵の名までで、何番目の項目かは出ない（標準のJSONの読みは、場所を渡さない）。
    # 表が大きくなって、問題の行だけでは直す所を見つけにくくなった時に見直す。段0 区切り9で、車の値とコースの形が入ったが、
    # 車は1台、コースは1本なので、ファイルと鍵の名で足りている。4車種とアカネ・ショートが入る段1で、もう一度見る。
    found = []

    def pairs(items):
        seen = {}
        for key, value in items:
            if key in seen:
                found.append(f"duplicate key {key!r}")
            seen[key] = value
        return seen

    def constant(name):
        found.append(f"{name} is not accepted (not a JSON number)")
        return None

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except RecursionError:
        return None, ["cannot read: nested too deep"]
    except ValueError as exc:
        return None, [f"cannot read: not JSON ({exc})"]
    return value, found


def _classify(name: str, tables: dict):
    """相対の名が、どの表のファイルか。返すのは (表の名, 1ファイル1項目のファイルの名の頭)。2つの形に当たらなければ None。"""
    if not name.endswith(SUFFIX):
        return None
    parts = name[:-len(SUFFIX)].split("/")
    table = tables.get(parts[0])
    if table is None or not parts[-1]:
        return None
    if len(parts) == 1 and table.layout == ONE_TABLE:
        return parts[0], None
    if len(parts) == 2 and table.layout == ONE_ENTRY:
        return parts[0], parts[1]
    return None


class _Item:
    """読んだ項目1つ。"""

    __slots__ = ("table", "label", "path", "entry", "key", "has_id")

    def __init__(self, table: str, label: str, path: tuple, entry: dict, key, has_id: bool) -> None:
        self.table = table  # 表の名
        self.label = label  # 問題の行の頭に付ける、ファイルの名
        self.path = path  # ファイルの中での、項目までの鍵の道
        self.entry = entry  # 項目（辞書）
        self.key = key  # 重ねるときに突き合わせる名。1ファイル1表は id、1ファイル1項目はファイルの名の頭。id が無ければ None
        self.has_id = has_id  # id が文字列か


def _id_shape(entry: dict) -> str:
    return "missing" if ID_KEY not in entry else f"expected a string id, got {_kind(entry[ID_KEY])}"


def _parse_file(name: str, table: TableDef, stem, label: str, text, problems: list) -> tuple:
    """表のファイル1つを読んで、頭の形を見る。返すのは (頭の形が合っているか, 項目の一覧)。問題は problems に足す。"""
    if type(text) is not str:
        problems.append(f"{label}: cannot read the file")
        return False, []
    value, found = _parse_json(text)
    if found:
        # JSONでない文、重複した鍵、NaN・無限大。どれも、このファイルの項目を検査へ渡さない（_parse_json の割り切りの注）。
        problems.extend(f"{label}: {message}" for message in found)
        return False, []
    if table.layout == ONE_ENTRY:
        if type(value) is not dict:
            problems.append(f"{label}: the file must be one entry (an object), got {_kind(value)}")
            return False, []
        has_id = type(value.get(ID_KEY)) is str
        if not has_id:
            problems.append(_line(label, (ID_KEY,), _id_shape(value)))
        elif value[ID_KEY] != stem:
            problems.append(_line(label, (ID_KEY,), f"{value[ID_KEY]!r} does not match the file name {stem!r}"))
        return has_id, [_Item(name, label, (), value, stem, has_id)]
    if type(value) is not dict:
        problems.append(f'{label}: the file must be {{"{name}": [...]}}, got {_kind(value)}')
        return False, []
    ok = True
    for key in sorted(key for key in value if key != name and not key.startswith(NOTE_PREFIX)):
        problems.append(_line(label, (key,), f"unknown key at the top level (only {name!r} and notes)"))
        ok = False
    if name not in value:
        problems.append(_line(label, (name,), f'missing (the file must be {{"{name}": [...]}})'))
        return False, []
    rows = value[name]
    if type(rows) is not list:
        problems.append(_line(label, (name,), f"expected a list of entries, got {_kind(rows)}"))
        return False, []
    if not rows:
        problems.append(_line(label, (name,), "no entries"))
        return False, []
    items = []
    for index, entry in enumerate(rows):
        path = (name, index)
        if type(entry) is not dict:
            problems.append(_line(label, path, f"expected an entry (an object), got {_kind(entry)}"))
            ok = False
            continue
        has_id = type(entry.get(ID_KEY)) is str
        if not has_id:
            problems.append(_line(label, (*path, ID_KEY), _id_shape(entry)))
            ok = False
        items.append(_Item(name, label, path, entry, entry[ID_KEY] if has_id else None, has_id))
    return ok, items


def _read_files(sources: dict, prefix: str, tables: dict, problems: list) -> list:
    """置き場1つの、全部のファイルを読む。返すのは [(表の名, 頭の形が合っているか, 項目の一覧)]（名を整列した順）。"""
    files = []
    for name in sorted(sources):
        label = prefix + name
        hit = _classify(name, tables)
        if hit is None:
            problems.append(f"{label}: unknown file (no table reads this name)")
            continue
        table, stem = hit
        ok, items = _parse_file(table, tables[table], stem, label, sources[name], problems)
        files.append((table, ok, items))
    return files


def _place(items: list, target: list, loose: list, problems: list) -> None:
    """項目を、表の並び（target）へ置く。同じ名の項目は差し替え、新しい名は末尾に足す。

    id が無い項目と、同じファイルの中で id が重なった項目は、置かずに loose へ回す（鍵ごとの規則だけ照らす）。
    """
    index_of = {item.key: index for index, item in enumerate(target)}
    placed = set()
    for item in items:
        if item.key is None:
            loose.append(item)
            continue
        if item.key in placed:
            problems.append(_line(item.label, (*item.path, ID_KEY), f"duplicate id {item.key!r}"))
            loose.append(item)
            continue
        placed.add(item.key)
        if item.key in index_of:
            target[index_of[item.key]] = item
        else:
            index_of[item.key] = len(target)
            target.append(item)


def _walk(rule, value, path: tuple, found: list, refs: list) -> None:
    """値1つを、規則の部品と照らす。問題は found に (鍵の道, 文)、参照は refs に (鍵の道, 表, id) で足す。"""
    message = rule.check(value)
    if message is not None:
        found.append((path, message))
    if isinstance(rule, ListOf) and type(value) is list:
        for index, item in enumerate(value):
            _walk(rule.item, item, (*path, index), found, refs)
    elif isinstance(rule, Obj) and type(value) is dict:
        _walk_fields(rule.fields, value, path, found, refs)
    elif isinstance(rule, Ref) and message is None:
        refs.append((path, rule.table, value))


def _walk_fields(fields: dict, entry: dict, path: tuple, found: list, refs: list, skip: tuple = ()) -> None:
    """辞書1つを、鍵ごとの規則と照らす。知らない鍵、足りない鍵、鍵ごとの値。skip の鍵は見ない（先に問題にしてある）。"""
    for key in sorted(key for key in entry if key not in fields and not key.startswith(NOTE_PREFIX)):
        found.append(((*path, key), "unknown key"))
    for key, rule in fields.items():
        if key in skip:
            continue
        optional = isinstance(rule, Opt)
        if key not in entry:
            if not optional:
                found.append(((*path, key), "missing"))
            continue
        _walk(rule.inner if optional else rule, entry[key], (*path, key), found, refs)


def _check_item(item: _Item, tables: dict, problems: list, refs) -> None:
    """項目1つを、表の定義と照らす。refs が None なら、参照は集めない（重ねた結果に入らない項目）。"""
    found, item_refs = [], []
    definition = tables[item.table]
    _walk_fields(definition.fields, item.entry, item.path, found, item_refs, () if item.has_id else (ID_KEY,))
    if not found and item.has_id and definition.check is not None:
        # 項目をまたぐ検査。鍵ごとの規則を全部通った項目にだけ呼ぶ（規則を通らない値で、計算を始めない）。注の鍵は、落として渡す。
        # 検査の関数が、計算の例外（0で割る、表の外を引く、など）を出したら、その項目の問題の行に直す（DataError のほかの例外を、外へ出さない。
        # 規則を通った値でも、形によっては、表を作る計算が止まる。例外の型の名は、行に出す）。
        try:
            found += [((*item.path, *path), message) for path, message in definition.check(_copy(item.entry, drop_notes=True))]
        except Exception as exc:  # noqa: BLE001 - どの例外も、その項目の問題の行にする
            found.append((item.path, f"cannot check the entry ({type(exc).__name__}: {exc})"))
    problems.extend(_line(item.label, path, message) for path, message in found)
    if refs is not None:
        refs.extend((item.label, path, table, ident) for path, table, ident in item_refs)


def load_game_data(sources: dict, pack=None, tables: dict = TABLES) -> GameData:
    """定義データを読んで、読み込み検査を通す。問題が1件でもあれば DataError（全部の行を並べる）。

    sources は、出荷するデータの「相対の名 → 文」の辞書。値が文字列でなければ（読めなかったファイル）、そのファイルの問題。
    pack は、重ねる試験用データ（(名, 「相対の名 → 文」の辞書)）。無ければ None。名の誤りは ValueError。
    tables は、表の定義。既定は、実物の表の定義。
    """
    targets = _check_tables(tables)
    problems = []
    merged = {name: [] for name in tables}  # 表ごとの、重ねた結果の項目（ファイルの順）
    loose = []  # 重ねた結果に入らない項目（id が無い、id の重複、重ねなかったファイルの項目）
    has_file = dict.fromkeys(tables, False)
    for table, _, items in _read_files(sources, "", tables, problems):
        has_file[table] = True
        _place(items, merged[table], loose, problems)
    for name, table in tables.items():
        if not has_file[name]:
            problems.append(f"{name}{SUFFIX}: missing file" if table.layout == ONE_TABLE else f"{name}/: no entry files")
    pack_name = None
    if pack is not None:
        pack_name, pack_sources = pack
        check_pack_name(pack_name)
        prefix = f"{PACKS_DIR}/{pack_name}/"
        files = _read_files(pack_sources, prefix, tables, problems)
        if not files:
            problems.append(f"{prefix}: no table files (nothing would be overlaid)")
        for table, ok, items in files:
            if ok:
                _place(items, merged[table], loose, problems)
            else:
                loose.extend(items)  # 頭の形が合わないファイルは、重ねない
    refs = []
    for name in tables:
        for item in merged[name]:
            _check_item(item, tables, problems, refs)
    for item in loose:
        _check_item(item, tables, problems, None)
    # 参照は、全部の表を読んでから照らす。
    ids = {name: [item.entry[ID_KEY] for item in merged[name] if item.has_id] for name in tables}
    used = {name: set() for name in targets}
    for label, path, target, ident in refs:
        if ident in ids[target]:
            used[target].add(ident)
        else:
            problems.append(_line(label, path, f"no {target} with id {ident!r}"))
    if problems:
        raise DataError(problems)
    warnings = [f"{name}.{ident}: defined but never referenced" for name in targets for ident in ids[name] if ident not in used[name]]
    entries = {name: {item.entry[ID_KEY]: _copy(item.entry, drop_notes=True) for item in merged[name]} for name in tables}
    return GameData(entries, warnings, pack_name)
