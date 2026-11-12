"""コース（純Python）。コースの表、照会、位置を引く口、壁の押し戻し、形の検査。決まりは docs/design/overview.md の「コース」。
元は、設計時の試作（spikes/track/track.py）。

コースの表（Track）は、定義データのコースの項目（tracks/<id>.json）から作る（build_track）。作った後は、書き換えない。
  制御点（x、z）→ 周期的な3次スプライン（弦の長さで媒介。曲率が連続）→ 細かい点列 → 約 sample_step_m 刻みの、等間隔の表
  表の点ごとの値：位置、接線、向き（巻き戻さない）、曲率、幅の半分（＝舗装の端）、左右の壁の位置
  座標は、平面 (x, z)。向きは +x が 0、+z が +π/2。左の法線は (−sin h, cos h)。横のずれは、左が正。曲率は、左へ曲がるとき正
照会（Track.query）は、位置から、コースに沿った距離、横のずれ、向き、曲率、路面の種類、舗装の端と壁の位置、壁までの距離を返す。
  前回の区間の番号（hint）があれば、その近くだけを探す（QUERY_MAX_WALK 点まで）。届かなければ、全部を探して取り直し、
  返す値の requeried を True にする（答えは同じで、遅い。毎tick取り直す退行を、数で見えるようにする）。
  hint が無い呼び出し（スタートと、置き直した後）は、全部を探す。取り直しには数えない。前回の区間の番号は、呼ぶ側（世界）が持つ。
  hint の近くに、位置を挟む区間があれば、それを答えにする（隣の道へ飛ばないため）。向かい側の直線のような、別の道の区間を
  hint に渡すと、その道の上の答えが返る（取り直さない）。車を、離れた所へ置き直した後は、hint を渡さない（None にする）。
位置を引く口（Track.pose_at）は、照会の逆（コースに沿った距離と横のずれ → 位置と向き）。
壁の押し戻し（Track.push_out）は、車を向きつきの長方形として、壁へのめり込みを求め、押し戻して、減速させる。
形の検査（shape_problems）は、読み込み検査（cp_core/datadefs.py）が呼ぶ。ここからは datadefs を読み込まない。
同じ中身の項目から作った表は、覚えておいて、同じものを渡す（build_track。直近の BUILT_MAX 個まで）。表は、読み込み検査の中の
形の検査と、世界を作るときに要る。2度作らない（1度に、デスクトップ版で約4ミリ秒、ブラウザ版で約15〜25ミリ秒。段0 区切り9の実測）。
表は書き換えられないので、同じものを、いくつの世界が持ってもよい。
入れていないもの（段1の「コースデータと照会」の区切り）：高さ、勾配、バンク（平地だけ。高さは、いつも0）、縁石、グラベル、
区間ごとの路肩と幅、グリッド、通過点と周回判定、理想ライン、カメラ、景観物、自己交差の検査、車同士の当たり、描画用のメッシュ。
"""
import json
from math import atan2, ceil, cos, hypot, pi, sin, sqrt

