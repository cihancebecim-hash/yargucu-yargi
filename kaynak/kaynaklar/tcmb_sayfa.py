"""TCMB "Reeskont ve Avans Faiz Oranları" sayfası.

Sayfadaki tablodan (tarih, reeskont, avans) satırları çıkarılır. Sayfanın yapısı
değişirse çözümleyici ya hiç satır bulamaz ya da kalibrasyon (geçmiş değerlerin
tohumla karşılaştırılması) düşer; her iki durumda da değer üretilmez, alarm verilir.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

import httpx
from bs4 import BeautifulSoup

URL = "https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB+TR/Main+Menu/Temel+Faaliyetler/Para+Politikasi/Reeskont+ve+Avans+Faiz+Oranlari"
TARIH_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
SAYI_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{1,4})?)(?![\d.,])")
HEADERS = {"User-Agent": "Mozilla/5.0 (YARGUCU Kaynak Motoru)", "Accept-Language": "tr-TR,tr;q=0.9"}


def _sayi(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def cozumle(html: str) -> list[tuple[date, float, float]]:
    """Tablodaki her satırdan bir tarih ve ardından gelen iki oranı çıkarır."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict[date, tuple[float, float]] = {}
    for tr in soup.find_all("tr"):
        hucreler = [" ".join(td.get_text(" ").split()) for td in tr.find_all(["td", "th"])]
        if len(hucreler) < 3:
            continue
        m = TARIH_RE.search(hucreler[0])
        if not m:
            continue
        try:
            t = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            continue
        sayilar = []
        for h in hucreler[1:]:
            mm = SAYI_RE.search(h)
            if mm:
                v = _sayi(mm.group(1))
                if v is not None:
                    sayilar.append(v)
        if len(sayilar) >= 2:
            out[t] = (sayilar[0], sayilar[1])
    return sorted((t, r, a) for t, (r, a) in out.items())


async def cek(client: Optional[httpx.AsyncClient] = None) -> list[tuple[date, float, float]]:
    kapat = client is None
    client = client or httpx.AsyncClient(headers=HEADERS, timeout=httpx.Timeout(40.0, connect=15.0), follow_redirects=True)
    try:
        r = await client.get(URL)
        if r.status_code != 200:
            raise RuntimeError(f"TCMB sayfası HTTP {r.status_code}")
        satirlar = cozumle(r.text)
        if not satirlar:
            raise RuntimeError("TCMB sayfasında oran tablosu bulunamadı (sayfa yapısı değişmiş olabilir)")
        return satirlar
    finally:
        if kapat:
            await client.aclose()
