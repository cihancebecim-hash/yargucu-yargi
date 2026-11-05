"""Tarihe bağlı oran deposu (SQLite).

Kurallar:
  * Onaylı bir değer asla silinmez ve üzerine yazılmaz.
  * Aynı seri ve yürürlük tarihi için farklı bir değer gelirse çakışma kaydedilir,
    alarm üretilir ve yeni değer onay bekler.
  * Sorgular yalnız onaylı değerleri döndürür.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

SEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS deger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  seri TEXT NOT NULL,
  yururluk TEXT NOT NULL,              -- YYYY-AA-GG
  deger TEXT NOT NULL,                 -- JSON
  kaynak TEXT NOT NULL,                -- kısa kaynak adı (ör. "tcmb_sayfa", "evds", "rg_metin", "tohum", "elle")
  kaynak_url TEXT,
  kanit TEXT,                          -- alıntı veya açıklama
  durum TEXT NOT NULL CHECK (durum IN ('onayli','bekliyor','reddedildi','aday')),
  olusturma REAL NOT NULL,
  karar_zamani REAL,
  karar_veren TEXT,
  sorunlar TEXT                        -- JSON liste: doğrulama bulguları
);
CREATE UNIQUE INDEX IF NOT EXISTS deger_tek_onayli ON deger(seri, yururluk) WHERE durum = 'onayli';
CREATE INDEX IF NOT EXISTS deger_seri ON deger(seri, yururluk);
CREATE TABLE IF NOT EXISTS saglik (
  kaynak TEXT PRIMARY KEY,
  son_deneme REAL, son_basari REAL, son_hata TEXT, ardisik_hata INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS alarm (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  anahtar TEXT NOT NULL,               -- aynı sorun tekrar tekrar alarm üretmesin diye
  zaman REAL NOT NULL,
  seviye TEXT NOT NULL CHECK (seviye IN ('kritik','uyari','bilgi')),
  mesaj TEXT NOT NULL,
  cozuldu REAL,
  bildirildi REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS alarm_acik ON alarm(anahtar) WHERE cozuldu IS NULL;
CREATE TABLE IF NOT EXISTS rg_arsiv (
  tarih TEXT NOT NULL, mukerrer INTEGER NOT NULL, sayi TEXT, fihrist TEXT NOT NULL, alindi REAL NOT NULL,
  PRIMARY KEY (tarih, mukerrer)
);
CREATE TABLE IF NOT EXISTS rg_tespit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tarih TEXT NOT NULL, seri TEXT NOT NULL, baslik TEXT NOT NULL, url TEXT NOT NULL,
  durum TEXT NOT NULL DEFAULT 'yeni' CHECK (durum IN ('yeni','islendi','ilgisiz')),
  olusturma REAL NOT NULL,
  UNIQUE (url, seri)
);
CREATE TABLE IF NOT EXISTS kontrol (
  seri TEXT PRIMARY KEY, son_kontrol REAL NOT NULL, kaynak TEXT
);
CREATE TABLE IF NOT EXISTS ayar (anahtar TEXT PRIMARY KEY, deger TEXT NOT NULL);
"""


def simdi() -> float:
    return time.time()


def bugun_tr() -> date:
    return datetime.fromtimestamp(time.time() + 3 * 3600, tz=timezone.utc).date()


