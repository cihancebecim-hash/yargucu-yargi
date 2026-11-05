"""Resmî Gazete toplayıcısı.

Her gün fihristi (mükerrerler dahil) arşivler ve takip edilen tarifelerin
(harç, AAÜT, bilirkişi, arabuluculuk, gider avansı, asgari ücret, gecikme zammı,
tecil faizi) yayımını başlıktan tanır. Tanınan her yayım için:
  * kalıcı bir tespit kaydı açılır,
  * yöneticiye "yeni tarife yayımlandı, değerleri onaylayın" alarmı gider,
  * değer çıkarılabilen basit düzenlemelerde (gecikme zammı) onaya hazır bir aday oluşturulur.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

import resmi_gazete as rgm

from ..depo import Depo
from ..dogrulama import aday_isle
from ..seriler import SERILER, rg_tani

GZ_RE = re.compile(r"(?:aylık\s*)?(?:%|yüzde)\s*(\d{1,2}(?:[.,]\d{1,2})?)", re.I)


def gecikme_zammi_cikar(metin: str) -> Optional[tuple[float, str]]:
    """Cumhurbaşkanı Kararı metninden aylık gecikme zammı oranını çıkarır.
    Yalnız 'gecikme zammı' ifadesinin geçtiği cümledeki oran kabul edilir; birden çok farklı oran varsa None."""
    cumleler = re.split(r"(?<=[.;])\s+", " ".join(metin.split()))
    adaylar = set()
    kanit = ""
    for c in cumleler:
        if re.search(r"gecikme\s+zamm", c, re.I) and re.search(r"aylık|her\s+ay", c, re.I):
            for m in GZ_RE.finditer(c):
                adaylar.add(float(m.group(1).replace(",", ".")))
                kanit = kanit or c[:400]
    if len(adaylar) == 1:
        return adaylar.pop(), kanit
    return None


async def topla(depo: Depo, gun: date, client=None) -> dict:
    kapat = client is None
    client = client or rgm._client()
    try:
        sayilar = await rgm._fetch_all(client, gun, True)
        if not sayilar:
            return {"tarih": gun.isoformat(), "durum": "yayim_yok"}
        tespitler = []
        for s in sayilar:
            depo.rg_kaydet(gun.isoformat(), int(s.get("mukerrer") or 0), s.get("sayi"), s)
            for b in s["bolumler"]:
                for k in b["kalemler"]:
                    if k.get("ilan"):
                        continue
                    for seri in rg_tani(k["baslik"]):
                        if depo.rg_tespit_ekle(gun.isoformat(), seri, k["baslik"], k["url"]):
                            tespitler.append((seri, k))
        for s_ in SERILER.values():  # fihrist başarıyla tarandı: başlıktan izlenen seriler kontrol edilmiş sayılır
            if s_.rg_desenleri:
                depo.kontrol_edildi(s_.id, "resmi_gazete")
        for seri, k in tespitler:
            ad = SERILER[seri].ad
            depo.alarm(f"rg:{seri}:{k['url']}", "uyari",
                       f"Resmî Gazete {gun:%d.%m.%Y}: '{k['baslik']}' yayımlandı ({ad}). Yeni değerler girilip onaylanana kadar hesaplar önceki tarifeyle yapılır ve ekranda uyarı gösterilir. Bağlantı: {k['url']}")
            if seri == "gecikme_zammi":
                await _gecikme_zammi_adayi(depo, client, gun, k)
        return {"tarih": gun.isoformat(), "durum": "tamam", "sayi": [s.get("sayi") for s in sayilar], "tespit": [{"seri": s, "baslik": k["baslik"]} for s, k in tespitler]}
    finally:
        if kapat:
            await client.aclose()


async def _gecikme_zammi_adayi(depo: Depo, client, gun: date, kalem: dict) -> None:
    try:
        belge = await rgm._doc_text(client, kalem["url"])
        metin = belge.get("metin") or ""
        if not metin and belge.get("taranmis"):
            from .. import ocr
            if ocr.hazir_mi():
                r = await rgm._get(client, rgm._real_url(kalem["url"]))
                metin = ocr.pdf_metni(r.content, en_cok_sayfa=5)
        sonuc = gecikme_zammi_cikar(metin)
        if sonuc:
            oran, kanit = sonuc
            yururluk = (gun + timedelta(days=1)).isoformat() if re.search(r"izleyen\s+gün", metin, re.I) else gun.isoformat()
            aday_isle(depo, "gecikme_zammi", yururluk, oran, "rg_metin", kalem["url"], kanit + " — Yürürlük tarihini metinden kontrol edin.")
    except Exception as e:  # değer çıkarılamazsa tespit alarmı zaten açık; ayrıca not düş
        depo.alarm(f"rgcikar:{kalem['url']}", "uyari", f"Gecikme zammı kararı okunamadı ({type(e).__name__}); değeri elle girin: {kalem['url']}")
