#!/usr/bin/env python3
"""
Recolector minimo para SMTR Patache.

No guarda credenciales. Lee configuracion desde variables de entorno y escribe
un JSON normalizado para que el MMO lo consuma como fuente local prioritaria.
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import os
import re
import getpass
import sys
import zlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener


DEFAULT_BASE_URL = "http://164.77.164.44"


@dataclass
class PatacheReading:
    station: str
    collected_at: str
    timestamp: str | None
    wind_avg_kt: float | None
    wind_dir_deg: float | None
    temperature_c: float | None
    sea_level_mm: float | None
    hs_m: float | None
    raw: dict[str, Any]
    source: str = "SMTR Patache"


class PatacheClient:
    def __init__(self, base_url: str, cookie_header: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))
        self.cookie_header = cookie_header

    def get_json(self, path: str) -> dict[str, Any]:
        text = self.get_text(path)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            preview = text[:180].replace("\n", " ")
            raise RuntimeError(f"Respuesta no JSON desde {path}: {preview}") from exc

    def login(self, username: str, password: str) -> None:
        login_html = self.get_text("/")
        csrf = extract_csrf(login_html)
        payload = urlencode({"name": username, "password": password, "csrf_token": csrf}).encode()
        url = urljoin(self.base_url + "/", "login")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "mmo-patache-collector/0.1",
        }
        req = Request(url, data=payload, headers=headers, method="POST")
        try:
            with self.opener.open(req, timeout=20) as res:
                body = res.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code} durante login") from exc
        except URLError as exc:
            raise RuntimeError(f"No se pudo conectar durante login: {exc.reason}") from exc
        if "form-signin" in body or "Ingreso Sistema" in body:
            raise RuntimeError("Login rechazado por SMTR. Revisar usuario/contrasena o bloqueo de sesion.")

    def get_text(self, path: str) -> str:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        headers = {
            "Accept": "application/json,text/plain,*/*",
            "Accept-Encoding": "gzip,deflate",
            "User-Agent": "mmo-patache-collector/0.1",
        }
        if self.cookie_header:
            headers["Cookie"] = self.cookie_header
        req = Request(url, headers=headers)
        try:
            with self.opener.open(req, timeout=20) as res:
                body = res.read()
                encoding = (res.headers.get("Content-Encoding") or "").lower()
                if encoding == "gzip":
                    body = gzip.decompress(body)
                elif encoding == "deflate":
                    body = zlib.decompress(body)
                else:
                    body = maybe_decompress(body)
                return body.decode("utf-8", errors="replace")
        except HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code} consultando {url}") from exc
        except URLError as exc:
            raise RuntimeError(f"No se pudo conectar a {url}: {exc.reason}") from exc


def maybe_decompress(body: bytes) -> bytes:
    if body.startswith(b"\x1f\x8b"):
        return gzip.decompress(body)
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            return zlib.decompress(body, wbits)
        except zlib.error:
            pass
    return body


def extract_csrf(page_html: str) -> str:
    match = re.search(r'name=["\']csrf_token["\'][^>]*value=["\']([^"\']+)["\']', page_html)
    if not match:
        raise RuntimeError("No se encontro csrf_token en pantalla de login.")
    return html.unescape(match.group(1))


def latest(items: list[dict[str, Any]], time_key: str) -> dict[str, Any] | None:
    valid = [item for item in items if item.get(time_key)]
    if not valid:
        return items[-1] if items else None
    return sorted(valid, key=lambda item: str(item.get(time_key)))[-1]


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def sea_level_value(value: Any) -> float | None:
    if isinstance(value, list):
        samples = [to_float(item) for item in value]
        samples = [item for item in samples if item is not None]
        if not samples:
            return None
        return round(sum(samples) / len(samples), 1)
    return to_float(value)


def normalize(msg_payload: dict[str, Any], hs_payload: dict[str, Any]) -> PatacheReading:
    msg = latest(msg_payload.get("d") or [], "t") or {}
    hs = latest(hs_payload.get("d") or [], "timestamp") or {}

    wind_ms = to_float(msg.get("ws"))
    hs_mm = to_float(hs.get("value"))

    msg_timestamp = msg.get("t")
    hs_timestamp = hs.get("timestamp")
    timestamp = max([t for t in [msg_timestamp, hs_timestamp] if t], default=None)

    return PatacheReading(
        station="Patache",
        collected_at=datetime.now(timezone.utc).isoformat(),
        timestamp=timestamp,
        wind_avg_kt=round(wind_ms * 1.944, 1) if wind_ms is not None else None,
        wind_dir_deg=to_float(msg.get("wd")),
        temperature_c=to_float(msg.get("wt")),
        sea_level_mm=sea_level_value(msg.get("l")),
        hs_m=round(hs_mm / 1000, 3) if hs_mm is not None else None,
        raw={"msg": msg, "hs": hs},
    )


def collect(base_url: str, cookie_header: str | None, username: str | None, password: str | None) -> PatacheReading:
    if cookie_header == "session_cookie_name=session_cookie_value":
        cookie_header = None
    client = PatacheClient(base_url, cookie_header)
    if not cookie_header and username and password:
        client.login(username, password)
    msg_payload = client.get_json("/zipmsg/10")
    hs_payload = client.get_json("/ziphs/10")
    if not isinstance(msg_payload.get("d"), list) or not isinstance(hs_payload.get("d"), list):
        raise RuntimeError("Sesion invalida o respuesta inesperada: falta arreglo 'd' en JSON SMTR.")
    return normalize(msg_payload, hs_payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Recolecta datos SMTR Patache para el MMO.")
    parser.add_argument("--base-url", default=os.getenv("PATACHE_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--out", default=os.getenv("PATACHE_OUT", "patache_latest.json"))
    parser.add_argument(
        "--cookie",
        default=os.getenv("PATACHE_COOKIE"),
        help="Cookie de sesion en formato HTTP Cookie header. Preferir variable de entorno.",
    )
    parser.add_argument("--user", default=os.getenv("PATACHE_USER"), help="Usuario SMTR. Preferir variable de entorno.")
    parser.add_argument(
        "--password",
        default=os.getenv("PATACHE_PASSWORD"),
        help="Contrasena SMTR. Preferir variable de entorno o secret manager.",
    )
    parser.add_argument(
        "--ask-password",
        action="store_true",
        help="Pedir contrasena en terminal sin mostrarla ni guardarla.",
    )
    args = parser.parse_args()
    if args.ask_password:
        args.password = getpass.getpass("Contrasena Patache: ")

    try:
        reading = collect(args.base_url, args.cookie, args.user, args.password)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(asdict(reading), f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(json.dumps(asdict(reading), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
