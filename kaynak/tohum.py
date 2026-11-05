"""Başlangıç verisi: YARGUCU uygulamasında gömülü, daha önce resmî kaynaklarla doğrulanmış tablolar.

tohum.json, uygulamanın kaynak kodundan otomatik çıkarılır (seed_extract). Tohumlama yalnız
boş depoda çalışır ve her değeri 'tohum' kaynağıyla onaylı olarak yazar.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from .depo import Depo

TOHUM = Path(__file__).resolve().parent / "tohum.json"


def _inf(x: Any) -> Any:
    if x == "Infinity":
        return None  # üst sınırsız dilim
    if isinstance(x, list):
        return [_inf(v) for v in x]
    if isinstance(x, dict):
        return {k: _inf(v) for k, v in x.items()}
    return x


def _aylar(bas: str, n: int) -> Iterator[str]:
    y, m = map(int, bas.split("-"))
    for _ in range(n):
        yield f"{y:04d}-{m:02d}-01"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def kayitlar(d: dict) -> Iterator[tuple[str, str, Any, str]]:
    """(seri, yürürlük, değer, kanıt) üretir."""
    for t, r, a in d["TCMB_RA"]:
        yield "tcmb_reeskont", t, r, ""
        yield "tcmb_avans", t, a, ""
    for row in d["GECIKME_ZAMMI"]:
        yield "gecikme_zammi", row[0], row[1], row[2] if len(row) > 2 else ""
    for row in d["TECIL"]:
        yield "tecil_faizi", row[0], row[1], row[2] if len(row) > 2 else ""
    for t, o, g in d["TTK1530"]:
        yield "ttk1530", t, {"oran": o, "asgari_giderim": g}, ""
    for t, alis, nakit in d["KK_TL"]:
        yield "kk_azami", t, {"alisveris": _inf(alis), "nakit": nakit}, "dilim: [dönem borcu üst sınırı (null = sınırsız), akdi aylık %, gecikme aylık %]"
    enf = d["ENF"]
    for anahtar, seri in (("tufe", "tufe_aylik"), ("ufe", "ufe_aylik"), ("tufe_yillik", "tufe_yillik"), ("ufe_yillik", "ufe_yillik")):
        for gun, v in zip(_aylar(enf[anahtar]["bas"], len(enf[anahtar]["v"])), enf[anahtar]["v"]):
            if v is not None:
                yield seri, gun, v, ""
    for ay, v in d["TUFE12_RESMI"].items():
        yield "tufe12_ort", ay + "-01", v, ""
    for t, v in d["KIDEM_TAVAN"]:
        yield "kidem_tavan", t, v, ""
    for t, v in d["ASGARI"]:
        yield "asgari_ucret_brut", t, v, ""
    for k in ("AAUT_2025", "AAUT_2026"):
        a = _inf(d[k])
        yield "aaut", a.get("yururluk") or ("2025-11-04" if k == "AAUT_2025" else "2026-11-03"), a, a.get("ad", "")
    h = _inf(d["HARC"])
    yield "harc_tarifesi", "2026-01-01", h, h.get("ad", "")
    yield "vekalet_pulu", "2026-01-01", h["vekaletPulu"], "TBB 2026"
    g = d["GIDER"]
    yield "gider_avansi", "2025-10-28", g, g.get("ad", "")
    yield "ptt_tebligat", "2026-02-04", g["tebligat"], "PTT tebligat ücreti"
    b = d["BILIRKISI"]
    yield "bilirkisi", "2026-01-01", b, b.get("ad", "")
    m = d["MEVDUAT_GUNCEL"]
    yield "mevduat_ort1ay", m["ortHafta"], m["ort1ay"], "TCMB haftalık"
    yield "mevduat_azami", m["azamiAy"] + "-01", {"azami1y": m["azami1y"], "azamiUzun": m["azamiUzun"], "azami1ay": m["azami1ay"]}, "TCMB aylık"


def tohumla(depo: Depo, yol: Path = TOHUM) -> int:
    if depo.ayar_al("tohumlandi"):
        return 0
    d = json.loads(yol.read_text(encoding="utf-8"))
    n = 0
    for seri, t, v, kanit in kayitlar(d):
        depo.ekle(seri, t, v, "tohum", "onayli", "", kanit, [], karar_veren="tohum (YARGUCU gömülü tablo, son doğrulama " + str(d.get("__meta", {}).get("RATES_CHECKED")) + ")")
        n += 1
    depo.ayar_yaz("tohumlandi", {"adet": n, "kaynak_dogrulama": d.get("__meta", {}).get("RATES_CHECKED")})
    return n
