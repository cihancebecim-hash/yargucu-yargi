"""Kaynak Motoru'nun MCP araçları (YARGUCU uygulaması ve bağımsız sürüm buradan okur)."""
from __future__ import annotations

import hmac
import os
from datetime import date, timedelta
from typing import Annotated, Any, Optional

from pydantic import Field

from .depo import Depo, bugun_tr
from .dogrulama import aday_isle
from .seriler import SERILER, TURETILEN
from .turet import TURETICILER
from . import bekci

_DEPO: Optional[Depo] = None


def depo() -> Depo:
    global _DEPO
    if _DEPO is None:
        _DEPO = Depo()
        from .tohum import tohumla
        tohumla(_DEPO)
    return _DEPO


def _yonetici(anahtar: str) -> None:
    beklenen = os.environ.get("YONETICI_ANAHTARI", "")
    if len(beklenen) < 16:
        raise PermissionError("Sunucuda YONETICI_ANAHTARI tanımlı değil (en az 16 karakter); onay işlemleri kapalı.")
    if not hmac.compare_digest(anahtar.encode(), beklenen.encode()):
        raise PermissionError("Yönetici anahtarı hatalı.")


def _tazelik(d: Depo, seri_id: str) -> dict:
    sorun = bekci.seri_durumu(d, seri_id)
    acik = [a["mesaj"] for a in d.acik_alarmlar()
            if seri_id in a["anahtar"].split(":") and a["seviye"] != "bilgi" and not a["anahtar"].startswith("eskime:")]
    return {"guncel": sorun is None and not acik, "uyarilar": ([sorun] if sorun else []) + acik[:3]}


