#!/usr/bin/env python3
"""
Evalua el JSON normalizado de Patache y entrega una senal lista para el MMO.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def minutes_old(timestamp: str | None, collected_at: str | None) -> float | None:
    observed = parse_dt(timestamp)
    collected = parse_dt(collected_at)
    if not observed or not collected:
        return None
    return round((collected - observed).total_seconds() / 60, 1)


def raw_timestamps(data: dict[str, Any]) -> tuple[str | None, str | None]:
    raw = data.get("raw") or {}
    msg = raw.get("msg") or {}
    hs = raw.get("hs") or {}
    return msg.get("t"), hs.get("timestamp")


def is_zero_wind(data: dict[str, Any]) -> bool:
    return (
        data.get("wind_avg_kt") == 0
        and data.get("wind_dir_deg") == 0
        and data.get("temperature_c") == 0
    )


def evaluate(data: dict[str, Any]) -> dict[str, Any]:
    msg_timestamp, hs_timestamp = raw_timestamps(data)
    collected_at = data.get("collected_at")
    msg_age_min = minutes_old(msg_timestamp or data.get("timestamp"), collected_at)
    hs_age_min = minutes_old(hs_timestamp or data.get("timestamp"), collected_at)
    ages = [age for age in (msg_age_min, hs_age_min) if age is not None]
    age_min = min(ages) if ages else None
    fresh = age_min is not None and age_min <= 15
    recent = age_min is not None and age_min <= 60

    hs_ok = data.get("hs_m") is not None and hs_age_min is not None and hs_age_min <= 60
    level_ok = data.get("sea_level_mm") is not None and msg_age_min is not None and msg_age_min <= 60
    wind_ok = (
        data.get("wind_avg_kt") is not None
        and data.get("wind_avg_kt") > 0
        and msg_age_min is not None
        and msg_age_min <= 60
    )

    return {
        "station": data.get("station", "Patache"),
        "source": data.get("source", "SMTR Patache"),
        "timestamp": data.get("timestamp"),
        "age_min": age_min,
        "age_min_by_field": {
            "hs": hs_age_min,
            "sea_level": msg_age_min,
            "wind": msg_age_min,
        },
        "freshness": "verde" if fresh else "amarillo" if recent else "rojo",
        "usable": bool(hs_ok or level_ok or wind_ok),
        "use_hs": hs_ok,
        "use_sea_level": level_ok,
        "use_wind": wind_ok,
        "discard_wind_reason": "sensor entrega 0/0/0" if is_zero_wind(data) else None,
        "mmo_values": {
            "hs_m": data.get("hs_m") if hs_ok else None,
            "sea_level_mm": data.get("sea_level_mm") if level_ok else None,
            "wind_avg_kt": data.get("wind_avg_kt") if wind_ok else None,
            "wind_dir_deg": data.get("wind_dir_deg") if wind_ok else None,
            "temperature_c": data.get("temperature_c") if wind_ok else None,
        },
        "instruction": build_instruction(data, hs_ok, level_ok, wind_ok, age_min),
    }


def build_instruction(
    data: dict[str, Any],
    hs_ok: bool,
    level_ok: bool,
    wind_ok: bool,
    age_min: float | None,
) -> str:
    parts = []
    if hs_ok:
        parts.append(f"usar Hs Patache {data.get('hs_m')} m")
    if level_ok:
        parts.append(f"usar nivel Patache {data.get('sea_level_mm')} mm")
    if wind_ok:
        parts.append(f"usar viento Patache {data.get('wind_avg_kt')} kt / {data.get('wind_dir_deg')} deg")
    else:
        parts.append("no usar viento Patache; mantener EMA Iquique/Armada/modelo")
    age = f"{age_min} min" if age_min is not None else "edad desconocida"
    return f"Dato Patache {age}: " + "; ".join(parts) + "."


def main() -> int:
    parser = argparse.ArgumentParser(description="Evalua fuente Patache para el MMO.")
    parser.add_argument("json_path", nargs="?", default="outputs/patache_latest.json")
    args = parser.parse_args()

    data = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    print(json.dumps(evaluate(data), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
