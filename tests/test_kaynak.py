"""Kaynak Motoru testleri. Ağ gerektirmez; dış kaynaklar örnek veriyle taklit edilir.

Çalıştırma: python -m pytest -q tests
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

from kaynak import bekci, gorevler
from kaynak.depo import Depo
from kaynak.dogrulama import aday_isle, tek_kaynak_adaylarini_isle
from kaynak.kaynaklar import evds, tcmb_sayfa
from kaynak.seriler import SERILER, rg_tani
from kaynak.tohum import tohumla
from kaynak.turet import kanuni_faiz, ticari_temerrut

VERI = Path(__file__).parent / "veri"


@pytest.fixture()
def depo():
    d = Depo(":memory:")
    tohumla(d)
    return d


def run(c):
    return asyncio.run(c)


# ---------------- tohum ----------------
TOHUMSUZ = {"arabuluculuk"}  # uygulamada henüz gömülü değil; ilk değer yayımdan elle girilir


def test_tohum_tum_seriler_dolu(depo):
    for sid in set(SERILER) - TOHUMSUZ:
        assert depo.son_onayli(sid), f"{sid} için tohum verisi yok"


def test_tohum_ikinci_kez_calismaz(depo):
    assert tohumla(depo) == 0


def test_tohum_degerleri_uygulama_ile_ayni(depo):
    t = json.loads((Path(__file__).parent.parent / "kaynak" / "tohum.json").read_text(encoding="utf-8"))
    for tarih, r, a in t["TCMB_RA"]:
        assert depo.onayli("tcmb_reeskont", tarih)["deger"] == r
        assert depo.onayli("tcmb_avans", tarih)["deger"] == a
    for tarih, v in t["ASGARI"]:
        assert depo.onayli("asgari_ucret_brut", tarih)["deger"] == v
    assert depo.son_onayli("kidem_tavan")["deger"] == t["KIDEM_TAVAN"][-1][1]


# ---------------- uygulama ile birebir aynı faiz ----------------
def test_kanuni_ve_ticari_faiz_uygulama_ile_birebir(depo):
    beklenen = json.loads((VERI / "uygulama_faiz_beklenen.json").read_text())
    assert len(beklenen) > 800
    for t, k, c in beklenen:
        g = date.fromisoformat(t)
        assert kanuni_faiz(depo, g)["oran"] == k, t
        assert ticari_temerrut(depo, g)["oran"] == c, t


# ---------------- depo ----------------
def test_onayli_deger_degistirilemez(depo):
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        depo.ekle("tcmb_reeskont", "2025-12-20", 99.0, "test", "onayli")


def test_karar_bir_kez_verilir(depo):
    r = aday_isle(depo, "asgari_ucret_brut", "2027-01-01", 40000.0, "elle")
    assert r["sonuc"] == "bekliyor"
    depo.karar(r["id"], "onayli", "test")
    with pytest.raises(ValueError):
        depo.karar(r["id"], "reddedildi", "test")
    assert depo.onayli("asgari_ucret_brut", "2027-02-01")["deger"] == 40000.0


# ---------------- doğrulama ----------------
def test_ayni_deger_zaten_onayli(depo):
    assert aday_isle(depo, "tcmb_reeskont", "2025-12-20", 38.75, "tcmb_sayfa")["sonuc"] == "zaten_onayli"


def test_cakisma_onayliyi_degistirmez_ve_kritik_alarm(depo):
    r = aday_isle(depo, "tcmb_reeskont", "2025-12-20", 37.0, "tcmb_sayfa")
    assert r["sonuc"] == "cakisma"
    assert depo.onayli("tcmb_reeskont", "2025-12-20")["deger"] == 38.75
    assert any(a["seviye"] == "kritik" for a in depo.acik_alarmlar())


def test_iki_kaynak_uyumlu_ise_otomatik_onay(depo):
    assert aday_isle(depo, "tcmb_reeskont", "2026-12-15", 36.75, "tcmb_sayfa")["sonuc"] == "aday"
    assert depo.onayli("tcmb_reeskont", "2026-12-20")["deger"] == 38.75  # aday hesaba girmez
    assert aday_isle(depo, "tcmb_reeskont", "2026-12-15", 36.75, "evds")["sonuc"] == "onaylandi"
    r = depo.onayli("tcmb_reeskont", "2026-12-20")
    assert r["deger"] == 36.75 and r["kaynak"] == "tcmb_sayfa+evds"


def test_iki_kaynak_uyumsuz_ise_hicbiri_uygulanmaz(depo):
    aday_isle(depo, "tcmb_reeskont", "2026-12-15", 36.75, "tcmb_sayfa")
    r = aday_isle(depo, "tcmb_reeskont", "2026-12-15", 36.5, "evds")
    assert r["sonuc"] == "cakisma"
    assert depo.onayli("tcmb_reeskont", "2026-12-20")["deger"] == 38.75
    assert len(depo.bekleyenler()) == 2


def test_makul_olmayan_degisim_onaya_duser(depo):
    r = aday_isle(depo, "tcmb_reeskont", "2026-12-15", 3.875, "tcmb_sayfa")  # ondalık kayması
    assert r["sonuc"] == "bekliyor" and r["sorunlar"]
    r2 = aday_isle(depo, "tcmb_reeskont", "2026-12-15", 3.875, "evds")
    assert depo.onayli("tcmb_reeskont", "2026-12-20")["deger"] == 38.75


def test_tutar_dusmesi_suphelidir(depo):
    r = aday_isle(depo, "asgari_ucret_brut", "2027-01-01", 3303.0, "elle")
    assert any("düşmüş" in s or "oransal" in s for s in r["sorunlar"])


def test_gecmise_donuk_kayit_onaya_duser(depo):
    r = aday_isle(depo, "tcmb_reeskont", "2024-07-01", 50.75, "tcmb_sayfa")
    assert r["sonuc"] == "bekliyor"


def test_bicimsiz_deger_reddedilir(depo):
    assert aday_isle(depo, "tcmb_reeskont", "2026-12-15", "38,75", "tcmb_sayfa")["sonuc"] == "reddedildi"
    assert any(a["seviye"] == "kritik" for a in depo.acik_alarmlar())


def test_elle_seriler_her_zaman_onay_bekler(depo):
    r = aday_isle(depo, "gecikme_zammi", "2027-01-01", 3.5, "rg_metin")
    assert r["sonuc"] == "bekliyor"
    assert depo.onayli("gecikme_zammi", "2027-02-01")["deger"] == 3.7


def test_tek_kaynak_adayi_bekleyince_onaya_duser(depo):
    aday_isle(depo, "mevduat_ort1ay", "2026-10-23", 42.5, "evds")
    with depo.islem() as db:
        db.execute("UPDATE deger SET olusturma=? WHERE durum='aday'", (time.time() - 49 * 3600,))
    assert tek_kaynak_adaylarini_isle(depo) == 1
    assert depo.bekleyenler()[0]["seri"] == "mevduat_ort1ay"


# ---------------- TCMB sayfası ----------------
TCMB_HTML = """<html><body><table>
<tr><th>Tarih</th><th>Reeskont İşlemleri (%)</th><th>Avans İşlemleri (%)</th></tr>
<tr><td>20.12.2025</td><td>38,75</td><td>39,75</td></tr>
<tr><td>17.09.2025</td><td>41,25</td><td>42,25</td></tr>
<tr><td>08.03.2025</td><td>43,25</td><td>44,25</td></tr>
<tr><td>28.12.2024</td><td>48,25</td><td>49,25</td></tr>
{yeni}
</table></body></html>"""


def test_tcmb_sayfasi_cozumlenir():
    s = tcmb_sayfa.cozumle(TCMB_HTML.format(yeni=""))
    assert (date(2025, 12, 20), 38.75, 39.75) in s and len(s) == 4


def test_tcmb_kalibrasyon_gecer_ve_yeni_oran_aday_olur(depo):
    satirlar = tcmb_sayfa.cozumle(TCMB_HTML.format(yeni="<tr><td>15.12.2026</td><td>36,75</td><td>37,75</td></tr>"))
    r = run(gorevler.tcmb(depo, satirlar))
    assert r["kalibrasyon"] is True
    assert depo.onayli("tcmb_reeskont", "2026-12-20")["deger"] == 38.75  # tek kaynak: henüz uygulanmaz
    assert aday_isle(depo, "tcmb_reeskont", "2026-12-15", 36.75, "evds")["sonuc"] == "onaylandi"


def test_tcmb_sayfa_yapisi_bozuksa_deger_alinmaz(depo):
    bozuk = TCMB_HTML.replace("38,75", "3,875").format(yeni="<tr><td>15.12.2026</td><td>36,75</td><td>37,75</td></tr>")
    r = run(gorevler.tcmb(depo, tcmb_sayfa.cozumle(bozuk)))
    assert r["kalibrasyon"] is False
    assert not depo.ayni_tarihli("tcmb_reeskont", "2026-12-15")
    assert any(a["anahtar"] == "kalibrasyon:tcmb_sayfa" for a in depo.acik_alarmlar())


# ---------------- EVDS ----------------
def test_evds_cozumle_ve_donustur():
    j = json.dumps({"totalCount": 3, "items": [
        {"Tarih": "2026-8", "TP_FG_J0": "100.00"}, {"Tarih": "2026-9", "TP_FG_J0": "102.50"}, {"Tarih": "2026-10", "TP_FG_J0": None}]})
    n = evds.cozumle(j, "TP.FG.J0")
    assert n == [(date(2026, 8, 1), 100.0), (date(2026, 9, 1), 102.5)]
    assert evds.donustur(n, "aylik_degisim") == [(date(2026, 9, 1), 2.5)]


def test_evds_basamakli_degisim_noktalari():
    n = [(date(2026, 1, 1), 38.75), (date(2026, 1, 2), 38.75), (date(2026, 3, 5), 37.0), (date(2026, 3, 6), 37.0)]
    assert evds.degisim_noktalari(n) == [(date(2026, 1, 1), 38.75), (date(2026, 3, 5), 37.0)]


def _tufe_endeksi(depo, bas="2023-01-01"):
    """Tohumdaki aylık TÜFE değişimlerinden, EVDS'nin vereceği endeks düzeyini kurar."""
    seri = depo.seri("tufe_aylik", bas)
    v, out = 1000.0, []
    onceki = date.fromisoformat(seri[0]["yururluk"]) - timedelta(days=1)
    out.append((onceki.replace(day=1), v))
    for x in seri:
        v = v * (1 + x["deger"] / 100)
        out.append((date.fromisoformat(x["yururluk"]), v))
    return out


