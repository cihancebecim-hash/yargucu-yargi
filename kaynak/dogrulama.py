"""Yeni gelen değerlerin doğrulanması ve onay kuralının uygulanması.

aday_isle() her toplayıcının tek giriş kapısıdır. Bir değerin onaylı depoya
girebilmesinin yolları:
  1. "iki_kaynak" serilerinde iki bağımsız kaynak aynı değeri verirse ve makullük
     kontrollerinden hiçbiri takılmazsa otomatik onay.
  2. Yöneticinin açık onayı (oran_onayla aracı).
Bunların dışında hiçbir değer hesaplara giremez.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from typing import Any, Optional

from .depo import Depo, bugun_tr
from .seriler import SERILER, Seri

TEK_KAYNAK_BEKLEME_SAAT = 48  # tek kaynaktan gelen aday bu süre sonunda onaya düşer


def esit(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-9)
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)


def bicim_kontrol(s: Seri, deger: Any) -> list[str]:
    if s.tur == "sayi":
        if isinstance(deger, bool) or not isinstance(deger, (int, float)) or not math.isfinite(float(deger)):
            return [f"Değer sayı olmalı: {deger!r}"]
        return []
    if not isinstance(deger, (dict, list)) or not deger:
        return ["Tablo değeri boş veya biçimsiz"]
    return []


def makullik(s: Seri, deger: Any, yururluk: str, onceki: Optional[dict], son: Optional[dict]) -> list[str]:
    sorun: list[str] = []
    try:
        y = date.fromisoformat(yururluk)
    except ValueError:
        return ["Yürürlük tarihi geçersiz: " + str(yururluk)]
    if y > bugun_tr() + timedelta(days=400):
        sorun.append(f"Yürürlük tarihi {yururluk} bir yıldan fazla ileride")
    if y < date(1950, 1, 1):
        sorun.append(f"Yürürlük tarihi {yururluk} makul değil")
    if son and yururluk < son["yururluk"]:
        sorun.append(f"Geçmişe dönük kayıt: son onaylı yürürlük {son['yururluk']}, gelen {yururluk}")
    if s.tur == "sayi" and isinstance(deger, (int, float)):
        v = float(deger)
        if s.makul and not (s.makul[0] <= v <= s.makul[1]):
            sorun.append(f"Değer makul aralık dışında: {v} (beklenen {s.makul[0]}–{s.makul[1]})")
        if onceki and isinstance(onceki["deger"], (int, float)):
            p = float(onceki["deger"])
            if s.max_degisim is not None and abs(v - p) > s.max_degisim:
                sorun.append(f"Önceki değere göre olağan dışı değişim: {p} → {v} (en çok ±{s.max_degisim} bekleniyor)")
            if s.max_oransal is not None and p != 0 and abs(v - p) / abs(p) > s.max_oransal:
                sorun.append(f"Önceki değere göre olağan dışı oransal değişim: {p} → {v}")
            if s.id in ("asgari_ucret_brut", "kidem_tavan", "vekalet_pulu") and v < p:
                sorun.append(f"Tutar düşmüş görünüyor: {p} → {v}")
    return sorun


def aday_isle(depo: Depo, seri_id: str, yururluk: str, deger: Any, kaynak: str, kaynak_url: str = "", kanit: str = "") -> dict:
    """Bir kaynaktan gelen değeri işler. Dönen 'sonuc':
    'zaten_onayli' | 'onaylandi' | 'aday' | 'bekliyor' | 'cakisma'"""
    s = SERILER.get(seri_id)
    if not s:
        raise ValueError("Bilinmeyen seri: " + seri_id)
    depo.kontrol_edildi(seri_id, kaynak)
    if s.tur == "sayi" and isinstance(deger, (int, float)) and not isinstance(deger, bool):
        deger = round(float(deger), 6)

    hatalar = bicim_kontrol(s, deger)
    if hatalar:
        depo.alarm(f"bicim:{seri_id}:{kaynak}", "kritik", f"{s.ad}: {kaynak} kaynağından biçimsiz değer geldi ({'; '.join(hatalar)}). Toplayıcı veya kaynak sayfası değişmiş olabilir.")
        return {"sonuc": "reddedildi", "sorunlar": hatalar}

    ayni = depo.ayni_tarihli(seri_id, yururluk)
    onayli = next((x for x in ayni if x["durum"] == "onayli"), None)
    if onayli:
        if esit(onayli["deger"], deger):
            return {"sonuc": "zaten_onayli", "id": onayli["id"]}
        sorun = [f"Çakışma: {yururluk} için onaylı değer {onayli['deger']!r}, {kaynak} kaynağı {deger!r} veriyor"]
        i = depo.ekle(seri_id, yururluk, deger, kaynak, "bekliyor", kaynak_url, kanit, sorun)
        depo.alarm(f"cakisma:{seri_id}:{yururluk}", "kritik", f"{s.ad}: {sorun[0]}. Onaylı değer değiştirilmedi; kontrol edin.")
        return {"sonuc": "cakisma", "id": i, "sorunlar": sorun}

    # Aynı kaynaktan aynı değer zaten aday/bekliyor ise yeni kayıt açma
    for x in ayni:
        if x["durum"] in ("aday", "bekliyor") and x["kaynak"] == kaynak and esit(x["deger"], deger):
            return {"sonuc": x["durum"], "id": x["id"]}

    onceki = depo.onayli(seri_id, (date.fromisoformat(yururluk) - timedelta(days=1)).isoformat())
    son = depo.son_onayli(seri_id)
    sorun = makullik(s, deger, yururluk, onceki, son)

    if s.onay == "elle" or sorun:
        i = depo.ekle(seri_id, yururluk, deger, kaynak, "bekliyor", kaynak_url, kanit, sorun)
        seviye = "uyari" if sorun else "bilgi"
        depo.alarm(f"onay:{seri_id}:{yururluk}", seviye,
                   f"{s.ad}: {yururluk} yürürlüklü yeni değer onay bekliyor ({kaynak})" + (f" — dikkat: {'; '.join(sorun)}" if sorun else "") + ".")
        return {"sonuc": "bekliyor", "id": i, "sorunlar": sorun}

    # iki_kaynak kuralı
    diger = [x for x in ayni if x["durum"] in ("aday", "bekliyor") and x["kaynak"] != kaynak]
    uyan = next((x for x in diger if esit(x["deger"], deger)), None)
    if uyan:
        i = depo.ekle(seri_id, yururluk, deger, f"{uyan['kaynak']}+{kaynak}", "onayli", kaynak_url or uyan.get("kaynak_url") or "",
                      kanit or uyan.get("kanit") or "", [], karar_veren="otomatik: iki kaynak uyumlu")
        for x in diger:
            if x["durum"] in ("aday", "bekliyor"):
                depo.karar(x["id"], "reddedildi", "birleştirildi" if esit(x["deger"], deger) else "uyumsuz kaynak")
        depo.alarm_kapat(f"tek:{seri_id}:{yururluk}")
        depo.alarm(f"yeni:{seri_id}:{yururluk}", "bilgi", f"{s.ad}: {yururluk} yürürlüklü yeni değer {deger} otomatik onaylandı (iki kaynak uyumlu).")
        return {"sonuc": "onaylandi", "id": i}
    uyumsuz = [x for x in diger if not esit(x["deger"], deger)]
    if uyumsuz:
        sorun = [f"Kaynaklar uyuşmuyor: {uyumsuz[0]['kaynak']}={uyumsuz[0]['deger']!r}, {kaynak}={deger!r}"]
        i = depo.ekle(seri_id, yururluk, deger, kaynak, "bekliyor", kaynak_url, kanit, sorun)
        for x in uyumsuz:
            if x["durum"] == "aday":
                with depo.islem() as db:
                    db.execute("UPDATE deger SET durum='bekliyor' WHERE id=?", (x["id"],))
        depo.alarm(f"cakisma:{seri_id}:{yururluk}", "kritik", f"{s.ad}: {sorun[0]}. Hiçbir değer uygulanmadı; kontrol edin.")
        return {"sonuc": "cakisma", "id": i, "sorunlar": sorun}
    i = depo.ekle(seri_id, yururluk, deger, kaynak, "aday", kaynak_url, kanit, [])
    return {"sonuc": "aday", "id": i}


def tek_kaynak_adaylarini_isle(depo: Depo, saat: float = TEK_KAYNAK_BEKLEME_SAAT) -> int:
    """İkinci kaynakla doğrulanamayan eski adayları onaya düşürür."""
    import time
    sinir = time.time() - saat * 3600
    n = 0
    for r in depo.sorgu("SELECT id, seri, yururluk, deger, kaynak FROM deger WHERE durum='aday' AND olusturma < ?", (sinir,)):
        with depo.islem() as db:
            db.execute("UPDATE deger SET durum='bekliyor', sorunlar=? WHERE id=?", (json.dumps(["İkinci bağımsız kaynakla doğrulanamadı"], ensure_ascii=False), r["id"]))
        s = SERILER.get(r["seri"])
        depo.alarm(f"tek:{r['seri']}:{r['yururluk']}", "uyari",
                   f"{s.ad if s else r['seri']}: {r['yururluk']} yürürlüklü değer {json.loads(r['deger'])} yalnız '{r['kaynak']}' kaynağından geldi; ikinci kaynakla doğrulanamadı, onayınızı bekliyor.")
        n += 1
    return n
