"""Takip edilen oran ve tarife serilerinin katalogu.

Her seri için: ne olduğu, hangi resmî kaynaktan geldiği, ne sıklıkla değişmesi
beklendiği, makul değer aralığı, bir adımda en çok ne kadar değişebileceği ve
yeni değerin hangi kuralla onaylanacağı tanımlanır.

Onay kuralları:
  "iki_kaynak" : İki bağımsız kaynak aynı değeri verirse otomatik onaylanır;
                 tek kaynak gelirse onay bekler.
  "elle"       : Değer her zaman yöneticinin onayını bekler (karmaşık tarife tabloları).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Seri:
    id: str
    ad: str
    birim: str                      # "%", "% aylık", "TL", "tablo"
    tur: str                        # "sayi" | "tablo"
    siklik: str                     # "gunluk" | "haftalik" | "aylik" | "yariyillik" | "yillik" | "duzensiz"
    dayanak: str
    kaynak_adi: str
    onay: str = "iki_kaynak"
    makul: Optional[tuple[float, float]] = None   # sayı serileri için alt/üst sınır
    max_degisim: Optional[float] = None           # bir önceki değere göre en büyük mutlak fark
    max_oransal: Optional[float] = None           # bir önceki değere göre en büyük oransal fark (0.5 = %50)
    rg_desenleri: tuple[str, ...] = field(default_factory=tuple)  # Resmî Gazete başlığında yayımı tanıyan desenler
    beklenen: Optional[str] = None                # bekçi kuralı (bkz. bekci.py)
    aciklama: str = ""


SERILER: dict[str, Seri] = {}


def _ekle(s: Seri) -> None:
    if s.id in SERILER:
        raise ValueError("Seri iki kez tanımlandı: " + s.id)
    SERILER[s.id] = s


# ---------------- TCMB ----------------
_ekle(Seri("tcmb_reeskont", "TCMB reeskont (iskonto) faiz oranı", "%", "sayi", "duzensiz",
           "TCMB; 3095 s.K. m.1-2", "TCMB Reeskont ve Avans Faiz Oranları",
           makul=(1, 150), max_degisim=15, beklenen="kaynak_saglik:2"))
_ekle(Seri("tcmb_avans", "TCMB avans faiz oranı", "%", "sayi", "duzensiz",
           "TCMB; 3095 s.K. m.2/2", "TCMB Reeskont ve Avans Faiz Oranları",
           makul=(1, 160), max_degisim=15, beklenen="kaynak_saglik:2"))
_ekle(Seri("ttk1530", "TTK m.1530 geç ödeme temerrüt faizi ve asgari giderim", "tablo", "tablo", "yillik",
           "6102 s.K. m.1530/7", "TCMB (her yıl ocak)", onay="elle", beklenen="yillik:01-15"))
_ekle(Seri("kk_azami", "Kredi kartı azami aylık faiz oranları", "tablo", "tablo", "aylik",
           "TCMB 2020/16 s. Tebliğ", "TCMB (aylık duyuru)", onay="elle", beklenen="kaynak_saglik:35"))
_ekle(Seri("mevduat_ort1ay", "1 aya kadar vadeli TL mevduat ağırlıklı ortalama faizi (haftalık)", "%", "sayi", "haftalik",
           "TCMB haftalık mevduat faizleri", "TCMB EVDS", makul=(0, 150), max_degisim=10, beklenen="gun_yasi:12"))
_ekle(Seri("mevduat_azami", "Mevduata fiilen uygulanan azami faiz oranları (aylık)", "tablo", "tablo", "aylik",
           "1475 s.K. m.14 (işçilik alacakları)", "TCMB (aylık)", onay="elle", beklenen="gun_yasi:70"))

# ---------------- Enflasyon (TÜİK) ----------------
_ekle(Seri("tufe_aylik", "TÜFE aylık değişim", "% aylık", "sayi", "aylik",
           "TÜİK", "TÜİK / TCMB EVDS", makul=(-10, 40), max_degisim=20, beklenen="aylik_veri:4"))
_ekle(Seri("ufe_aylik", "Yİ-ÜFE aylık değişim", "% aylık", "sayi", "aylik",
           "TÜİK", "TÜİK / TCMB EVDS", makul=(-15, 50), max_degisim=25, beklenen="aylik_veri:4"))
_ekle(Seri("tufe_yillik", "TÜFE yıllık değişim", "%", "sayi", "aylik",
           "TÜİK", "TÜİK / TCMB EVDS", makul=(-10, 200), max_degisim=30, beklenen="aylik_veri:4"))
_ekle(Seri("ufe_yillik", "Yİ-ÜFE yıllık değişim", "%", "sayi", "aylik",
           "TÜİK", "TÜİK / TCMB EVDS", makul=(-15, 250), max_degisim=40, beklenen="aylik_veri:4"))
_ekle(Seri("tufe12_ort", "TÜFE on iki aylık ortalamalara göre değişim (kira artış sınırı)", "%", "sayi", "aylik",
           "TBK m.344", "TÜİK", makul=(0, 200), max_degisim=15, beklenen="aylik_veri:4"))

# ---------------- Kamu alacakları ----------------
_ekle(Seri("gecikme_zammi", "Gecikme zammı (aylık)", "% aylık", "sayi", "duzensiz",
           "6183 s.K. m.51", "Cumhurbaşkanı Kararı (Resmî Gazete)", onay="elle", makul=(0.5, 15), max_degisim=3,
           rg_desenleri=(r"6183.*51\s*inci\s*madde.*gecikme\s*zamm", r"gecikme\s*zamm.*oran.*belirlen"),
           beklenen="kaynak_saglik:2"))
_ekle(Seri("tecil_faizi", "Tecil faizi (yıllık)", "%", "sayi", "duzensiz",
           "6183 s.K. m.48", "Tahsilat Genel Tebliği (Resmî Gazete)", onay="elle", makul=(1, 150), max_degisim=30,
           rg_desenleri=(r"tahsilat\s*genel\s*tebli", r"tecil\s*faiz"), beklenen="kaynak_saglik:2"))

# ---------------- İş hukuku ----------------
_ekle(Seri("asgari_ucret_brut", "Brüt asgari ücret (aylık)", "TL", "sayi", "yariyillik",
           "4857 s.K. m.39", "Asgari Ücret Tespit Komisyonu Kararı (Resmî Gazete)", onay="elle",
           makul=(1000, 1_000_000), max_oransal=1.0,
           rg_desenleri=(r"asgari\s*ücret\s*tespit\s*komisyonu\s*karar",), beklenen="yillik:01-05"))
_ekle(Seri("kidem_tavan", "Kıdem tazminatı tavanı", "TL", "sayi", "yariyillik",
           "1475 s.K. m.14", "Hazine ve Maliye Bakanlığı mali haklar genelgesi", onay="elle",
           makul=(1000, 5_000_000), max_oransal=0.8, beklenen="yariyillik:01-10"))

# ---------------- Yargılama giderleri ve tarifeler ----------------
_ekle(Seri("harc_tarifesi", "Yargı harçları (492 s.K. tarifeleri)", "tablo", "tablo", "yillik",
           "492 s.K.; Harçlar Kanunu Genel Tebliği", "Resmî Gazete", onay="elle",
           rg_desenleri=(r"harçlar\s*kanunu\s*genel\s*tebli",), beklenen="yillik:01-05"))
_ekle(Seri("aaut", "Avukatlık Asgari Ücret Tarifesi", "tablo", "tablo", "yillik",
           "1136 s.K. m.168", "Resmî Gazete", onay="elle",
           rg_desenleri=(r"avukatl[ıi]k\s*asgari\s*ücret\s*tarife",)))
_ekle(Seri("bilirkisi", "Bilirkişilik Asgari Ücret Tarifesi", "tablo", "tablo", "yillik",
           "6754 s.K.", "Resmî Gazete", onay="elle",
           rg_desenleri=(r"bilirkişilik\s*asgari\s*ücret\s*tarife",), beklenen="yillik:01-05"))
_ekle(Seri("arabuluculuk", "Arabuluculuk Asgari Ücret Tarifesi", "tablo", "tablo", "yillik",
           "6325 s.K.", "Resmî Gazete", onay="elle",
           rg_desenleri=(r"arabuluculuk\s*asgari\s*ücret\s*tarife",), beklenen="yillik:01-05"))
_ekle(Seri("gider_avansi", "HMK Gider Avansı Tarifesi", "tablo", "tablo", "yillik",
           "6100 s.K. m.120", "Resmî Gazete", onay="elle",
           rg_desenleri=(r"gider\s*avans[ıi]\s*tarife",)))
_ekle(Seri("ptt_tebligat", "PTT tebligat ücreti", "TL", "sayi", "duzensiz",
           "7201 s.K.; PTT tarifesi", "PTT", onay="elle", makul=(1, 100_000), max_oransal=1.5))
_ekle(Seri("vekalet_pulu", "Vekâlet pulu", "TL", "sayi", "yillik",
           "1136 s.K. m.27", "TBB", onay="elle", makul=(1, 100_000), max_oransal=1.5, beklenen="yillik:01-10"))

# Türetilen seriler veritabanında tutulmaz; kaynak serilerden formülle hesaplanır (turet.py).
TURETILEN = {
    "kanuni_faiz": "3095 s.K. m.1: TCMB reeskont oranına bağlı, altı aylık kural",
    "avans_faizi_3095": "3095 s.K. m.2/2: TCMB avans oranına bağlı, altı aylık kural",
}


def rg_tani(baslik: str) -> list[str]:
    """Resmî Gazete kalem başlığından, yayımını takip ettiğimiz serileri bulur."""
    t = baslik.replace("I", "ı").replace("İ", "i").lower()
    out = []
    for s in SERILER.values():
        for d in s.rg_desenleri:
            if re.search(d, t, re.I):
                out.append(s.id)
                break
    return out