def test_evds_kalibrasyon_gecerse_yeni_ay_aday_olur(depo):
    endeks = _tufe_endeksi(depo)
    son = endeks[-1]
    yeni_ay = (son[0] + timedelta(days=32)).replace(day=1)
    endeks.append((yeni_ay, son[1] * 1.0210))
    r = run(gorevler.evds_seri(depo, "tufe_aylik", {"kod": "TP.FG.J0", "donusum": "aylik_degisim"}, veri=endeks))
    assert r["kalibrasyon"]["gecti"], r
    assert r["yeni"][0]["sonuc"] == "aday"


def test_evds_yanlis_kod_kalibrasyonda_duser(depo):
    endeks = [(t, v * (1.001 if i % 5 == 0 else 1)) for i, (t, v) in enumerate(_tufe_endeksi(depo))]
    r = run(gorevler.evds_seri(depo, "tufe_aylik", {"kod": "TP.YANLIS", "donusum": "aylik_degisim"}, veri=endeks))
    assert not r["kalibrasyon"]["gecti"]
    assert "yeni" not in r
    assert any("kalibrasyon:evds:tufe_aylik" == a["anahtar"] for a in depo.acik_alarmlar())


# ---------------- Resmî Gazete ----------------
@pytest.mark.parametrize("baslik,seri", [
    ("Harçlar Kanunu Genel Tebliği (Seri No: 99)", "harc_tarifesi"),
    ("Avukatlık Asgari Ücret Tarifesi", "aaut"),
    ("2027 Yılı Bilirkişilik Asgari Ücret Tarifesi", "bilirkisi"),
    ("Arabuluculuk Asgari Ücret Tarifesi", "arabuluculuk"),
    ("Hukuk Muhakemeleri Kanunu Gider Avansı Tarifesi", "gider_avansi"),
    ("Asgari Ücret Tespit Komisyonu Kararı", "asgari_ucret_brut"),
    ("6183 Sayılı Amme Alacaklarının Tahsil Usulü Hakkında Kanunun 51 inci Maddesinde Yer Alan Gecikme Zammı Oranının Belirlenmesine İlişkin Karar (Karar Sayısı: 12000)", "gecikme_zammi"),
    ("Tahsilat Genel Tebliği (Seri: C Sıra No: 10)", "tecil_faizi"),
])
def test_rg_baslik_tanima(baslik, seri):
    assert seri in rg_tani(baslik)


