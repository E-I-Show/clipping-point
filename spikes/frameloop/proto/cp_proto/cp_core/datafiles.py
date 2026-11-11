"""Data loading with validation at load time (pure Python, no pyxel)."""

import json
import struct
import zlib
from pathlib import Path

CAR_REQUIRED = {"id": str, "name": str, "layout": str, "power_ps": int, "mass_kg": int, "car_class": str}
LAYOUTS = {"FF", "FR", "MR", "4WD"}
TRACK_MAGIC = b"CPTK"


class DataError(ValueError):
    pass


def load_cars(path: Path) -> list:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataError(f"{path}: {exc}") from exc
    cars = doc.get("cars") if isinstance(doc, dict) else None
    if not isinstance(cars, list) or not cars:
        raise DataError(f"{path}: 'cars' must be a non-empty list")
    seen = set()
    for i, car in enumerate(cars):
        for key, typ in CAR_REQUIRED.items():
            if not isinstance(car.get(key), typ) or isinstance(car.get(key), bool):
                raise DataError(f"{path}: cars[{i}].{key} missing or not {typ.__name__}")
        if car["layout"] not in LAYOUTS:
            raise DataError(f"{path}: cars[{i}].layout {car['layout']!r} not in {sorted(LAYOUTS)}")
        if not car["name"].isascii():
            raise DataError(f"{path}: cars[{i}].name must be ASCII (HUD is alphanumeric only)")
        if car["id"] in seen:
            raise DataError(f"{path}: duplicate car id {car['id']!r}")
        seen.add(car["id"])
    return cars


def pack_track(points) -> bytes:
    body = TRACK_MAGIC + struct.pack("<HH", 1, len(points))
    for x, y in points:
        body += struct.pack("<ff", x, y)
    return body + struct.pack("<I", zlib.crc32(body))


def load_track(path: Path) -> list:
    try:
        blob = Path(path).read_bytes()
    except OSError as exc:
        raise DataError(f"{path}: {exc}") from exc
    if len(blob) < 12 or blob[:4] != TRACK_MAGIC:
        raise DataError(f"{path}: bad magic")
    body, (crc,) = blob[:-4], struct.unpack("<I", blob[-4:])
    if zlib.crc32(body) != crc:
        raise DataError(f"{path}: checksum mismatch")
    version, count = struct.unpack_from("<HH", body, 4)
    if version != 1 or count < 3 or len(body) != 8 + 8 * count:
        raise DataError(f"{path}: bad header (version={version}, count={count})")
    return [struct.unpack_from("<ff", body, 8 + 8 * i) for i in range(count)]
