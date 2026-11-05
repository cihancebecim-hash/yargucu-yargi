"""Bekçi: verinin eskimediğini ve toplayıcıların çalıştığını denetler.

Sistem eskimiş bir değerle sessizce çalışamaz: beklenen bir güncelleme gelmediğinde
veya bir kaynak art arda hata verdiğinde alarm açılır; durum düzelince alarm kendiliğinden kapanır.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from .depo import Depo, bugun_tr
from .dogrulama import tek_kaynak_adaylarini_isle
from .seriler import SERILER

KAYNAK_ADLARI = {"resmi_gazete": "Resmî Gazete", "tcmb_sayfa": "TCMB oran sayfası", "evds": "TCMB EVDS"}


def _var_mi(depo: Depo, seri: str, bas: str, son: str, bekleyen_dahil: bool = True) -> bool:
    durumlar = "('onayli','bekliyor','aday')" if bekleyen_dahil else "('onayli')"
    r = depo.sorgu(f"SELECT 1 FROM deger WHERE seri=? AND yururluk BETWEEN ? AND ? AND durum IN {durumlar} LIMIT 1", (seri, bas, son))
    return bool(r)


def seri_durumu(depo: Depo, seri_id: str, bugun: Optional[date] = None) -> Optional[str]:
    """Seri için açık bir eskime sorunu varsa açıklamasını döndürür."""
    s = SERILER[seri_id]
    if not s.beklenen:
        return None
    bugun = bugun or bugun_tr()
    tur, _, param = s.beklenen.partition(":")
    if tur == "aylik_veri":
        gun = int(param)
        onceki_ay = (bugun.replace(day=1) - timedelta(days=1)).replace(day=1)
        hedef = onceki_ay if bugun.day >= gun else (onceki_ay - timedelta(days=1)).replace(day=1)
        if not _var_mi(depo, seri_id, hedef.isoformat(), hedef.isoformat()):
            return f"{s.ad}: {hedef:%m.%Y} verisi henüz alınamadı (her ay {gun}. güne kadar bekleniyor)"
    elif tur == "gun_yasi":
        son = depo.son_onayli(seri_id)
        if not son or (bugun - date.fromisoformat(son["yururluk"])).days > int(param):
            return f"{s.ad}: son onaylı değer {son['yururluk'] if son else '-'} tarihli; {param} günden eski"
    elif tur in ("yillik", "yariyillik"):
        ay, gun = map(int, param.split("-"))
        donemler = [date(bugun.year, ay, gun)]
        if tur == "yariyillik":
            donemler.append(date(bugun.year, ay + 6, gun))
        for esik in donemler:
            bas = esik.replace(day=1)
            if bugun >= esik and not _var_mi(depo, seri_id, bas.isoformat(), (bas + timedelta(days=200)).isoformat(), bekleyen_dahil=False):
                if not depo.son_onayli(seri_id):
                    return f"{s.ad}: henüz hiç doğrulanmış değer yok; yürürlükteki tarifeyi girin"
                return f"{s.ad}: {bas:%m.%Y} döneminin değeri henüz onaylanmadı; hesaplar önceki dönemin değeriyle yapılıyor"
    elif tur == "kaynak_saglik":
        k = depo.son_kontrol(seri_id)
        if not k or time.time() - k > int(param) * 86400:
            return f"{s.ad}: kaynak {param} gündür kontrol edilemedi"
    return None


def calistir(depo: Depo, bugun: Optional[date] = None) -> dict:
    sonuc = {"tek_kaynak": tek_kaynak_adaylarini_isle(depo), "eskime": [], "kaynak": []}
    for sid in SERILER:
        sorun = seri_durumu(depo, sid, bugun)
        if sorun:
            depo.alarm(f"eskime:{sid}", "uyari", sorun)
            sonuc["eskime"].append(sorun)
        else:
            depo.alarm_kapat(f"eskime:{sid}")
    for k in depo.saglik():
        ad = KAYNAK_ADLARI.get(k["kaynak"], k["kaynak"])
        if k["ardisik_hata"] >= 2:
            depo.alarm(f"saglik:{k['kaynak']}", "kritik", f"{ad} {k['ardisik_hata']} kez üst üste okunamadı. Son hata: {k['son_hata']}")
            sonuc["kaynak"].append(ad)
        elif k["ardisik_hata"] == 0:
            depo.alarm_kapat(f"saglik:{k['kaynak']}")
    simdi_tr = datetime.now(timezone.utc) + timedelta(hours=3)
    if (bugun is None and simdi_tr.hour >= 9) or bugun is not None:
        g = (bugun or simdi_tr.date()).isoformat()
        if not depo.rg_getir(g):
            depo.alarm(f"rg_eksik:{g}", "uyari", f"{g} tarihli Resmî Gazete henüz arşivlenemedi.")
        else:
            depo.alarm_kapat(f"rg_eksik:{g}")
    return sonuc