SURFACE_ASPHALT, SURFACE_GRASS = "asphalt", "grass"
SURFACES = (SURFACE_ASPHALT, SURFACE_GRASS)  # 路面の種類。いまは、舗装と芝だけ（縁石とグラベルは、段1）
TWO_PI = 2.0 * pi
# 照会が、前回の区間から歩く点の数の上限。1 tickに車が動くのは、2 m刻みの表で1〜2点。試作で、ヘアピンでも隣の道へ飛ばないことを
# 確かめた値（届かなければ、全部を探して取り直すので、答えは変わらない。変わるのは、取り直しの回数だけ）。
QUERY_MAX_WALK = 16
MIN_SAMPLES = 8  # 表の点の数の下限
BUILT_MAX = 4  # 覚えておく表の数（直近に使ったものから）。同じコースを、検査と世界で2度作らないための数で、多くは要らない
# --- 形の検査の決まり（読み込み検査の、範囲の規則と同じ役目。データの外に置く） ---
MIN_POINTS = 4  # 制御点の数の下限
MIN_GAP_M = 0.5  # 隣り合う制御点の間隔の下限（m）。頭の点を、末尾に繰り返さない
CLOSE_GAP_FACTOR = 4.0  # 末尾から頭へ戻る間隔が、ほかの間隔のいちばん長いものの、この倍を超えたら「閉じていない」
MAX_LENGTH_M = 20000.0  # 制御点を結んだ長さの上限（m）。これを超える表は作らない（読み込みで固まらないため）
TURNING_TOLERANCE_RAD = 0.01  # 1周の向きの変化が、±2π からこれを超えて外れたら「1周で閉じていない」（8の字、2重の輪）
MIN_RADIUS_M = 8.0  # 最小半径（m）
FOLD_MARGIN = 0.15  # 内側の折り返し。1 − |曲率| × 内側の壁の位置 が、これ未満なら、壁の内で照会が1つに決まらない
START_EDGE_MARGIN_M = 1.0  # スタート位置が、舗装の端から、これより内にあること（m）


class TrackQuery:
    """照会の結果。"""

    __slots__ = (
        "index", "s", "lateral", "heading", "curvature", "surface", "half_left", "half_right",
        "wall_left", "wall_right", "to_wall_left", "to_wall_right", "height", "requeried",
    )

    def __init__(self) -> None:
        self.index = 0  # 区間の番号（表の点 index から index+1 まで）。次の照会の hint に渡す
        self.s = 0.0  # コースに沿った距離（m）。0以上、全長未満
        self.lateral = 0.0  # 横のずれ（m）。左が正
        self.heading = 0.0  # コースの向き（rad。−π〜π）
        self.curvature = 0.0  # 曲率（1/m）。左へ曲がるとき正
        self.surface = SURFACE_ASPHALT  # 路面の種類（SURFACES のどれか）
        self.half_left = 0.0  # 中心線から、左の舗装の端まで（m）
        self.half_right = 0.0  # 中心線から、右の舗装の端まで（m）
        self.wall_left = 0.0  # 中心線から、左の壁まで（m）
        self.wall_right = 0.0  # 中心線から、右の壁まで（m）
        self.to_wall_left = 0.0  # この点から、左の壁まで（m）。負は、壁の外
        self.to_wall_right = 0.0  # この点から、右の壁まで（m）
        self.height = 0.0  # 路面の高さ（m）。いまは、いつも0（平地だけ）
        self.requeried = False  # 前回の区間の近くで探し当てられず、全部を探して取り直したか


def _wrap_pi(angle: float) -> float:
    """角度を、−π より大きく π 以下に折り返す。"""
    while angle > pi:
        angle -= TWO_PI
    while angle <= -pi:
        angle += TWO_PI
    return angle


def _solve_cyclic(lower: list, diag: list, upper: list, rhs: list) -> list:
    """巡回する三重対角の連立方程式を解く（三重対角の解法に、Sherman-Morrison の補正を足す）。"""
    n = len(diag)
    gamma = -diag[0]
    dd = list(diag)
    dd[0] = diag[0] - gamma
    dd[n - 1] = diag[n - 1] - lower[0] * upper[n - 1] / gamma
    u = [0.0] * n
    u[0] = gamma
    u[n - 1] = upper[n - 1]

    def thomas(d: list) -> list:
        c2 = [0.0] * n
        d2 = [0.0] * n
        c2[0] = upper[0] / dd[0]
        d2[0] = d[0] / dd[0]
        for i in range(1, n):
            m = dd[i] - lower[i] * c2[i - 1]
            c2[i] = upper[i] / m
            d2[i] = (d[i] - lower[i] * d2[i - 1]) / m
        x = [0.0] * n
        x[n - 1] = d2[n - 1]
        for i in range(n - 2, -1, -1):
            x[i] = d2[i] - c2[i] * x[i + 1]
        return x

    y = thomas(rhs)
    q = thomas(u)
    f = (y[0] + lower[0] * y[n - 1] / gamma) / (1.0 + q[0] + lower[0] * q[n - 1] / gamma)
    return [y[i] - f * q[i] for i in range(n)]