def test_rg_ilgisiz_baslik_tanimaz():
    assert rg_tani("Geçici Görevlendirme Yönetmeliğinde Değişiklik Yapılmasına Dair Yönetmelik") == []
    assert rg_tani("Özelleştirme İdaresi Başkanlığı ile İlgili Karar (Karar Sayısı: 11926)") == []


def test_gecikme_zammi_metinden_cikar():
    from kaynak.kaynaklar.rg import gecikme_zammi_cikar
    m = ("6183 sayılı Kanunun 51 inci maddesinin birinci fıkrasında yer alan gecikme zammı oranı, "
         "her ay için ayrı ayrı olmak üzere aylık %3,5 olarak belirlenmiştir. Bu Karar yayımı tarihini izleyen günden geçerli olmak üzere yürürlüğe girer.")
    assert gecikme_zammi_cikar(m)[0] == 3.5
    # aynı cümlede iki farklı oran: belirsiz, değer üretilmez
    assert gecikme_zammi_cikar("Gecikme zammı oranı aylık %3,5, 1/1/2027'den itibaren ise aylık %4 olarak uygulanır.") is None
    assert gecikme_zammi_cikar("Tecil faizi yıllık %39 olarak belirlenmiştir.") is None


def test_rg_toplayici_tarifeyi_yakalar(depo, monkeypatch):
    import resmi_gazete as rgm
    from kaynak.kaynaklar import rg as rgk
    html = ("<html><body><p><b>31 Aralık 2026</b> <b>Tarihli ve 33477 Sayılı Resmî Gazete</b></p>"
            "<p><b>YÜRÜTME VE İDARE BÖLÜMÜ</b></p><p><b>TEBLİĞLER</b></p>"
            "<p><a href='20261231-5.htm'>–– Harçlar Kanunu Genel Tebliği (Seri No: 99)</a></p>"
            "<p><a href='20261231-6.htm'>–– Gümrük Tebliği</a></p></body></html>")
    url = rgm.fihrist_url(date(2026, 12, 31))
    fihrist = rgm.parse_fihrist(html, url)
    fihrist.update(tarih="2026-12-31", mukerrer=0)

    async def sahte(client, d, mukerrer):
        return [fihrist] if d == date(2026, 12, 31) else []
    monkeypatch.setattr(rgm, "_fetch_all", sahte)
    r = run(rgk.topla(depo, date(2026, 12, 31)))
    assert r["tespit"] == [{"seri": "harc_tarifesi", "baslik": "Harçlar Kanunu Genel Tebliği (Seri No: 99)"}]
    assert depo.rg_getir("2026-12-31")[0]["sayi"] == "33477"
    assert any(a["anahtar"].startswith("rg:harc_tarifesi:") for a in depo.acik_alarmlar())
    run(rgk.topla(depo, date(2026, 12, 31)))  # ikinci çalışma yeni tespit açmaz
    assert len(depo.rg_tespitler()) == 1