class Depo:
    def __init__(self, yol: Optional[str] = None):
        self.yol = yol or os.environ.get("KAYNAK_DB", str(Path(__file__).resolve().parent.parent / "veri" / "kaynak.db"))
        if self.yol != ":memory:":
            Path(self.yol).parent.mkdir(parents=True, exist_ok=True)
        self._kilit = threading.RLock()
        self._db = sqlite3.connect(self.yol, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(SEMA)

    @contextmanager
    def islem(self) -> Iterator[sqlite3.Connection]:
        with self._kilit:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def sorgu(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._kilit:
            return list(self._db.execute(sql, args))

    # ---------------- değerler ----------------
    def onayli(self, seri: str, tarih: Optional[str] = None) -> Optional[dict]:
        """Verilen tarihte yürürlükte olan onaylı değer."""
        tarih = tarih or bugun_tr().isoformat()
        r = self.sorgu("SELECT * FROM deger WHERE seri=? AND durum='onayli' AND yururluk<=? ORDER BY yururluk DESC LIMIT 1", (seri, tarih))
        return _satir(r[0]) if r else None

    def son_onayli(self, seri: str) -> Optional[dict]:
        r = self.sorgu("SELECT * FROM deger WHERE seri=? AND durum='onayli' ORDER BY yururluk DESC LIMIT 1", (seri,))
        return _satir(r[0]) if r else None

    def seri(self, seri: str, baslangic: Optional[str] = None) -> list[dict]:
        r = self.sorgu("SELECT * FROM deger WHERE seri=? AND durum='onayli' AND yururluk>=? ORDER BY yururluk", (seri, baslangic or "0000-00-00"))
        return [_satir(x) for x in r]

    def ayni_tarihli(self, seri: str, yururluk: str) -> list[dict]:
        return [_satir(x) for x in self.sorgu("SELECT * FROM deger WHERE seri=? AND yururluk=? ORDER BY id", (seri, yururluk))]

    def ekle(self, seri: str, yururluk: str, deger: Any, kaynak: str, durum: str, kaynak_url: str = "", kanit: str = "",
             sorunlar: Optional[list] = None, karar_veren: Optional[str] = None) -> int:
        _tarih_kontrol(yururluk)
        with self.islem() as db:
            cur = db.execute(
                "INSERT INTO deger (seri, yururluk, deger, kaynak, kaynak_url, kanit, durum, olusturma, karar_zamani, karar_veren, sorunlar)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (seri, yururluk, json.dumps(deger, ensure_ascii=False, sort_keys=True), kaynak, kaynak_url, kanit, durum, simdi(),
                 simdi() if durum in ("onayli", "reddedildi") else None, karar_veren, json.dumps(sorunlar or [], ensure_ascii=False)))
            return int(cur.lastrowid)

    def karar(self, deger_id: int, durum: str, karar_veren: str) -> dict:
        if durum not in ("onayli", "reddedildi"):
            raise ValueError("durum onayli veya reddedildi olmalı")
        with self.islem() as db:
            r = db.execute("SELECT * FROM deger WHERE id=?", (deger_id,)).fetchone()
            if not r:
                raise ValueError("Kayıt yok: " + str(deger_id))
            if r["durum"] not in ("bekliyor", "aday"):
                raise ValueError(f"Kayıt zaten '{r['durum']}' durumunda; yeniden karar verilemez")
            if durum == "onayli":
                eski = db.execute("SELECT deger FROM deger WHERE seri=? AND yururluk=? AND durum='onayli'", (r["seri"], r["yururluk"])).fetchone()
                if eski and eski["deger"] != r["deger"]:
                    raise ValueError("Bu tarih için farklı bir onaylı değer var; onaylı değer değiştirilemez. Düzeltme gerekiyorsa yeni yürürlük tarihiyle girin.")
                if eski:  # aynı değer zaten onaylı: kaydı reddedilmiş say (tekrar)
                    durum = "reddedildi"
            db.execute("UPDATE deger SET durum=?, karar_zamani=?, karar_veren=? WHERE id=?", (durum, simdi(), karar_veren, deger_id))
            return _satir(db.execute("SELECT * FROM deger WHERE id=?", (deger_id,)).fetchone())

    def bekleyenler(self) -> list[dict]:
        return [_satir(x) for x in self.sorgu("SELECT * FROM deger WHERE durum='bekliyor' ORDER BY olusturma")]

    def kontrol_edildi(self, seri: str, kaynak: str) -> None:
        with self.islem() as db:
            db.execute("INSERT INTO kontrol(seri, son_kontrol, kaynak) VALUES(?,?,?) ON CONFLICT(seri) DO UPDATE SET son_kontrol=excluded.son_kontrol, kaynak=excluded.kaynak", (seri, simdi(), kaynak))

    def son_kontrol(self, seri: str) -> Optional[float]:
        r = self.sorgu("SELECT son_kontrol FROM kontrol WHERE seri=?", (seri,))
        return float(r[0]["son_kontrol"]) if r else None

    # ---------------- sağlık ve alarm ----------------
    def saglik_kaydet(self, kaynak: str, basari: bool, hata: str = "") -> int:
        with self.islem() as db:
            r = db.execute("SELECT ardisik_hata FROM saglik WHERE kaynak=?", (kaynak,)).fetchone()
            ard = 0 if basari else ((r["ardisik_hata"] if r else 0) + 1)
            db.execute(
                "INSERT INTO saglik(kaynak, son_deneme, son_basari, son_hata, ardisik_hata) VALUES(?,?,?,?,?) "
                "ON CONFLICT(kaynak) DO UPDATE SET son_deneme=excluded.son_deneme, "
                "son_basari=COALESCE(excluded.son_basari, saglik.son_basari), son_hata=excluded.son_hata, ardisik_hata=excluded.ardisik_hata",
                (kaynak, simdi(), simdi() if basari else None, "" if basari else hata[:500], ard))
            return ard

    def saglik(self) -> list[dict]:
        return [dict(x) for x in self.sorgu("SELECT * FROM saglik ORDER BY kaynak")]

    def alarm(self, anahtar: str, seviye: str, mesaj: str) -> Optional[int]:
        """Aynı anahtarla açık bir alarm varsa yenisini açmaz (mesajı günceller)."""
        with self.islem() as db:
            r = db.execute("SELECT id FROM alarm WHERE anahtar=? AND cozuldu IS NULL", (anahtar,)).fetchone()
            if r:
                db.execute("UPDATE alarm SET mesaj=?, seviye=? WHERE id=?", (mesaj, seviye, r["id"]))
                return None
            cur = db.execute("INSERT INTO alarm(anahtar, zaman, seviye, mesaj) VALUES(?,?,?,?)", (anahtar, simdi(), seviye, mesaj))
            return int(cur.lastrowid)

    def alarm_kapat(self, anahtar: str) -> None:
        with self.islem() as db:
            db.execute("UPDATE alarm SET cozuldu=? WHERE anahtar=? AND cozuldu IS NULL", (simdi(), anahtar))

    def acik_alarmlar(self) -> list[dict]:
        return [dict(x) for x in self.sorgu("SELECT * FROM alarm WHERE cozuldu IS NULL ORDER BY CASE seviye WHEN 'kritik' THEN 0 WHEN 'uyari' THEN 1 ELSE 2 END, zaman")]

    def bildirilmemis(self) -> list[dict]:
        return [dict(x) for x in self.sorgu("SELECT * FROM alarm WHERE cozuldu IS NULL AND bildirildi IS NULL ORDER BY zaman")]

    def bildirildi(self, ids: list[int]) -> None:
        with self.islem() as db:
            db.executemany("UPDATE alarm SET bildirildi=? WHERE id=?", [(simdi(), i) for i in ids])

    # ---------------- Resmî Gazete arşivi ----------------
    def rg_kaydet(self, tarih: str, mukerrer: int, sayi: Optional[str], fihrist: dict) -> None:
        with self.islem() as db:
            db.execute("INSERT OR REPLACE INTO rg_arsiv(tarih, mukerrer, sayi, fihrist, alindi) VALUES(?,?,?,?,?)",
                       (tarih, mukerrer, sayi, json.dumps(fihrist, ensure_ascii=False), simdi()))

    def rg_getir(self, tarih: str) -> list[dict]:
        return [dict(tarih=x["tarih"], mukerrer=x["mukerrer"], sayi=x["sayi"], fihrist=json.loads(x["fihrist"]), alindi=x["alindi"])
                for x in self.sorgu("SELECT * FROM rg_arsiv WHERE tarih=? ORDER BY mukerrer", (tarih,))]

    def rg_tespit_ekle(self, tarih: str, seri: str, baslik: str, url: str) -> bool:
        with self.islem() as db:
            cur = db.execute("INSERT OR IGNORE INTO rg_tespit(tarih, seri, baslik, url, olusturma) VALUES(?,?,?,?,?)", (tarih, seri, baslik, url, simdi()))
            return cur.rowcount > 0

    def rg_tespitler(self, durum: Optional[str] = None) -> list[dict]:
        if durum:
            return [dict(x) for x in self.sorgu("SELECT * FROM rg_tespit WHERE durum=? ORDER BY tarih DESC", (durum,))]
        return [dict(x) for x in self.sorgu("SELECT * FROM rg_tespit ORDER BY tarih DESC LIMIT 200")]

    def rg_tespit_durum(self, tespit_id: int, durum: str) -> None:
        with self.islem() as db:
            db.execute("UPDATE rg_tespit SET durum=? WHERE id=?", (durum, tespit_id))

    # ---------------- ayarlar ----------------
    def ayar_al(self, anahtar: str, varsayilan: Any = None) -> Any:
        r = self.sorgu("SELECT deger FROM ayar WHERE anahtar=?", (anahtar,))
        return json.loads(r[0]["deger"]) if r else varsayilan

    def ayar_yaz(self, anahtar: str, deger: Any) -> None:
        with self.islem() as db:
            db.execute("INSERT OR REPLACE INTO ayar(anahtar, deger) VALUES(?,?)", (anahtar, json.dumps(deger, ensure_ascii=False)))

    def yedekle(self, hedef: str) -> None:
        """Çalışırken tutarlı yedek (SQLite online backup)."""
        with self._kilit:
            dst = sqlite3.connect(hedef)
            try:
                self._db.backup(dst)
            finally:
                dst.close()


def _tarih_kontrol(s: str) -> None:
    try:
        date.fromisoformat(s)
    except ValueError:
        raise ValueError("Yürürlük tarihi YYYY-AA-GG olmalı: " + str(s)) from None


def _satir(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["deger"] = json.loads(d["deger"])
    d["sorunlar"] = json.loads(d.get("sorunlar") or "[]")
    return d
