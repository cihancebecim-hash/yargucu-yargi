"""Sayfa değişikliği izleyicisi: değerini otomatik okuyamadığımız resmî sayfalar için güvenlik ağı.

Sayfanın görünen metni her gün alınır ve bir önceki halle karşılaştırılır. Metin değişirse
"yeni değer yayımlanmış olabilir" alarmı açılır. Böylece bu seriler için de bir değişiklik
sessizce kaçırılamaz. İzlenecek sayfalar izlenen_sayfalar.json dosyasındadır.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from .depo import Depo
from .seriler import SERILER

AYAR = Path(__file__).resolve().parent / "izlenen_sayfalar.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (YARGUCU Kaynak Motoru)", "Accept-Language": "tr-TR,tr;q=0.9"}


def normal_metin(html: str, secici: Optional[str] = None) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for s in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        s.decompose()
    kok = soup.select_one(secici) if secici else soup.body or soup
    metin = " ".join((kok or soup).get_text(" ").split())
    # Sayfa her açılışta değişen saat/ziyaretçi sayacı gibi gürültüyü at
    return re.sub(r"\b\d{1,2}:\d{2}(:\d{2})?\b", "", metin)


async def calistir(depo: Depo, client: Optional[httpx.AsyncClient] = None) -> dict:
    sayfalar = [x for x in json.loads(AYAR.read_text(encoding="utf-8")).get("sayfalar", []) if x.get("url")]
    kapat = client is None
    client = client or httpx.AsyncClient(headers=HEADERS, timeout=httpx.Timeout(40.0, connect=15.0), follow_redirects=True)
    sonuc = {}
    try:
        for s in sayfalar:
            anahtar = f"izleyici:{s['seri']}:{s['url']}"
            try:
                r = await client.get(s["url"])
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                metin = normal_metin(r.text, s.get("secici"))
                if len(metin) < 50:
                    raise RuntimeError("Sayfa metni boş geldi")
                ozet = hashlib.sha256(metin.encode()).hexdigest()
                onceki = depo.ayar_al(anahtar)
                depo.ayar_yaz(anahtar, {"ozet": ozet, "uzunluk": len(metin)})
                depo.kontrol_edildi(s["seri"], "izleyici")
                depo.alarm_kapat(f"izleyici_hata:{s['seri']}")
                if onceki and onceki.get("ozet") != ozet:
                    ad = SERILER[s["seri"]].ad if s["seri"] in SERILER else s["seri"]
                    depo.alarm(f"izleyici_degisti:{s['seri']}:{ozet[:12]}", "uyari",
                               f"{ad}: resmî sayfa değişti, yeni değer yayımlanmış olabilir. Sayfayı kontrol edip yeni değeri girin: {s['url']}")
                    sonuc[s["seri"]] = "degisti"
                else:
                    sonuc[s["seri"]] = "ayni" if onceki else "ilk_kayit"
            except Exception as e:
                depo.alarm(f"izleyici_hata:{s['seri']}", "uyari", f"{s['seri']} için izlenen sayfa okunamadı ({type(e).__name__}: {e}): {s['url']}")
                sonuc[s["seri"]] = "hata"
    finally:
        if kapat:
            await client.aclose()
    return sonuc
