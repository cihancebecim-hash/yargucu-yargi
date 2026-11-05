"""Kanunla başka bir orana bağlanmış oranların formülle hesaplanması.

YARGUCU uygulamasındaki hesap motoruyla (rateOn "kanuni" ve "ticari") birebir aynı kural
uygulanır; testler iki tarafın aynı sonucu verdiğini doğrular.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from .depo import Depo


def _r2(x: float) -> float:
    return float(f"{x + 1e-12:.2f}") if x >= 0 else -float(f"{-x + 1e-12:.2f}")


def _tcmb_at(depo: Depo, seri: str, gun: date) -> Optional[float]:
    r = depo.onayli(seri, gun.isoformat())
    return float(r["deger"]) if r else None


def _altı_aylik(depo: Depo, seri: str, gun: date) -> tuple[Optional[float], str]:
    """3095 yöntemi: yılın ilk yarısında önceki yılın 31 Aralık oranı; 30 Haziran oranı
    5 puan veya daha fazla farklıysa ikinci yarıda 30 Haziran oranı."""
    y = gun.year
    taban = _tcmb_at(depo, seri, date(y - 1, 12, 31))
    if gun.month >= 7:
        haz = _tcmb_at(depo, seri, date(y, 6, 30))
        if haz is not None and taban is not None and abs(haz - taban) >= 5:
            return haz, f"30.06.{y}"
    return taban, f"31.12.{y - 1}"


def kanuni_faiz(depo: Depo, gun: date) -> dict:
    if gun < date(1998, 1, 1):
        return {"oran": 30.0, "dayanak": "3095 s.K. m.1 (ilk hâli)"}
    if gun < date(2000, 1, 1):
        return {"oran": 50.0, "dayanak": "BKK 97/9807"}
    if gun < date(2005, 5, 1):
        o, ref = _altı_aylik(depo, "tcmb_reeskont", gun)
        return {"oran": o, "dayanak": f"3095 m.1 (4489 s.K.): TCMB reeskont oranı ({ref})"}
    if gun < date(2006, 1, 1):
        return {"oran": 12.0, "dayanak": "3095 m.1 (5335 s.K. m.14)"}
    if gun < date(2024, 6, 1):
        return {"oran": 9.0, "dayanak": "BKK 2005/9831 (RG 30.12.2005/26039)"}
    if gun < date(2026, 7, 31):
        return {"oran": 24.0, "dayanak": "8485 s. CB Kararı (RG 21.05.2024/32552)"}
    o, ref = _altı_aylik(depo, "tcmb_reeskont", gun)
    if o is None:
        return {"oran": None, "dayanak": "TCMB reeskont oranı bulunamadı"}
    return {"oran": _r2(o * 0.8), "dayanak": f"3095 m.1 (7589 s.K. m.10): TCMB reeskont oranı %{str(o).replace('.', ',')} ({ref}) × %80"}


def ticari_temerrut(depo: Depo, gun: date) -> dict:
    k = kanuni_faiz(depo, gun)
    if gun < date(2000, 1, 1):
        r = _tcmb_at(depo, "tcmb_reeskont", gun)
        v = max(k["oran"], r or 0)
        return {"oran": v, "dayanak": "3095 m.2/3 (eski): reeskont oranı" if v > k["oran"] else k["dayanak"]}
    a, ref = _altı_aylik(depo, "tcmb_avans", gun)
    if a is not None and k["oran"] is not None and a > k["oran"]:
        return {"oran": a, "dayanak": f"3095 m.2/2: TCMB avans faiz oranı ({ref})"}
    return {"oran": k["oran"], "dayanak": k["dayanak"] + " (avans oranı kanuni faizin altında)"}


TURETICILER = {"kanuni_faiz": kanuni_faiz, "avans_faizi_3095": ticari_temerrut}