def _dense_points(px: list, pz: list, gaps: list, dense_step: float) -> list:
    """制御点を通る、周期的な3次スプライン（曲率が連続）を、約 dense_step 刻みの点列 [(x, z)] にする。gaps は、隣の制御点までの間隔。"""
    n = len(px)
    lower = [gaps[i - 1] for i in range(n)]
    diag = [2.0 * (gaps[i - 1] + gaps[i]) for i in range(n)]
    second = []
    for p in (px, pz):
        rhs = [6.0 * ((p[(i + 1) % n] - p[i]) / gaps[i] - (p[i] - p[i - 1]) / gaps[i - 1]) for i in range(n)]
        second.append(_solve_cyclic(lower, diag, gaps, rhs))
    dense = []
    for k in range(n):
        j = (k + 1) % n
        hk = gaps[k]
        count = max(2, int(ceil(hk / dense_step)))
        for q in range(count):
            u = q / float(count)
            a = (1.0 - u) * hk
            b = u * hk
            point = []
            for p, mm in zip((px, pz), second):
                point.append(
                    mm[k] * a * a * a / (6.0 * hk) + mm[j] * b * b * b / (6.0 * hk)
                    + (p[k] / hk - mm[k] * hk / 6.0) * a + (p[j] / hk - mm[j] * hk / 6.0) * b
                )
            dense.append((point[0], point[1]))
    return dense


