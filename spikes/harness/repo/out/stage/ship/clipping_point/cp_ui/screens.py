"""The 2D screens. Each is a function (canvas, view_model). View models are plain dicts built from
cp_core state (see cp_ui.fixtures for the shapes). No game logic here."""
from .canvas import FONT_H, FONT_W, SCREEN_H, SCREEN_W, Canvas, text_size

COL_BG, COL_FRAME, COL_TEXT, COL_DIM, COL_HI = 1, 5, 7, 13, 10


def _center_text(c: Canvas, cx: int, y: int, s: str, col: int) -> None:
    c.text(cx - (text_size(s)[0] + 1) // 2, y, s, col)


def _panel(c: Canvas, name: str, x: int, y: int, w: int, h: int):
    c.rect(x, y, w, h, COL_BG)
    c.rectb(x, y, w, h, COL_FRAME)
    return c.box(name, x + 2, y + 2, w - 4, h - 4)


def draw_menu(c: Canvas, vm: dict) -> None:
    _center_text(c, SCREEN_W // 2, 40, "CLIPPING POINT", COL_HI)
    with _panel(c, "menu", 100, 84, 120, 14 + 12 * len(vm["items"])):
        for i, label in enumerate(vm["items"]):
            col = COL_HI if i == vm["cursor"] else COL_TEXT
            c.text(112, 92 + 12 * i, ("> " if i == vm["cursor"] else "  ") + label, col)
    with c.box("footer", 0, SCREEN_H - 10, SCREEN_W, 10):
        c.text(4, SCREEN_H - 8, vm["hint"], COL_DIM)
        v = "VER " + vm["version"]
        c.text(SCREEN_W - 4 - text_size(v)[0], SCREEN_H - 8, v, COL_DIM)


def draw_hud(c: Canvas, vm: dict) -> None:
    with c.box("hud_top_left", 2, 2, 100, 24):
        c.text(4, 4, f"LAP {vm['lap']}/{vm['laps']}", COL_TEXT)
        c.text(4, 12, f"POS {vm['pos']}/{vm['cars']}", COL_TEXT)
    with c.box("hud_top_right", SCREEN_W - 86, 2, 84, 24):
        c.text(SCREEN_W - 84, 4, f"TIME {vm['time']}", COL_TEXT)
        c.text(SCREEN_W - 84, 12, f"BEST {vm['best']}", COL_DIM)
    with c.box("hud_bottom_right", SCREEN_W - 70, SCREEN_H - 30, 68, 28):
        s = f"{vm['speed']:3d}"
        c.text(SCREEN_W - 20 - text_size(s)[0], SCREEN_H - 26, s, COL_HI)
        c.text(SCREEN_W - 16, SCREEN_H - 26, vm["unit"], COL_DIM)
        c.text(SCREEN_W - 66, SCREEN_H - 26, f"GEAR {vm['gear']}", COL_TEXT)
        c.rectb(SCREEN_W - 66, SCREEN_H - 14, 62, 8, COL_FRAME)
        c.rect(SCREEN_W - 65, SCREEN_H - 13, max(1, int(60 * vm["rpm"])), 6, COL_HI)
    with c.box("hud_bottom_left", 2, SCREEN_H - 12, 120, 10):
        c.text(4, SCREEN_H - 10, vm["car_name"], COL_DIM)


SETUP_ROWS = (
    ("GEAR RATIO", "gear", 5, "ACCEL", "SPEED"),
    ("WING", "wing", 5, "LOW", "HIGH"),
    ("SUSPENSION", "suspension", 5, "SOFT", "HARD"),
    ("BRAKE BALANCE", "brake_balance", 5, "FRONT", "REAR"),
    ("TRACTION", "traction", 5, "TURN", "EXIT"),
    ("STEERING", "steering", 3, "MILD", "QUICK"),
)


def draw_settings(c: Canvas, vm: dict) -> None:
    _center_text(c, SCREEN_W // 2, 8, "SETTING", COL_HI)
    with _panel(c, "car", 20, 20, 280, 18):
        c.text(26, 26, vm["car_name"], COL_TEXT)
        info = f"{vm['layout']} {vm['power_ps']}PS {vm['mass_kg']}KG CLASS {vm['car_class']}"
        c.text(294 - text_size(info)[0], 26, info, COL_DIM)
    with _panel(c, "setup", 20, 44, 280, 16 * len(SETUP_ROWS) + 8):
        for i, (label, key, steps, lo, hi) in enumerate(SETUP_ROWS):
            y = 52 + 16 * i
            with c.box(f"row_{key}", 24, y - 2, 272, 14):
                c.text(28, y + 2, label, COL_HI if i == vm["cursor"] else COL_TEXT)
                c.text(124 - text_size(lo)[0], y + 2, lo, COL_DIM)
                for s in range(steps):
                    x = 130 + s * 22 + (5 - steps) * 11
                    (c.rect if s + 1 == vm["setup"][key] else c.rectb)(x, y, 18, 9, COL_HI if s + 1 == vm["setup"][key] else COL_FRAME)
                c.text(242, y + 2, hi, COL_DIM)
    with _panel(c, "options", 20, 156, 280, 30):
        c.text(28, 162, f"TRANSMISSION  {vm['transmission']}", COL_TEXT)
        c.text(28, 172, f"ASSIST        {'ON' if vm['assist'] else 'OFF'}", COL_TEXT)
    with c.box("footer", 0, SCREEN_H - 10, SCREEN_W, 10):
        c.text(4, SCREEN_H - 8, vm["hint"], COL_DIM)


THEATER_VISIBLE_ROWS = 12


def draw_theater(c: Canvas, vm: dict) -> None:
    _center_text(c, SCREEN_W // 2, 8, "THEATER", COL_HI)
    with _panel(c, "list", 8, 20, 304, 14 * THEATER_VISIBLE_ROWS + 18):
        c.text(14, 25, "NO TITLE            TRACK          CAR            TIME    KB", COL_DIM)
        rows = vm["rows"][vm["top"] : vm["top"] + THEATER_VISIBLE_ROWS]  # only visible rows are drawn
        for i, row in enumerate(rows):
            y = 36 + 14 * i
            with c.box(f"row_{row['slot']}", 12, y - 2, 296, 12):
                col = COL_HI if vm["top"] + i == vm["cursor"] else COL_TEXT
                c.text(14, y, f"{row['slot']:02d}", col)
                c.text(26, y, row["title"], col)
                c.text(94, y, row["track"], COL_TEXT)
                c.text(154, y, row["car"], COL_TEXT)
                c.text(214, y, row["time"], COL_TEXT)
                kb = f"{row['kb']:4d}"
                c.text(304 - text_size(kb)[0], y, kb, COL_DIM)
    with c.box("usage", 8, 208, 304, 12):
        c.text(12, 211, f"USED {vm['used_kb']:4d}/{vm['max_kb']} KB  {len(vm['rows']):2d}/{vm['slots']} SLOTS", COL_DIM)
    with c.box("footer", 0, SCREEN_H - 10, SCREEN_W, 10):
        c.text(4, SCREEN_H - 8, vm["hint"], COL_DIM)


SCREENS = {"menu": draw_menu, "hud": draw_hud, "settings": draw_settings, "theater": draw_theater}
