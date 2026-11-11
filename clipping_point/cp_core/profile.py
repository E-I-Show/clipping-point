"""保存する項目（純Python）。決まりは docs/design/overview.md の「決定性と保存」の「保存するもの」。

いまは「設定」だけ（音量、変速、アシスト、視点、レースの通し番号）。操作設定、タイムの記録、セッティング、リプレイ、ゴーストは、作る段で足す。
保存は、保存の口（cp_core.storage の SaveStore）だけを通す。本体は JSON（鍵の順をそろえ、空白を入れない。UTF-8）。
読むときは、知らない項目、足りない項目、型や範囲の外を、どれも読めない値として扱う（半分だけ読まない）。
項目を足す、消す、型を変えるときは、形式バージョンを上げるか、NOT_SAVED に理由つきで入れるかを決める。
保存する項目の一覧の写し（tests/snapshots/profile_schema.json）が、決めずに変えたことを拾う（項目の名と型だけ。schema() の注）。
形式バージョンの決まり：
  人にHTMLを渡す前（段0の間）     形式バージョンを1のままにしてよい（古い保存が、まだ人の手元に無い）
  渡した後（段0の仕上げから後）    保存する項目、型、範囲、選べる値を変えるたびに、形式バージョンを上げる。人の手元のブラウザに、
                                   前のHTMLの保存が残っている。据え置くと、前のHTMLが、新しいHTMLの設定を、壊れた値として退避し、
                                   次に新しいHTMLを開いたときに、退避した値も上書きされる。上げてあれば、前のHTMLは触れずに残す
  公開（段4の終わり）まで          移行を書かずに、古い形式バージョンの値を退避でよい（人の試しのデータ）
  公開の後                         上げるたびに、移行を書く（MIGRATIONS）。移行の関数は、残し続ける

読み込み（load_settings）は、StorageError を外へ出さない（起動時に通るので、例外が出ると、起動のたびに止まる）。
結果は、値、知らせの1行、その鍵に書いてよいか、の3つ。
  鍵が無い                                   既定値、知らせ無し、書いてよい。保存先には何もしない
  いまの形式バージョンで、読めた             読んだ値、知らせ無し、書いてよい
  古い形式バージョンで、移行が全部通った     移行した値、知らせ無し、書いてよい（書き直しは、次の保存で）
  新しい形式バージョン                       既定値、新しい形式バージョンの文、書いてよくない。保存先には何もしない
  壊れた値                                   既定値、読めないの文、書いてよい。「<鍵>.bad」へ退避して、既定値で書き直す
      （封筒が読めない、本体が読めない、移行の表に無い古い形式バージョン、移行が失敗。書き直しが失敗しても、結果は変えない）
  壊れた値で、退避が失敗した                 既定値、読めないの文、書いてよくない。元の鍵に触れない
  保存先の読みが失敗した                     既定値、保存先が読めないの文、書いてよくない。保存先には何もしない
「書いてよいか」は、画面に出すための知らせ。新しい形式バージョンの値を上書きしない守りは、保存の口の put にある。
"""
import json
from dataclasses import dataclass, fields

from cp_core.storage import (
    NOTICE_BACKEND_UNREADABLE,
    NOTICE_NEWER_VERSION,
    NOTICE_UNREADABLE,
    CorruptError,
    SaveStore,
    StorageError,
)

SETTINGS_KEY = "settings"  # 設定の、保存の鍵
SETTINGS_VERSION = 1  # 設定の、いまの形式バージョン
# 移行の表。{古い形式バージョン: 関数}。関数は、その形式バージョンの本体（JSONを読んだ辞書）を受けて、次の形式バージョンの辞書を返す。
# 古い形式バージョンの値は、いまの形式バージョンになるまで、順に通す。いまは、古い形式バージョンが無いので空。
MIGRATIONS = {}
# 保存しない項目。{"クラス.項目": "理由"}。ここに無い項目は、全部保存する。いまは、保存しない項目が無い。
NOT_SAVED = {}
SELFCHECK_NAMESPACE = "selfcheck"  # 検証の口で、保存の往復を回す名前空間。ふつうの保存（main）には触れない
# 仮の値：設定の項目、範囲、既定値は、設計の「保存するもの」の表から置いた（音量は0〜10の11段階で、既定は真ん中）。
# 設定を使う所（音、変速、アシスト、視点、レース）を作る段1で合わせる。既定値を定義データへ移すかも、その区切りで決める。
VOLUME_MIN, VOLUME_MAX = 0, 10
TRANSMISSIONS = ("AT", "MT")
VIEWS = ("chase", "bumper")  # 視点。後方追従と、バンパー