# ---------------- bekçi ----------------
def test_bekci_eksik_aylik_veriyi_yakalar_ve_gelince_kapatir(depo):
    g = date(2026, 12, 10)  # Kasım 2026 TÜFE'si gelmiş olmalı
    assert bekci.seri_durumu(depo, "tufe_aylik", g)
    bekci.calistir(depo, g)
    assert any(a["anahtar"] == "eskime:tufe_aylik" for a in depo.acik_alarmlar())
    depo.ekle("tufe_aylik", "2026-11-01", 1.9, "evds", "onayli")
    bekci.calistir(depo, g)
    assert not any(a["anahtar"] == "eskime:tufe_aylik" for a in depo.acik_alarmlar())


def test_bekci_yillik_tarife_beklenir(depo):
    assert bekci.seri_durumu(depo, "harc_tarifesi", date(2026, 6, 1)) is None
    assert "henüz onaylanmadı" in bekci.seri_durumu(depo, "harc_tarifesi", date(2027, 1, 6))


def test_bekci_kaynak_hatasi_kritik_alarm(depo):
    depo.saglik_kaydet("tcmb_sayfa", False, "ağ hatası")
    depo.saglik_kaydet("tcmb_sayfa", False, "ağ hatası")
    bekci.calistir(depo, date(2026, 11, 5))
    assert any(a["anahtar"] == "saglik:tcmb_sayfa" and a["seviye"] == "kritik" for a in depo.acik_alarmlar())
    depo.saglik_kaydet("tcmb_sayfa", True)
    bekci.calistir(depo, date(2026, 11, 5))
    assert not any(a["anahtar"] == "saglik:tcmb_sayfa" for a in depo.acik_alarmlar())


