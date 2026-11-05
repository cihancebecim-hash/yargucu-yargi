"""Zamanlanmış görevler (sunucudaki systemd zamanlayıcısı çalıştırır; yapay zekâ kullanılmaz)."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Callable, Optional

from . import bekci, bildirim
from .depo import Depo, bugun_tr
from .dogrulama import aday_isle
from .kaynaklar import evds, tcmb_sayfa
from .seriler import SERILER


def _kaydet(depo: Depo, kaynak: str, fn: Callable):
    async def sar(*a, **k):
        try:
            sonuc = await fn(*a, **k)
            depo.saglik_kaydet(kaynak, True)
            return sonuc
        except Exception as e:
            n = depo.saglik_kaydet(kaynak, False, f"{type(e).__name__}: {e}")
            return {"hata": f"{type(e).__name__}: {e}", "ardisik_hata": n}
    return sar


async def rg(depo: Depo, gun: Optional[date] = None) -> dict:
    from .kaynaklar import rg as rgk
    bugun = gun or bugun_tr()
    sonuc = {}
    for g in [bugun - timedelta(days=i) for i in range(3, -1, -1)]:  # kaçırılan günleri de tamamla
        if g != bugun and depo.rg_getir(g.isoformat()):
            continue
        sonuc[g.isoformat()] = await rgk.topla(depo, g)
    return sonuc


async def tcmb(depo: Depo, satirlar: Optional[list] = None) -> dict:
    satirlar = satirlar if satirlar is not None else await tcmb_sayfa.cek()
    uyumsuz, ortak = [], 0
    son_r = depo.son_onayli("tcmb_reeskont")
    son_t = son_r["yururluk"] if son_r else "0000-00-00"
    for t, r, a in satirlar:
        if t.isoformat() > son_t:
            continue
        for seri, v in (("tcmb_reeskont", r), ("tcmb_avans", a)):
            d = depo.onayli(seri, t.isoformat())
            if d is not None:
                ortak += 1
                if abs(float(d["deger"]) - v) > 1e-9:
                    uyumsuz.append(f"{t:%d.%m.%Y} {seri}: sayfa {v}, doğrulanmış {d['deger']}")
    if uyumsuz or ortak < 4:
        depo.alarm("kalibrasyon:tcmb_sayfa", "kritik",
                   "TCMB oran sayfası doğrulanmış geçmişle uyuşmuyor; sayfadan değer alınmadı. " + ("; ".join(uyumsuz[:5]) if uyumsuz else f"Yalnız {ortak} ortak kayıt bulundu."))
        return {"kalibrasyon": False, "uyumsuz": uyumsuz, "ortak": ortak}
    depo.alarm_kapat("kalibrasyon:tcmb_sayfa")
    yeni = []
    for t, r, a in satirlar:
        if t.isoformat() <= son_t:
            continue
        for seri, v in (("tcmb_reeskont", r), ("tcmb_avans", a)):
            yeni.append({seri: aday_isle(depo, seri, t.isoformat(), v, "tcmb_sayfa", tcmb_sayfa.URL, f"TCMB sayfası: {t:%d.%m.%Y} reeskont %{r}, avans %{a}")})
    for seri in ("tcmb_reeskont", "tcmb_avans"):
        depo.kontrol_edildi(seri, "tcmb_sayfa")
    return {"kalibrasyon": True, "ortak": ortak, "yeni": yeni}


async def evds_seri(depo: Depo, seri_id: str, ayar: dict, veri: Optional[list] = None) -> dict:
    kod = (ayar.get("kod") or "").strip()
    if not kod:
        return {"atlandi": "kod yok"}
    bugun = bugun_tr()
    bas = bugun - timedelta(days=4 * 365)
    ham = veri if veri is not None else await evds.cek(kod, bas, bugun)
    noktalar = evds.donustur(ham, ayar.get("donusum", "seviye"))
    if ayar.get("basamakli"):
        noktalar = evds.degisim_noktalari(noktalar)
        dogru = lambda t: (lambda r: float(r["deger"]) if r and r["yururluk"] <= t.isoformat() else None)(depo.onayli(seri_id, t.isoformat()))
    else:
        dogru = lambda t: (lambda r: float(r["deger"]) if r and r["yururluk"] == t.isoformat() else None)(depo.onayli(seri_id, t.isoformat()))
    son = depo.son_onayli(seri_id)
    son_t = son["yururluk"] if son else "0000-00-00"
    gecmis = [(t, v) for t, v in noktalar if t.isoformat() <= son_t]
    k = evds.kalibre_et(gecmis, dogru)
    depo.ayar_yaz(f"evds_kalibrasyon:{seri_id}", {"kod": kod, **k})
    if not k["gecti"]:
        depo.alarm(f"kalibrasyon:evds:{seri_id}", "kritik",
                   f"EVDS '{kod}' kodu {SERILER[seri_id].ad} için doğrulanmış geçmişle uyuşmuyor ({k['ortak']} ortak dönem, {len(k['uyumsuz'])} uyumsuz). Bu koddan değer alınmadı; kodu kontrol edin.")
        return {"kalibrasyon": k}
    depo.alarm_kapat(f"kalibrasyon:evds:{seri_id}")
    yeni = [aday_isle(depo, seri_id, t.isoformat(), v, "evds", f"https://evds2.tcmb.gov.tr ({kod})", f"EVDS {kod}: {t:%d.%m.%Y} = {v}")
            for t, v in noktalar if t.isoformat() > son_t]
    depo.kontrol_edildi(seri_id, "evds")
    return {"kalibrasyon": k, "yeni": yeni}


async def evds_hepsi(depo: Depo) -> dict:
    ayarlar = evds.seri_ayarlari()
    out = {}
    for seri_id, a in ayarlar.items():
        if seri_id.startswith("_") or seri_id not in SERILER:
            continue
        try:
            out[seri_id] = await evds_seri(depo, seri_id, a)
        except Exception as e:
            out[seri_id] = {"hata": f"{type(e).__name__}: {e}"}
            raise
    return out


async def gunluk(depo: Depo) -> dict:
    sonuc = {
        "resmi_gazete": await _kaydet(depo, "resmi_gazete", rg)(depo),
        "tcmb_sayfa": await _kaydet(depo, "tcmb_sayfa", tcmb)(depo),
    }
    import os
    if os.environ.get("EVDS_ANAHTARI"):
        sonuc["evds"] = await _kaydet(depo, "evds", evds_hepsi)(depo)
    from . import izleyici
    sonuc["izleyici"] = await _kaydet(depo, "izleyici", izleyici.calistir)(depo)
    sonuc["bekci"] = bekci.calistir(depo)
    sonuc["bildirim"] = bildirim.gonder(depo)
    return sonuc


def calistir(coro):
    return asyncio.run(coro)