class ProfileError(ValueError):
    """保存の本体が、保存する項目として読めない。load_settings の外へは出ない。"""


def _int_in(name: str, value, low: int, high) -> None:
    """bool でない整数で、low 以上（high があれば、high 以下）。"""
    if type(value) is not int:
        raise TypeError(f"{name}={value!r} must be int (bool and float are not accepted)")
    if value < low or (high is not None and value > high):
        raise ValueError(f"{name}={value!r} must be in {low}..{'' if high is None else high}")


def _one_of(name: str, value, allowed: tuple) -> None:
    if type(value) is not str:
        raise TypeError(f"{name}={value!r} must be str")
    if value not in allowed:
        raise ValueError(f"{name}={value!r} must be one of {allowed}")


@dataclass(frozen=True)
class Settings:
    """設定。作るときに、型と範囲を検査する。bool を整数の項目に、整数を bool の項目に受けない（JSONの true と 1 を取り違えない）。"""

    sfx_volume: int = 5  # 効果音の音量。0〜10
    bgm_volume: int = 5  # BGMの音量。0〜10
    transmission: str = "AT"  # 変速。"AT" か "MT"
    assist: bool = True  # アシスト。ON が真
    view: str = "chase"  # 視点。"chase"（後方追従）か "bumper"（バンパー）
    race_serial: int = 0  # レースの通し番号。0以上

    def __post_init__(self) -> None:
        _int_in("sfx_volume", self.sfx_volume, VOLUME_MIN, VOLUME_MAX)
        _int_in("bgm_volume", self.bgm_volume, VOLUME_MIN, VOLUME_MAX)
        _one_of("transmission", self.transmission, TRANSMISSIONS)
        if type(self.assist) is not bool:
            raise TypeError(f"assist={self.assist!r} must be bool (int is not accepted)")
        _one_of("view", self.view, VIEWS)
        _int_in("race_serial", self.race_serial, 0, None)


SAVED_CLASSES = (Settings,)  # 保存する項目を持つ型。保存する項目の一覧（schema）は、ここから作る
# 往復の見本。全部の項目が、既定値と違う設定。アプリの保存の往復（selfcheck）、テストの往復、道具が使う。
SELFCHECK_SETTINGS = Settings(sfx_volume=3, bgm_volume=8, transmission="MT", assist=False, view="bumper", race_serial=12)


@dataclass(frozen=True)
class Loaded:
    """読み込みの結果。"""

    settings: Settings  # 値
    notice: str  # 知らせの1行。無ければ空
    writable: bool  # その鍵に書いてよいか。画面に出すための知らせで、守りではない（守りは SaveStore.put）


def saved_names(cls) -> tuple:
    """cls の、保存する項目の名（NOT_SAVED に無いもの）。"""
    return tuple(field.name for field in fields(cls) if f"{cls.__name__}.{field.name}" not in NOT_SAVED)


def schema() -> dict:
    """保存する項目の一覧。形式バージョンと、{"クラス.項目": "型の名"}。保存する項目の一覧の写し（tests/snapshots/profile_schema.json）は、これから作る。"""
    # 割り切り：一覧は、項目の名と型だけを持つ。範囲（音量の0〜10）と、選べる値（変速、視点）の変更は拾わない
    # （変えて、形式バージョンを上げ忘れても、一覧の写しのテストは落ちない）。設定の項目を作り直す段1で、範囲と選べる値も一覧に入れる。
    saved = {}
    for cls in SAVED_CLASSES:
        types = {field.name: field.type for field in fields(cls)}
        for name in saved_names(cls):
            saved[f"{cls.__name__}.{name}"] = types[name] if isinstance(types[name], str) else types[name].__name__
    return {"version": SETTINGS_VERSION, "fields": saved}


def to_plain(settings: Settings) -> dict:
    """設定を、JSONにそのまま書ける辞書にする。保存しない項目は入れない。"""
    if type(settings) is not Settings:
        raise TypeError(f"settings must be a Settings, got {type(settings).__name__}")
    return {name: getattr(settings, name) for name in saved_names(Settings)}


def from_plain(data) -> Settings:
    """to_plain の逆。知らない項目、足りない項目、型や範囲の外は ProfileError（半分だけ読まない）。"""
    if type(data) is not dict:
        raise ProfileError(f"settings must be an object, got {type(data).__name__}")
    names = saved_names(Settings)
    unknown, missing = sorted(set(data) - set(names)), sorted(set(names) - set(data))
    if unknown or missing:
        raise ProfileError(f"settings: unknown items {unknown}, missing items {missing}")
    try:
        return Settings(**data)
    except (TypeError, ValueError) as exc:
        raise ProfileError(f"settings: {exc}") from exc