def register(mcp) -> None:
    @mcp.tool(name="oran_getir", description="Bir oran veya tarifenin verilen tarihte yürürlükte olan, doğrulanmış değerini döndürür. Seriler: oran_katalogu. Türetilenler: kanuni_faiz, avans_faizi_3095 (ticari temerrüt). 'guncel' false ise değer eskimiş veya yeni yayım onay bekliyor olabilir; uyarıları kullanıcıya gösterin.")
    async def oran_getir(
        seri: Annotated[str, Field(description="Seri kimliği, ör. tcmb_reeskont, kanuni_faiz, harc_tarifesi")],
        tarih: Annotated[Optional[str], Field(description="YYYY-AA-GG; boşsa bugün")] = None,
    ) -> dict:
        d = depo()
        t = tarih or bugun_tr().isoformat()
        gun = date.fromisoformat(t)
        if seri in TURETICILER:
            r = TURETICILER[seri](d, gun)
            kaynak_seri = "tcmb_avans" if seri == "avans_faizi_3095" else "tcmb_reeskont"
            taz = _tazelik(d, kaynak_seri)
            ref = gun.replace(month=1, day=1) - timedelta(days=1)
            if gun.month >= 7:
                ref = gun.replace(month=6, day=30)
            if ref > bugun_tr():
                taz["guncel"] = False
                taz["uyarilar"].append(f"Hesap {ref:%d.%m.%Y} tarihindeki TCMB oranına bağlı; bu tarih henüz gelmedi, oran değişebilir.")
            return {"seri": seri, "tarih": t, "deger": r["oran"], "dayanak": r["dayanak"], "turetilen": True, **taz}
        if seri not in SERILER:
            raise ValueError("Bilinmeyen seri: " + seri)
        r = d.onayli(seri, t)
        s = SERILER[seri]
        if not r:
            return {"seri": seri, "tarih": t, "deger": None, "uyari": f"{t} için doğrulanmış {s.ad} değeri yok"}
        return {"seri": seri, "ad": s.ad, "birim": s.birim, "tarih": t, "deger": r["deger"], "yururluk": r["yururluk"],
                "kaynak": r["kaynak"], "kaynak_url": r["kaynak_url"], "onaylayan": r["karar_veren"], **_tazelik(d, seri)}

    @mcp.tool(name="oran_serisi", description="Bir serinin doğrulanmış tüm değişiklik noktalarını (yürürlük tarihi ve değer) döndürür.")
    async def oran_serisi(
        seri: Annotated[str, Field(description="Seri kimliği")],
        baslangic: Annotated[Optional[str], Field(description="YYYY-AA-GG; bu tarihten itibaren")] = None,
    ) -> dict:
        d = depo()
        if seri not in SERILER:
            raise ValueError("Bilinmeyen seri: " + seri)
        return {"seri": seri, "degerler": [{"yururluk": x["yururluk"], "deger": x["deger"], "kaynak": x["kaynak"]} for x in d.seri(seri, baslangic)], **_tazelik(d, seri)}

    @mcp.tool(name="oran_katalogu", description="Takip edilen tüm oran ve tarifeler: son doğrulanmış değer, yürürlük tarihi, kaynak ve güncellik durumu.")
    async def oran_katalogu() -> dict:
        d = depo()
        out = []
        for s in SERILER.values():
            son = d.son_onayli(s.id)
            out.append({"seri": s.id, "ad": s.ad, "birim": s.birim, "dayanak": s.dayanak, "kaynak": s.kaynak_adi,
                        "son_yururluk": son["yururluk"] if son else None,
                        "son_deger": son["deger"] if son and s.tur == "sayi" else ("tablo" if son else None),
                        **_tazelik(d, s.id)})
        return {"seriler": out, "turetilen": TURETILEN}

    @mcp.tool(name="kaynak_durumu", description="Kaynak Motoru'nun sağlık durumu: açık alarmlar, kaynakların son başarılı okunma zamanı, onay bekleyen değerler ve yeni yayımlanan tarifeler.")
    async def kaynak_durumu() -> dict:
        d = depo()
        return {"alarmlar": [{"seviye": a["seviye"], "mesaj": a["mesaj"], "zaman": a["zaman"]} for a in d.acik_alarmlar()],
                "kaynaklar": d.saglik(), "onay_bekleyen": len(d.bekleyenler()),
                "rg_tespitleri": [x for x in d.rg_tespitler("yeni")][:20]}

    @mcp.tool(name="oran_onay_listesi", description="Onay bekleyen değerler (yönetici).")
    async def oran_onay_listesi(yonetici_anahtari: Annotated[str, Field(description="Yönetici anahtarı")]) -> dict:
        _yonetici(yonetici_anahtari)
        d = depo()
        out = []
        for x in d.bekleyenler():
            onceki = d.onayli(x["seri"], x["yururluk"])
            out.append({**x, "ad": SERILER[x["seri"]].ad, "onceki_deger": onceki["deger"] if onceki else None})
        return {"bekleyenler": out}

    @mcp.tool(name="oran_karar", description="Onay bekleyen bir değeri onaylar veya reddeder (yönetici). Onaylanan değer bir daha değiştirilemez.")
    async def oran_karar(
        yonetici_anahtari: Annotated[str, Field(description="Yönetici anahtarı")],
        kayit_id: Annotated[int, Field(description="oran_onay_listesi'ndeki id")],
        karar: Annotated[str, Field(description="onayla veya reddet")],
        onaylayan: Annotated[str, Field(description="Onaylayan kişinin adı")],
    ) -> dict:
        _yonetici(yonetici_anahtari)
        if karar not in ("onayla", "reddet"):
            raise ValueError("karar 'onayla' veya 'reddet' olmalı")
        d = depo()
        r = d.karar(kayit_id, "onayli" if karar == "onayla" else "reddedildi", onaylayan)
        d.alarm_kapat(f"onay:{r['seri']}:{r['yururluk']}")
        d.alarm_kapat(f"tek:{r['seri']}:{r['yururluk']}")
        if karar == "onayla":
            d.alarm_kapat(f"cakisma:{r['seri']}:{r['yururluk']}")
            for t in d.rg_tespitler("yeni"):
                if t["seri"] == r["seri"]:
                    d.rg_tespit_durum(t["id"], "islendi")
                    d.alarm_kapat(f"rg:{t['seri']}:{t['url']}")
        return {"kayit": r}

    @mcp.tool(name="oran_elle_gir", description="Resmî kaynaktan okunan bir değeri elle girer (yönetici). Girilen değer doğrulamadan geçer ve ayrı bir adımda oran_karar ile onaylanmadıkça kullanılmaz.")
    async def oran_elle_gir(
        yonetici_anahtari: Annotated[str, Field(description="Yönetici anahtarı")],
        seri: Annotated[str, Field(description="Seri kimliği")],
        yururluk: Annotated[str, Field(description="YYYY-AA-GG")],
        deger: Annotated[Any, Field(description="Sayı veya tablo (JSON nesnesi)")],
        kaynak_url: Annotated[str, Field(description="Resmî kaynak bağlantısı (Resmî Gazete vb.)")],
        aciklama: Annotated[str, Field(description="Hangi tablodan/maddeden alındığı")] = "",
    ) -> dict:
        _yonetici(yonetici_anahtari)
        if not kaynak_url.startswith("https://"):
            raise ValueError("Resmî kaynak bağlantısı (https://) zorunlu")
        d = depo()
        r = aday_isle(d, seri, yururluk, deger, "elle", kaynak_url, aciklama)
        if r["sonuc"] == "aday":  # elle girilen değer otomatik onaylanmaz
            with d.islem() as db:
                db.execute("UPDATE deger SET durum='bekliyor' WHERE id=?", (r["id"],))
            r["sonuc"] = "bekliyor"
        return r

    @mcp.tool(name="rg_arsiv", description="Kaynak Motoru'nun arşivlediği Resmî Gazete fihristi (verilen gün).")
    async def rg_arsiv(tarih: Annotated[Optional[str], Field(description="YYYY-AA-GG; boşsa bugün")] = None) -> dict:
        d = depo()
        t = tarih or bugun_tr().isoformat()
        return {"tarih": t, "sayilar": d.rg_getir(t)}
