"""カメラ（純Python）。位置と向きの計算、塊が見えるかの判定、背景をずらす量、判定用の柱。決まりは docs/design/overview.md の「描画」。

ここで返す位置は、全部、ロジックの座標（平面が (x, z)、高さが y。+z は、+x の左。向きは +x が 0、+z が +π/2 で、増えると左旋回）。
Pyxelの3Dへ渡すときの、z の反転は、cp_app/render.py の1つの関数が行う（ここでは、反転しない）。
  後方追従（chase_pose）  車の後方 back m、高さ height m から、車の前方 look_ahead m、高さ look_height m を見る。
                          車の位置と向きに、そのまま付いていく（遅れや、ならしは、入れない）
  見えるかの判定（chunk_visible）  塊の中心までの距離が、奥＋半径より近く、前方への射影が、−半径より大きい（平面で見る）
  背景（backdrop_*、horizon_row）  空と山並みの横長の絵を、カメラの向きで、横にずらして写すための量。画角は、縦の画角
                          （Pyxelの3Dの fov。試作の記録）。焦点距離（画素）は、(画面の高さ÷2)÷tan(画角÷2)
  判定用の柱（pillar_positions、pillar_parts）  検証の口があるときにだけ使う、左右の向きの目印。車の左前と右前に置く
カメラの値（CameraSpec）は、定義データの表 cameras の項目から作る（spec_from_entry）。いまは、後方追従（CHASE）だけ。
バンパーの視点、TVカメラ、ヘリは、後の段（段1の「走行画面」、段2）。
"""
from dataclasses import dataclass
from math import atan2, cos, floor, hypot, pi, radians, sin, tan

from cp_core import mesh

TWO_PI = 2.0 * pi
CHASE = "chase"  # 表 cameras の、後方追従の項目の id
# 判定用の柱（左右の向きの目印）。調整する値ではなく、検証の決め（道具の判定の余裕 tools/budgets.json と、対で決める）。
PILLAR_AHEAD_M = 8.0  # 柱を置く所。車の前方へ（m）
PILLAR_SIDE_M = 3.0  # 同じく、車の横へ（m）。左の柱は左へ、右の柱は右へ
PILLAR_WIDTH_M = 0.5  # 柱の板の幅（m）
PILLAR_HEIGHT_M = 2.0  # 柱の板の高さ（m）。地面から立てる
PILLAR_LEFT, PILLAR_RIGHT = "pillar_left", "pillar_right"  # 柱の名（部品の名。結果の鍵にも使う）
PILLAR_ROLES = {PILLAR_LEFT: "red", PILLAR_RIGHT: "blue"}  # 柱の、色の役割の名。2本は、違う色


@dataclass(frozen=True, slots=True)
class CameraSpec:
    """カメラの値。定義データの表 cameras の項目から作る（spec_from_entry）。書き換えられない。"""

    camera_id: str  # カメラの id
    back: float  # 目の位置。車の後方へ（m）
    height: float  # 目の高さ（m）
    look_ahead: float  # 注視点。車の前方へ（m）
    look_height: float  # 注視点の高さ（m）
    fov_deg: float  # 画角（度。縦）
    near: float  # 手前の切り取り面（m）
    far: float  # 奥の切り取り面（m）


def spec_from_entry(entry: dict) -> CameraSpec:
    """定義データの表 cameras の項目（読み込み検査を通ったもの。GameData.entry("cameras", id)）から、カメラの値を作る。"""
    return CameraSpec(
        camera_id=entry["id"],
        back=float(entry["back_m"]),
        height=float(entry["height_m"]),
        look_ahead=float(entry["look_ahead_m"]),
        look_height=float(entry["look_height_m"]),
        fov_deg=float(entry["fov_deg"]),
        near=float(entry["near_m"]),
        far=float(entry["far_m"]),
    )


@dataclass(frozen=True, slots=True)
class CameraPose:
    """カメラの位置と向き。位置は、ロジックの座標。書き換えられない。"""

    eye: tuple  # 目 (x, y, z)。ロジックの座標（m）
    target: tuple  # 注視点 (x, y, z)。ロジックの座標（m）
    fov_deg: float  # 画角（度。縦）
    near: float  # 手前の切り取り面（m）
    far: float  # 奥の切り取り面（m）

    @property
    def heading(self) -> float:
        """目から注視点への、平面での向き（rad。+x が 0、+z が +π/2。−π〜π）。真下か真上を見ているときは 0。"""
        return atan2(self.target[2] - self.eye[2], self.target[0] - self.eye[0])

    @property
    def pitch(self) -> float:
        """仰角（rad。上が正。見下ろしていれば負）。"""
        flat = hypot(self.target[0] - self.eye[0], self.target[2] - self.eye[2])
        return atan2(self.target[1] - self.eye[1], flat)