def encode(settings: Settings) -> bytes:
    """設定を、保存の本体にする。JSON（鍵の順をそろえ、空白を入れない。UTF-8）。"""
    return json.dumps(to_plain(settings), sort_keys=True, separators=(",", ":")).encode("utf-8")


def decode(payload: bytes, version: int = SETTINGS_VERSION, migrations=MIGRATIONS) -> Settings:
    """保存の本体を、設定にする。version が古ければ、移行の表を、いまの形式バージョンになるまで順に通す。読めなければ ProfileError。"""
    try:
        data = json.loads(payload.decode("utf-8"))
    except (ValueError, RecursionError) as exc:  # UTF-8でない、JSONでない、入れ子が深すぎる
        raise ProfileError(f"settings: not JSON: {type(exc).__name__}: {exc}") from exc
    if type(version) is not int or not 1 <= version <= SETTINGS_VERSION:
        raise ProfileError(f"settings: format version {version!r} cannot be read (this build reads up to {SETTINGS_VERSION})")
    while version < SETTINGS_VERSION:
        migrate = migrations.get(version)
        if migrate is None:
            raise ProfileError(f"settings: no migration from format version {version}")
        try:
            data = migrate(data)
        except Exception as exc:  # noqa: BLE001 - 移行の関数の中の、どの失敗も、読めない値として扱う
            raise ProfileError(f"settings: migration from format version {version} failed: {type(exc).__name__}: {exc}") from exc
        version += 1
    return from_plain(data)


def save_settings(store: SaveStore, settings: Settings) -> None:
    """設定を保存する。StorageError（書けない、新しい形式バージョンの値がある、など）は、そのまま外へ出す。

    呼ぶ側が、画面に1行で知らせる。段0で呼ぶのは、検証の往復（selfcheck）と、壊れた値の書き直しだけ。
    """
    store.put(SETTINGS_KEY, encode(settings), SETTINGS_VERSION)


def load_settings(store: SaveStore, migrations=MIGRATIONS) -> Loaded:
    """設定を読み込む。StorageError（子を含む）を外へ出さない。場合ごとの扱いは、頭の注の表のとおり。"""
    try:
        got = store.get(SETTINGS_KEY)
    except CorruptError:
        return _set_aside(store)
    except StorageError:
        return Loaded(Settings(), NOTICE_BACKEND_UNREADABLE, False)
    if got is None:
        return Loaded(Settings(), "", True)
    version, payload = got
    if version > SETTINGS_VERSION:
        return Loaded(Settings(), NOTICE_NEWER_VERSION, False)
    try:
        settings = decode(payload, version, migrations)
    except ProfileError:
        return _set_aside(store)
    return Loaded(settings, "", True)


def _set_aside(store: SaveStore) -> Loaded:
    """壊れた値の扱い。「<鍵>.bad」へ退避して、既定値で書き直す。"""
    try:
        store.quarantine(SETTINGS_KEY)
    except StorageError:
        return Loaded(Settings(), NOTICE_UNREADABLE, False)  # 退避できない。元の鍵に触れない
    try:
        save_settings(store, Settings())
    except StorageError:
        pass  # 書き直しが失敗しても、結果は変えない（鍵が無い状態と同じ）
    return Loaded(Settings(), NOTICE_UNREADABLE, True)


def selfcheck(backend) -> tuple:
    """保存の往復。検証の口（画面なしで回す口と、外から渡す値）のときだけ、アプリが回す。返すのは (通ったか, 失敗の理由)。

    名前空間 selfcheck で回し、ふつうの鍵（名前空間 main）には触れない。
    手順：鍵を消す → 無いことを確かめる → 往復の見本を書く → 読み直して同じ。書いた鍵は、消さずに残す
    （道具が、保存先の中身を自分で読んで照らす）。StorageError を外へ出さない（失敗の理由に入れて返す）。
    """
    try:
        store = SaveStore(backend, SELFCHECK_NAMESPACE)
        store.delete(SETTINGS_KEY)
        if store.get(SETTINGS_KEY) is not None:
            return False, "the key is still there after delete"
        save_settings(store, SELFCHECK_SETTINGS)
        if store.get(SETTINGS_KEY) != (SETTINGS_VERSION, encode(SELFCHECK_SETTINGS)):
            return False, "the stored envelope is not the one that was written"
        loaded = load_settings(store)
    except StorageError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if loaded.settings != SELFCHECK_SETTINGS or loaded.notice or not loaded.writable:
        return False, f"read back {loaded.settings!r} with notice {loaded.notice!r}"
    return True, ""