class Track:
    """コースの表。作った後は、書き換えない（値は、タプルで持つ）。作るのは build_track()。"""

    __slots__ = (
        "track_id", "length", "n", "ds", "turning", "wall_restitution", "wall_friction", "start_s", "start_lateral",
        "_mu", "_x", "_z", "_tx", "_tz", "_h", "_k", "_half", "_wall_l", "_wall_r", "_dh", "_dk", "_dxs", "_dzs", "_qa", "_built",
    )

    def __setattr__(self, name: str, value) -> None:
        if getattr(self, "_built", False):
            raise AttributeError(f"Track is read-only (cannot set {name})")
        object.__setattr__(self, name, value)

    def __init__(self, entry: dict) -> None:
        points = entry["control_points"]
        px = [float(point["x_m"]) for point in points]
        pz = [float(point["z_m"]) for point in points]
        count = len(px)
        gaps = [hypot(px[(i + 1) % count] - px[i], pz[(i + 1) % count] - pz[i]) for i in range(count)]
        dense = _dense_points(px, pz, gaps, entry["table"]["dense_step_m"])
        # 細かい点列の、頭からの長さ。これを、等間隔に取り直す。
        m = len(dense)
        cum = [0.0] * (m + 1)
        for i in range(m):
            a = dense[i]
            b = dense[(i + 1) % m]
            cum[i + 1] = cum[i] + hypot(b[0] - a[0], b[1] - a[1])
        total = cum[m]
        n = max(MIN_SAMPLES, int(round(total / entry["table"]["sample_step_m"])))
        ds = total / n
        xs = [0.0] * n
        zs = [0.0] * n
        j = 0
        for i in range(n):
            s = i * ds
            while cum[j + 1] < s:
                j += 1
            seg = cum[j + 1] - cum[j]
            u = (s - cum[j]) / seg if seg > 0.0 else 0.0
            a = dense[j]
            b = dense[(j + 1) % m]
            xs[i] = a[0] + u * (b[0] - a[0])
            zs[i] = a[1] + u * (b[1] - a[1])
        # 点ごとの値：接線、向き（巻き戻さない）、曲率。
        tx = [0.0] * n
        tz = [0.0] * n
        hd = [0.0] * n
        kap = [0.0] * n
        for i in range(n):
            a = (i - 1) % n
            b = (i + 1) % n
            dx = xs[b] - xs[a]
            dz = zs[b] - zs[a]
            ln = hypot(dx, dz)
            tx[i] = dx / ln
            tz[i] = dz / ln
            h_in = atan2(zs[i] - zs[a], xs[i] - xs[a])
            h_out = atan2(zs[b] - zs[i], xs[b] - xs[i])
            kap[i] = _wrap_pi(h_out - h_in) / ds
        hd[0] = atan2(tz[0], tx[0])
        for i in range(1, n):
            hd[i] = hd[i - 1] + _wrap_pi(atan2(tz[i], tx[i]) - hd[i - 1])
        nxt = [(i + 1) % n for i in range(n)]
        half = entry["width_m"] * 0.5
        wall = half + entry["grass_m"]
        self.track_id = entry["id"]  # コースの id
        self.length = total  # 全長（m）
        self.n = n  # 表の点の数（＝区間の数）
        self.ds = ds  # 表の刻み（m）
        self.turning = hd[n - 1] + _wrap_pi(hd[0] - hd[n - 1]) - hd[0]  # 1周の向きの変化（rad）。ふつうの輪なら ±2π
        self._mu = {name: float(entry["surface_mu"][name]) for name in SURFACES}  # 路面の種類 → 摩擦係数。引くのは surface_mu()
        self.wall_restitution = float(entry["wall"]["restitution"])  # 壁の反発（0〜1）
        self.wall_friction = float(entry["wall"]["friction"])  # 壁の摩擦
        self.start_s = float(entry["start"]["s_m"])  # スタート位置の、コースに沿った距離（m）
        self.start_lateral = float(entry["start"]["lateral_m"])  # スタート位置の、横のずれ（m）
        self._x = tuple(xs)
        self._z = tuple(zs)
        self._tx = tuple(tx)
        self._tz = tuple(tz)
        self._h = tuple(hd)
        self._k = tuple(kap)
        # 幅は、いまは一定（区間ごとの幅と路肩は、段1）。点ごとに持つ形だけ、先に作る。
        self._half = (half,) * n  # 幅の半分＝中心線から舗装の端まで（左右同じ）
        self._wall_l = (wall,) * n  # 中心線から、左の壁まで
        self._wall_r = (wall,) * n  # 中心線から、右の壁まで
        # 区間ごとの差（区間 i は、点 i から点 i+1 まで）。
        self._dh = tuple(_wrap_pi(hd[nxt[i]] - hd[i]) for i in range(n))
        self._dk = tuple(kap[nxt[i]] - kap[i] for i in range(n))
        self._dxs = tuple(xs[nxt[i]] - xs[i] for i in range(n))
        self._dzs = tuple(zs[nxt[i]] - zs[i] for i in range(n))
        # 照会の、区間の中の位置を求める式の、2次の項。
        self._qa = tuple(-(self._dxs[i] * (tx[nxt[i]] - tx[i]) + self._dzs[i] * (tz[nxt[i]] - tz[i])) for i in range(n))
        self._built = True  # ここから後は、書き換えられない

    def surface_mu(self, surface: str) -> float:
        """路面の種類（SURFACES のどれか）の、摩擦係数。知らない名は KeyError。"""
        return self._mu[surface]

    def sample(self, index: int) -> tuple:
        """表の点1つ。返すのは (x, z, 向き, 曲率, 幅の半分, 左の壁, 右の壁)。向きは、巻き戻さない値。"""
        return (
            self._x[index], self._z[index], self._h[index], self._k[index],
            self._half[index], self._wall_l[index], self._wall_r[index],
        )

    def nearest_index(self, x: float, z: float) -> int:
        """全部の点を見て、いちばん近い点の番号を返す。"""
        xs = self._x
        zs = self._z
        best = 0
        best_d2 = -1.0
        for i in range(self.n):
            dx = xs[i] - x
            dz = zs[i] - z
            d2 = dx * dx + dz * dz
            if best_d2 < 0.0 or d2 < best_d2:
                best_d2 = d2
                best = i
        return best

    def _locate(self, x: float, z: float, i: int, steps: int) -> tuple:
        """区間 i から、前後へ steps 点まで歩いて、(x, z) が入る区間を探す。返すのは (探し当てたか, 区間, 区間の中の位置 0〜1)。"""
        n = self.n
        xs = self._x
        zs = self._z
        tx = self._tx
        tz = self._tz
        a0 = (x - xs[i]) * tx[i] + (z - zs[i]) * tz[i]
        a1 = 0.0
        found = False
        while steps > 0:
            if a0 < 0.0:
                i = i - 1 if i > 0 else n - 1
                a1 = a0
                a0 = (x - xs[i]) * tx[i] + (z - zs[i]) * tz[i]
                if a0 >= 0.0:
                    found = True
                    break
                steps -= 1
                continue
            j = i + 1 if i + 1 < n else 0
            a1 = (x - xs[j]) * tx[j] + (z - zs[j]) * tz[j]
            if a1 < 0.0:
                found = True
                break
            i = j
            a0 = a1
            steps -= 1
        if not found:
            # 探し当てられなかった（曲率の中心を越えた所など）。区間の端に寄せる。
            return False, i, 0.0 if a0 < 0.0 else 1.0
        den = a0 - a1
        t = a0 / den if den > 1e-12 else 0.0
        qa = self._qa[i]
        if qa > 1e-9 or qa < -1e-9:
            # f(t) = a0 + t × (a1 − a0 − qa) + qa × t² の根へ、ニュートン法を1回
            b = a1 - a0 - qa
            f = a0 + t * b + qa * t * t
            fp = b + 2.0 * qa * t
            if fp < -1e-12:
                t -= f / fp
                if t < 0.0:
                    t = 0.0
                elif t > 1.0:
                    t = 1.0
        return True, i, t

    def query(self, x: float, z: float, hint=None) -> TrackQuery:
        """照会。位置 (x, z) を、コースの表から引く。hint は、前回の区間の番号（TrackQuery.index）。無ければ None。"""
        n = self.n
        requeried = False
        found = False
        i = 0
        t = 0.0
        if hint is not None:
            found, i, t = self._locate(x, z, hint % n, QUERY_MAX_WALK)
            if not found:
                requeried = True  # 前回の区間の近くに無い。全部を探して、取り直す
        if not found:
            start = self.nearest_index(x, z)
            found, i, t = self._locate(x, z, start - 1 if start > 0 else n - 1, n)
        if t >= 1.0:
            # 区間の終わりちょうどは、次の区間の頭として返す（コースに沿った距離が、全長に届かない）。
            i = i + 1 if i + 1 < n else 0
            t = 0.0
        j = i + 1 if i + 1 < n else 0
        tx = self._tx
        tz = self._tz
        px = self._x[i] + t * self._dxs[i]
        pz = self._z[i] + t * self._dzs[i]
        nx = -(tz[i] + t * (tz[j] - tz[i]))
        nz = tx[i] + t * (tx[j] - tx[i])
        lateral = ((x - px) * nx + (z - pz) * nz) / sqrt(nx * nx + nz * nz)
        heading = self._h[i] + t * self._dh[i]
        if heading > pi:
            heading -= TWO_PI
        elif heading <= -pi:
            heading += TWO_PI
        half = self._half[i] + t * (self._half[j] - self._half[i])
        wall_left = self._wall_l[i] + t * (self._wall_l[j] - self._wall_l[i])
        wall_right = self._wall_r[i] + t * (self._wall_r[j] - self._wall_r[i])
        result = TrackQuery()
        result.index = i
        result.s = (i + t) * self.ds
        result.lateral = lateral
        result.heading = heading
        result.curvature = self._k[i] + t * self._dk[i]
        result.surface = SURFACE_ASPHALT if -half <= lateral <= half else SURFACE_GRASS
        result.half_left = half
        result.half_right = half
        result.wall_left = wall_left
        result.wall_right = wall_right
        result.to_wall_left = wall_left - lateral
        result.to_wall_right = wall_right + lateral
        result.requeried = requeried
        return result

    def pose_at(self, s: float, lateral: float = 0.0) -> tuple:
        """コースに沿った距離 s（m。1周で折り返す）と、横のずれ lateral（m。左が正）から、位置と向きを引く。返すのは (x, z, 向き)。"""
        n = self.n
        f = (s % self.length) / self.ds
        i = int(f)
        if i >= n:
            i = n - 1
        t = f - i
        j = i + 1 if i + 1 < n else 0
        nx = -(self._tz[i] + t * (self._tz[j] - self._tz[i]))
        nz = self._tx[i] + t * (self._tx[j] - self._tx[i])
        ln = sqrt(nx * nx + nz * nz)
        heading = self._h[i] + t * self._dh[i]
        if heading > pi:
            heading -= TWO_PI
        elif heading <= -pi:
            heading += TWO_PI
        return self._x[i] + t * self._dxs[i] + lateral * nx / ln, self._z[i] + t * self._dzs[i] + lateral * nz / ln, heading

    def start_pose(self) -> tuple:
        """スタート位置。返すのは (x, z, 向き)。"""
        return self.pose_at(self.start_s, self.start_lateral)

    def wall_contact(self, query: TrackQuery, heading: float, half_length: float, half_width: float) -> tuple:
        """車（向きつきの長方形。中心が照会の点）の、壁へのめり込み。返すのは (めり込み m, 側)。側は、+1＝左の壁、−1＝右の壁、0＝無し。

        heading は、車の向き（rad）。half_length、half_width は、車体の半長と半幅（m）。
        """
        # 割り切り：長方形を、車の中心の区間の法線へ投影する（壁の曲がりを見ない。半径15 mで、最大約0.15 mの差。試作の見積り）。
        # 見直すのは、ヘアピンのある本物のコースを作る段1の「コースデータと照会」の区切り。
        angle = heading - query.heading
        extent = abs(sin(angle)) * half_length + abs(cos(angle)) * half_width
        pen_left = query.lateral + extent - query.wall_left
        pen_right = extent - query.lateral - query.wall_right
        if pen_left > 0.0 and pen_left >= pen_right:
            return pen_left, 1
        if pen_right > 0.0:
            return pen_right, -1
        return 0.0, 0

    def push_out(self, query: TrackQuery, x: float, z: float, wvx: float, wvz: float, heading: float, half_length: float, half_width: float) -> tuple:
        """壁の押し戻し。返すのは (x, z, wvx, wvz, 当たっているか, 壁へ向かっていた速さ m/s)。

        query は、位置 (x, z) の照会の結果。wvx、wvz は、世界座標での速度（m/s）。heading は、車の向き（rad）。
        めり込んだ分を、壁の法線の向きに押し戻す。壁へ向かう速度は、反発の割合で跳ね返し、壁に沿う速度は、摩擦で減らす。
        向きとヨーレートは、変えない（壁に当たって回り込む動きは、段1で車両モデルの側に足す）。
        """
        pen, side = self.wall_contact(query, heading, half_length, half_width)
        if side == 0:
            return x, z, wvx, wvz, False, 0.0
        ch = cos(query.heading)
        sh = sin(query.heading)
        nx = -sh * side  # 壁へ向かう法線
        nz = ch * side
        x -= nx * pen
        z -= nz * pen
        vn = wvx * nx + wvz * nz
        impact = 0.0
        if vn > 0.0:
            impact = vn
            vt = wvx * ch + wvz * sh
            loss = self.wall_friction * (1.0 + self.wall_restitution) * vn
            if vt > loss:
                vt -= loss
            elif vt < -loss:
                vt += loss
            else:
                vt = 0.0
            vn_after = -self.wall_restitution * vn
            wvx = vt * ch + vn_after * nx
            wvz = vt * sh + vn_after * nz
        return x, z, wvx, wvz, True, impact