def chase_pose(spec: CameraSpec, x: float, z: float, heading: float) -> CameraPose:
    """後方追従。車の位置 (x, z) と向き heading（rad。ロジックの座標）から、カメラの位置と向きを作る。

    目は、車の後方 back m、高さ height m。注視点は、車の前方 look_ahead m、高さ look_height m。路面の高さは、いつも0（平地だけ）。
    """
    fx, fz = cos(heading), sin(heading)
    return CameraPose(
        eye=(x - fx * spec.back, spec.height, z - fz * spec.back),
        target=(x + fx * spec.look_ahead, spec.look_height, z + fz * spec.look_ahead),
        fov_deg=spec.fov_deg,
        near=spec.near,
        far=spec.far,
    )


def chunk_visible(pose: CameraPose, center_x: float, center_z: float, radius: float) -> bool:
    """塊（中心 (center_x, center_z)、半径 radius。ロジックの座標の平面）が、見えるか。

    中心までの距離が、奥＋半径より近く、前方への射影が、−半径より大きければ、見える（試作の決め）。
    真下か真上を見ているとき（前方が、平面で決まらない）は、距離だけで決める。
    """
    dx, dz = center_x - pose.eye[0], center_z - pose.eye[2]
    reach = pose.far + radius
    if dx * dx + dz * dz >= reach * reach:
        return False
    fx, fz = pose.target[0] - pose.eye[0], pose.target[2] - pose.eye[2]
    flat = hypot(fx, fz)
    if flat <= 0.0:
        return True
    return (dx * fx + dz * fz) / flat > -radius


# --- 背景（空と山並みの横長の絵）を写すための量 ---
def focal_px(fov_deg: float, screen_h: int) -> float:
    """焦点距離（画素）。画角は、縦の画角（度）。画面の中央では、向きが 1 rad 変わると、絵が、この画素だけ動く。"""
    return 0.5 * screen_h / tan(0.5 * radians(fov_deg))


def backdrop_period_px(fov_deg: float, screen_h: int) -> int:
    """背景の絵が、1周する幅（画素）。向きが1周（2π）で、絵が、ちょうど1周ぶん動く幅。絵は、この幅で、横に繰り返す。"""
    return max(1, int(round(TWO_PI * focal_px(fov_deg, screen_h))))


def backdrop_shift_px(heading: float, period_px: int) -> int:
    """背景の絵を、右へずらす量（画素。0以上、period_px 未満）。絵の列 u は、画面の x = (u + ずらす量) を period_px で折り返した所に写る。

    heading は、カメラの向き（rad。CameraPose.heading）。向きが増える（左へ回る）と、絵は、右へ流れる。1周で、元に戻る。
    """
    return int(floor(heading / TWO_PI * period_px)) % period_px


def horizon_row(pose: CameraPose, screen_h: int) -> int:
    """地平線が写る行（画面の y。上が0）。見下ろしているほど、上へ行く。画面の外の値も、そのまま返す。"""
    return int(round(0.5 * screen_h + focal_px(pose.fov_deg, screen_h) * tan(pose.pitch)))


# --- 判定用の柱（検証の口があるときにだけ使う） ---
def pillar_positions(x: float, z: float, heading: float) -> tuple:
    """判定用の柱の位置。返すのは ((左の柱の x, z), (右の柱の x, z))。ロジックの座標。

    車の位置 (x, z) と向き heading（rad）から、前へ PILLAR_AHEAD_M、左（と右）へ PILLAR_SIDE_M。
    左の向きの単位ベクトルは (−sin h, cos h)（向き0で、左は +z）。
    """
    fx, fz = cos(heading), sin(heading)
    ahead_x, ahead_z = x + fx * PILLAR_AHEAD_M, z + fz * PILLAR_AHEAD_M
    left_x, left_z = -fz * PILLAR_SIDE_M, fx * PILLAR_SIDE_M
    return (ahead_x + left_x, ahead_z + left_z), (ahead_x - left_x, ahead_z - left_z)


def pillar_parts(x: float, z: float, heading: float) -> tuple:
    """判定用の柱の形。返すのは (左の柱, 右の柱)。どちらも、片面の板（cp_core.mesh の MeshPart）。ロジックの座標。

    板は、地面から立ち、表が、車の後ろの側（カメラの側）を向く：(b−a)×(c−a) が (−cos h, 0, −sin h)。
    ロジックの座標の形なので、Pyxelの3Dへは、コースと同じ変換（z の反転と、頂点の順の入れ替え）を通す。
    """
    facing = (-cos(heading), -sin(heading))
    parts = []
    for name, (px, pz) in zip((PILLAR_LEFT, PILLAR_RIGHT), pillar_positions(x, z, heading)):
        vertices, triangles = mesh.board((px, 0.5 * PILLAR_HEIGHT_M, pz), facing, PILLAR_WIDTH_M, PILLAR_HEIGHT_M)
        parts.append(mesh.MeshPart(name, PILLAR_ROLES[name], vertices, triangles))
    return tuple(parts)
