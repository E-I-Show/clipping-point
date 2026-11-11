"""Development bridge for the screens: named view models for the overflow check and the tour.

Every screen has a 'typical' and an 'extreme' variant. Extreme values are derived from the loaded
data (longest names, largest numbers the formats can produce), so a new car or a test data pack
with a longer name is picked up without editing this file.
"""
from cp_core.datadefs import GameData
from cp_core.profile import SHELF_MAX_BYTES, SHELF_SLOTS

VARIANTS = ("typical", "extreme")


def _widest(data: GameData, table: str) -> dict:
    return max(data.table(table).values(), key=lambda e: (len(e["name"]), e["id"]))


def format_time(ticks: int) -> str:
    ms = ticks * 1000 // 60
    return f"{ms // 60000}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def build(screen: str, variant: str, data: GameData) -> dict:
    x = variant == "extreme"
    car = _widest(data, "cars") if x else data.table("cars")["kazane_rs"]
    track = _widest(data, "tracks") if x else data.table("tracks")["akane_short"]
    if screen == "menu":
        return {"items": ["TIME ATTACK", "SINGLE RACE", "THEATER", "OPTIONS"], "cursor": 3 if x else 0,
                "hint": "UP/DOWN:SELECT  A/ENTER:OK" + ("  B/ESC:BACK  START:PAUSE" if x else ""), "version": "0.0.1"}
    if screen == "hud":
        return {"lap": 99 if x else 2, "laps": 99 if x else 3, "pos": 6 if x else 3, "cars": 6,
                "time": format_time(60 * 60 * 59 + 3599 if x else 4321), "best": format_time(60 * 60 * 59 + 3599 if x else 3900),
                "speed": 399 if x else 142, "unit": "KMH", "gear": 6 if x else 3, "rpm": 1.0 if x else 0.62, "car_name": car["name"]}
    if screen == "settings":
        return {"car_name": car["name"], "layout": "4WD" if x else car["layout"], "power_ps": 600 if x else car["power_ps"],
                "mass_kg": 2500 if x else car["mass_kg"], "car_class": car["car_class"], "cursor": 5 if x else 0,
                "setup": {"gear": 5, "wing": 5, "suspension": 5, "brake_balance": 5, "traction": 5, "steering": 3} if x
                else {"gear": 3, "wing": 3, "suspension": 3, "brake_balance": 3, "traction": 3, "steering": 2},
                "transmission": "AT", "assist": not x, "hint": "LEFT/RIGHT:CHANGE  B/ESC:BACK"}
    if screen == "theater":
        n = SHELF_SLOTS if x else 3
        rows = [{"slot": i + 1, "title": ("W" * 16) if x else f"REPLAY {i + 1}", "track": track["name"], "car": car["name"],
                 "time": format_time(60 * 60 * 59 + 3599 if x else 3700 + i), "kb": 9999 if x else 180 + i} for i in range(n)]
        return {"rows": rows, "top": 0, "cursor": n - 1 if x else 0, "used_kb": 9999 if x else 543,
                "max_kb": SHELF_MAX_BYTES // 1024, "slots": SHELF_SLOTS, "hint": "A:PLAY  X:EXPORT  Y:DELETE  B:BACK"}
    raise KeyError(screen)