_built = {}  # 項目の中身（鍵を整列したJSONの文）→ コースの表。古い順に並ぶ。直近の BUILT_MAX 個まで


def build_track(entry: dict) -> Track:
    """定義データのコースの項目（読み込み検査を通ったもの。GameData.entry("tracks", id)）から、コースの表を作る。

    同じ中身の項目からは、前に作った表を、そのまま渡す（表は、書き換えられない）。作れなかった項目（計算の例外）は、覚えない。
    """
    key = json.dumps(entry, sort_keys=True)
    built = _built.pop(key, None)
    if built is None:
        built = Track(entry)
        while len(_built) >= BUILT_MAX:
            del _built[next(iter(_built))]  # いちばん古いものを忘れる
    _built[key] = built  # 使ったものを、いちばん新しい所へ
    return built


def shape_problems(entry: dict) -> list:
    """コースの形の検査。読み込み検査が、鍵ごとの規則を全部通った項目にだけ呼ぶ。返すのは [(鍵の道, 問題の文)]。

    先に、退化した形（点が足りない、制御点の間隔が短すぎる、閉じていない、全長が短すぎる・長すぎる）を見る。1つでもあれば、
    表を作る計算に進まない。次に、表を作って、1周で閉じること、最小半径、内側の折り返し、スタートが舗装の上にあることを見る。
    """
    points = entry["control_points"]
    count = len(points)
    where = ("control_points",)
    if count < MIN_POINTS:
        return [(where, f"{count} control points (at least {MIN_POINTS})")]
    gaps = [hypot(points[(i + 1) % count]["x_m"] - points[i]["x_m"], points[(i + 1) % count]["z_m"] - points[i]["z_m"]) for i in range(count)]
    problems = [
        ((*where, i), f"this point and the next are {gap:.3f} m apart (at least {MIN_GAP_M}; do not repeat the first point at the end)")
        for i, gap in enumerate(gaps) if gap < MIN_GAP_M
    ]
    if problems:
        return problems
    longest = max(gaps[:-1])
    if gaps[-1] > CLOSE_GAP_FACTOR * longest:
        return [(where, f"not closed: the gap from the last point back to the first is {gaps[-1]:.1f} m (the longest other gap is {longest:.1f} m)")]
    total = sum(gaps)
    shortest = MIN_SAMPLES * entry["table"]["sample_step_m"]
    if not shortest <= total <= MAX_LENGTH_M:
        return [(where, f"the loop is {total:.1f} m long (must be {shortest:.1f}..{MAX_LENGTH_M:.1f})")]
    track = build_track(entry)
    if abs(abs(track.turning) - TWO_PI) > TURNING_TOLERANCE_RAD:
        return [(where, f"not one closed loop: the heading turns {track.turning:.3f} rad over the lap (must be 2*pi either way)")]
    worst = max(range(track.n), key=lambda i: abs(track._k[i]))
    if abs(track._k[worst]) > 1.0 / MIN_RADIUS_M:
        problems.append((where, f"radius {1.0 / abs(track._k[worst]):.1f} m at s={worst * track.ds:.0f} m (at least {MIN_RADIUS_M})"))
    folds = []
    for i in range(track.n):
        curvature = track._k[i]
        inner = track._wall_l[i] if curvature > 0.0 else track._wall_r[i]
        if 1.0 - abs(curvature) * inner < FOLD_MARGIN:
            folds.append((abs(curvature) * inner, i, inner))
    if folds:
        _, i, inner = max(folds)
        problems.append((
            where,
            f"the inner wall ({inner:.1f} m from the centre line) folds over at s={i * track.ds:.0f} m (radius {1.0 / abs(track._k[i]):.1f} m)",
        ))
    start = entry["start"]
    if start["s_m"] >= track.length:
        problems.append((("start", "s_m"), f"{start['s_m']} is beyond the lap length {track.length:.1f} m"))
    else:
        half = track._half[int(start["s_m"] / track.ds) % track.n]
        if abs(start["lateral_m"]) + START_EDGE_MARGIN_M > half:
            problems.append((
                ("start", "lateral_m"),
                f"{start['lateral_m']} is not on the asphalt (half width {half:.1f} m, keep {START_EDGE_MARGIN_M} m from the edge)",
            ))
    return problems