def test_alarm_tekrar_acilmaz(depo):
    assert depo.alarm("x", "uyari", "a") is not None
    assert depo.alarm("x", "uyari", "b") is None
    assert len([a for a in depo.acik_alarmlar() if a["anahtar"] == "x"]) == 1


# ---------------- MCP araçları ----------------
def test_mcp_araclari(monkeypatch, tmp_path):
    from fastmcp import Client, FastMCP
    from kaynak import mcp_araclari
    monkeypatch.setenv("KAYNAK_DB", str(tmp_path / "k.db"))
    monkeypatch.setenv("YONETICI_ANAHTARI", "dogru-anahtar-1234567")
    monkeypatch.setenv("MCP_YONETIM", "1")
    mcp_araclari._DEPO = None
    app = FastMCP("test")
    mcp_araclari.register(app)

    async def go():
        async with Client(app) as c:
            r = (await c.call_tool("oran_getir", {"seri": "kanuni_faiz", "tarih": "2026-08-15"})).data
            assert r["deger"] == 31.0
            r = (await c.call_tool("oran_getir", {"seri": "tcmb_reeskont", "tarih": "2026-01-10"})).data
            assert r["deger"] == 38.75 and r["kaynak"] == "tohum"
            k = (await c.call_tool("oran_katalogu", {})).data
            assert len(k["seriler"]) == len(SERILER)
            with pytest.raises(Exception):
                await c.call_tool("oran_onay_listesi", {"yonetici_anahtari": "yanlis"})
            e = (await c.call_tool("oran_elle_gir", {"yonetici_anahtari": "dogru-anahtar-1234567", "seri": "ptt_tebligat",
                                                     "yururluk": "2027-01-01", "deger": 300, "kaynak_url": "https://www.ptt.gov.tr"})).data
            assert e["sonuc"] == "bekliyor"
            assert (await c.call_tool("oran_getir", {"seri": "ptt_tebligat", "tarih": "2027-02-01"})).data["deger"] == 265
            await c.call_tool("oran_karar", {"yonetici_anahtari": "dogru-anahtar-1234567", "kayit_id": e["id"], "karar": "onayla", "onaylayan": "Av. Test"})
            assert (await c.call_tool("oran_getir", {"seri": "ptt_tebligat", "tarih": "2027-02-01"})).data["deger"] == 300
    run(go())
    mcp_araclari._DEPO = None


