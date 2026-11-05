"""TCMB Elektronik Veri Dağıtım Sistemi (EVDS) istemcisi.

Anahtar: evds2.tcmb.gov.tr üzerinden ücretsiz üyelikle alınır, EVDS_ANAHTARI ortam
değişkeniyle verilir ve istek başlığında ("key") gönderilir.

Seri kodları evds_seriler.json dosyasındadır. Bir kod, KALİBRASYON geçmeden asla
kullanılmaz: kodun son yıllardaki değerleri, daha önce doğrulanmış tohum verisiyle
birebir karşılaştırılır; tek bir uyuşmazlık bile kodu devre dışı bırakır.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

TABAN = "https://evds2.tcmb.gov.tr/service/evds/"
AYAR = Path(__file__).resolve().parent.parent / "evds_seriler.json"
KALIBRASYON_EN_AZ = 12  # karşılaştırılacak en az ortak dönem


def anahtar() -> str:
    k = os.environ.get("EVDS_ANAHTARI", "").strip()
    if not k:
        raise RuntimeError("EVDS_ANAHTARI tanımlı değil (evds2.tcmb.gov.tr → Profil → API Anahtarı)")
    return k


def seri_ayarlari() -> dict:
    return json.loads(AYAR.read_text(encoding="utf-8"))


def _tarih(s: str) -> Optional[date]:
    """EVDS tarih biçimleri: GG-AA-YYYY (günlük/haftalık), YYYY-A veya YYYY-AA (aylık)."""
    s = (s or "").strip()
    try:
        if len(s) == 10 and s[2] == "-":
            return date(int(s[6:]), int(s[3:5]), int(s[:2]))
        if "-" in s:
            y, m = s.split("-")[:2]
            return date(int(y), int(m), 1)
    except ValueError:
        return None
    return None


def cozumle(json_metin: str | bytes, kod: str) -> list[tuple[date, float]]:
    """EVDS JSON yanıtından (tarih, değer) listesi. Boş değerler atlanır."""
    obj = json.loads(json_metin)
    items = obj.get("items") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        raise ValueError("EVDS yanıtında 'items' listesi yok")
    alan = kod.replace(".", "_")
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        t = _tarih(str(it.get("Tarih", "")))
        v = it.get(alan)
        if t is None or v in (None, "", "null"):
            continue
        try:
            out.append((t, float(str(v).replace(",", "."))))
        except ValueError:
            raise ValueError(f"EVDS değeri sayı değil: {v!r}") from None
    out.sort()
    return out


def donustur(nokta: list[tuple[date, float]], donusum: str) -> list[tuple[date, float]]:
    """Endeks düzeyinden yüzde değişim üretir (TÜİK yöntemiyle, iki ondalık)."""
    if donusum == "seviye":
        return [(t, round(v, 6)) for t, v in nokta]
    d = dict(nokta)
    out = []
    for t, v in nokta:
        if donusum == "aylik_degisim":
            onceki = (t.replace(day=1) - timedelta(days=1)).replace(day=1)
        elif donusum == "yillik_degisim":
            onceki = t.replace(year=t.year - 1)
        else:
            raise ValueError("Bilinmeyen dönüşüm: " + donusum)
        if onceki in d and d[onceki]:
            out.append((t, round((v / d[onceki] - 1) * 100 + 1e-12, 2)))
    return out


async def cek(kod: str, baslangic: date, bitis: date, client: Optional[httpx.AsyncClient] = None) -> list[tuple[date, float]]:
    url = f"{TABAN}series={kod}&startDate={baslangic:%d-%m-%Y}&endDate={bitis:%d-%m-%Y}&type=json"
    kapat = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=15.0))
    try:
        r = await client.get(url, headers={"key": anahtar(), "Accept": "application/json"})
        if r.status_code != 200:
            raise RuntimeError(f"EVDS HTTP {r.status_code}")
        return cozumle(r.content, kod)
    finally:
        if kapat:
            await client.aclose()


def degisim_noktalari(nokta: list[tuple[date, float]]) -> list[tuple[date, float]]:
    """Günlük yayımlanan basamaklı seriden (ör. reeskont oranı) yalnız değerin değiştiği günleri çıkarır."""
    out: list[tuple[date, float]] = []
    for t, v in nokta:
        if not out or abs(out[-1][1] - v) > 1e-9:
            out.append((t, v))
    return out


def kalibre_et(evds_degerler: list[tuple[date, float]], dogru: Callable[[date], Optional[float]]) -> dict:
    """EVDS'ten gelen her değeri, daha önce doğrulanmış değerle karşılaştırır.
    dogru(t): o tarihte doğrulanmış değer (yoksa None). Tek uyuşmazlık kalibrasyonu düşürür."""
    ortak, uyumsuz = 0, []
    for t, v in evds_degerler:
        d = dogru(t)
        if d is None:
            continue
        ortak += 1
        if abs(float(d) - v) > 1e-6:
            uyumsuz.append({"tarih": t.isoformat(), "evds": v, "dogrulanmis": d})
    return {"gecti": ortak >= KALIBRASYON_EN_AZ and not uyumsuz, "ortak": ortak, "uyumsuz": uyumsuz[:10]}
