"""OpenSanctions maritime loader — Person A.

Downloads the small (~3.7 MB) OpenSanctions *maritime* CSV once, caches it under
backend/data/, and offers lookup by IMO or normalized name. Degrades to no-hit
(returns None) if the file can't be fetched, so the scorer never crashes.

CSV columns: type, caption(name), imo, risk, countries, flag, mmsi, id, datasets, aliases
`risk` carries tags like `mare.detained`, `reg.warn`, sanctions-program codes.
"""
import csv
import os
import re
from pathlib import Path

import requests

_INDEX_URL = "https://data.opensanctions.org/datasets/latest/maritime/index.json"
_CACHE = Path(__file__).resolve().parents[3] / "data" / "maritime.csv"  # backend/data/maritime.csv

_by_imo: dict[str, dict] = {}
_by_name: dict[str, dict] = {}
_loaded = False


def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _download() -> bool:
    """Resolve the current maritime.csv build URL from index.json and cache it."""
    try:
        idx = requests.get(_INDEX_URL, timeout=20).json()
        url = next((r.get("url") for r in idx.get("resources", [])
                    if r.get("name") == "maritime.csv"), None)
        if not url:
            print("[sanctions] maritime.csv not found in index.json")
            return False
        data = requests.get(url, timeout=60).content
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.write_bytes(data)
        return True
    except Exception as e:  # noqa: BLE001 — network failure must not crash the app
        print(f"[sanctions] download failed: {e}")
        return False


def load(force: bool = False) -> None:
    global _loaded
    if _loaded and not force:
        return
    if force or not _CACHE.exists():
        _download()
    if not _CACHE.exists():
        print("[sanctions] no cache available; lookups return None")
        _loaded = True
        return
    with open(_CACHE, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = _digits(row.get("imo"))
            if d:
                _by_imo[d] = row
            n = _norm(row.get("caption"))
            if n:
                _by_name[n] = row
    _loaded = True
    print(f"[sanctions] loaded {len(_by_imo)} by IMO / {len(_by_name)} by name")


def lookup(imo: str | None = None, name: str | None = None) -> dict | None:
    """Return the matching maritime row (dict) or None. Match by IMO first, then name."""
    if not _loaded:
        load()
    if imo:
        hit = _by_imo.get(_digits(imo))
        if hit:
            return hit
    if name:
        hit = _by_name.get(_norm(name))
        if hit:
            return hit
    return None