def test_rg_fihrist_windows1254_cozumlenir():
    import httpx
    import resmi_gazete as rgm
    ham = (VERI / "rg_20261024_win1254.html").read_bytes()
    r = httpx.Response(200, content=ham, request=httpx.Request("GET", "https://www.resmigazete.gov.tr/eskiler/2026/10/20261024.htm"))
    f = rgm.parse_fihrist(rgm._decode(r), "https://www.resmigazete.gov.tr/eskiler/2026/10/20261024.htm")
    assert f["sayi"] == "33410"
    basliklar = [k["baslik"] for b in f["bolumler"] for k in b["kalemler"]]
    assert any(b.startswith("Özelleştirme İdaresi") for b in basliklar)


def test_komut_satiri_agsiz_calisir(tmp_path, monkeypatch, capsys):
    from kaynak.__main__ import main
    monkeypatch.setenv("KAYNAK_DB", str(tmp_path / "k.db"))
    assert main(["tohumla"]) == 0
    main(["durum"])
    out = capsys.readouterr().out
    assert '"alarmlar"' in out
    main(["yedek", str(tmp_path / "yedek.db")])
    assert (tmp_path / "yedek.db").stat().st_size > 10000


def test_izleyici_sayfa_degisince_alarm(depo, monkeypatch, tmp_path):
    import httpx
    from kaynak import izleyici
    ayar = tmp_path / "s.json"
    ayar.write_text(json.dumps({"sayfalar": [{"seri": "kk_azami", "url": "https://www.tcmb.gov.tr/kk"}]}), encoding="utf-8")
    monkeypatch.setattr(izleyici, "AYAR", ayar)
    icerik = {"v": "<html><body><table><tr><td>Akdi faiz aylık %3,25</td></tr></table>" + "x" * 60 + " Son güncelleme 10:41</body></html>"}
    tr = httpx.MockTransport(lambda req: httpx.Response(200, text=icerik["v"]))

    async def bir_kez():
        async with httpx.AsyncClient(transport=tr) as c:
            return await izleyici.calistir(depo, c)
    assert run(bir_kez()) == {"kk_azami": "ilk_kayit"}
    icerik["v"] = icerik["v"].replace("10:41", "11:02")  # yalnız saat değişti: gürültü
    assert run(bir_kez()) == {"kk_azami": "ayni"}
    icerik["v"] = icerik["v"].replace("3,25", "3,10")
    assert run(bir_kez()) == {"kk_azami": "degisti"}
    assert any(a["anahtar"].startswith("izleyici_degisti:kk_azami") for a in depo.acik_alarmlar())



def test_mcp_yonetim_varsayilan_kapali(monkeypatch, tmp_path):
    from kaynak import mcp_araclari
    monkeypatch.delenv("MCP_YONETIM", raising=False)
    monkeypatch.setenv("YONETICI_ANAHTARI", "dogru-anahtar-1234567")
    with pytest.raises(PermissionError):
        mcp_araclari._yonetici("dogru-anahtar-1234567")


def test_komut_satiri_elle_giris_ve_onay(tmp_path, monkeypatch, capsys):
    from kaynak.__main__ import main
    monkeypatch.setenv("KAYNAK_DB", str(tmp_path / "k.db"))
    main(["elle", "vekalet_pulu", "2027-01-01", "190", "https://www.barobirlik.org.tr", "TBB duyurusu"])
    out = json.loads(capsys.readouterr().out)
    assert out["sonuc"] == "bekliyor"
    with pytest.raises(ValueError):
        main(["onayla", str(out["id"])])  # onaylayan adı zorunlu
    main(["onayla", str(out["id"]), "Av.", "Cihan", "CEBECİ"])
    capsys.readouterr()
    d = Depo(str(tmp_path / "k.db"))
    assert d.onayli("vekalet_pulu", "2027-03-01")["deger"] == 190
    assert d.onayli("vekalet_pulu", "2026-12-31")["deger"] == 164
