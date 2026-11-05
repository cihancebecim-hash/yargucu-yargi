"""Resmî Gazete belgesinin yayımlandığı biçimle (paragraf paragraf) gösterilmesi."""
import asyncio

import pytest

import resmi_gazete as rgm

# Word'den çıkan Resmî Gazete sayfalarındaki gibi kapanmamış <p> etiketleri (5.11.2026/33421 örneği)
BOZUK = ("<html><body><p class=MsoNormal><table><tr><td>5 Kasım 2026 PERŞEMBE</td><td><b>Resmî Gazete</b></td><td>Sayı : 33421</td></tr></table>"
         "<p align=center><b>YÖNETMELİK</b><p>Türk Mühendis ve Mimar Odaları Birliği Harita ve Kadastro Mühendisleri Odasından:"
         "<p align=center><b>BİRİNCİ BÖLÜM</b><p align=center><b>Başlangıç Hükümleri</b><p><b>Amaç</b>"
         "<p><b>MADDE 1-</b> (1) Bu Yönetmeliğin amacı; eğitim merkezinin çalışma esaslarını düzenlemektir.<p><b>Kapsam</b>"
         "<p><b>MADDE 2-</b> (1) Bu Yönetmelik; merkezin tüm faaliyetlerini kapsar.</body></html>")


def bloklar(parser, monkeypatch):
    monkeypatch.setattr(rgm, "_parser", lambda: parser)
    return asyncio.run(rgm._html_blocks(None, BOZUK, "https://www.resmigazete.gov.tr/eskiler/2026/11/20261105-6.htm", images=False))


@pytest.mark.parametrize("parser", ["html5lib", "html.parser"])
def test_paragraflar_birbirine_girmez(parser, monkeypatch):
    if parser == "html5lib":
        pytest.importorskip("html5lib")
    B = bloklar(parser, monkeypatch)
    ps = [b["h"] for b in B if b["t"] == "p"]
    assert any(b["t"] == "table" and len(b["rows"][0]) == 3 for b in B), B  # künye tablosu ayrı
    for beklenen in ["<b>YÖNETMELİK</b>", "<b>BİRİNCİ BÖLÜM</b>", "<b>Amaç</b>", "<b>Kapsam</b>"]:
        assert beklenen in ps, (beklenen, ps)
    madde1 = next(p for p in ps if p.startswith("<b>MADDE 1-</b>"))
    assert "Kapsam" not in madde1 and "MADDE 2" not in madde1
    assert not any("YÖNETMELİK" in p and "MADDE 1" in p for p in ps)
    hiza = {b["h"]: b["a"] for b in B if b["t"] == "p"}
    assert hiza["<b>YÖNETMELİK</b>"] == "center" and hiza["<b>BİRİNCİ BÖLÜM</b>"] == "center"


def test_duzgun_html_degismez(monkeypatch):
    html = "<html><body><p align=center><b>KARAR</b></p><p>Birinci paragraf.</p><p>İkinci <i>paragraf</i>.</p></body></html>"
    for parser in ("html5lib", "html.parser"):
        monkeypatch.setattr(rgm, "_parser", lambda p=parser: p)
        B = asyncio.run(rgm._html_blocks(None, html, "https://www.resmigazete.gov.tr/x.htm", images=False))
        assert [b["h"] for b in B] == ["<b>KARAR</b>", "Birinci paragraf.", "İkinci <i>paragraf</i>."]


# 5.11.2026/33421 sayfasının iskeleti: tüm sayfa tek hücreli bir düzen tablosunda, künye ise iç tabloda
DUZEN = ("<html><body><table width=642><tr><td>"
         "<table width=100%><tr><td>5 Kasım 2026 PERŞEMBE</td><td align=center><b>Resmî Gazete</b></td><td align=right>Sayı : 33421</td></tr></table>"
         "<table width=100%><tr><td align=center><b>YÖNETMELİK</b></td></tr></table>"
         "<table width=100%><tr><td>"
         "<p>Türk Mühendis ve Mimar Odaları Birliği Harita ve<br>Kadastro Mühendisleri Odasından:</p>"
         "<p align=center><b>TÜRK MÜHENDİS VE MİMAR ODALARI BİRLİĞİ HARİTA VE KADASTRO MÜHENDİSLERİ ODASI EĞİTİM VE BELGELENDİRME MERKEZİ YÖNETMELİĞİ</b></p>"
         "<p align=center><b>BİRİNCİ BÖLÜM</b></p><p align=center><b>Başlangıç Hükümleri</b></p>"
         "<p><b>Amaç</b></p><p><b>MADDE 1-</b>(1) Bu Yönetmeliğin amacı; usul ve esasları düzenlemektir.</p>"
         "<p><b>Kapsam</b></p><p><b>MADDE 2-</b>(1) Bu Yönetmelik; süreçlerini kapsar.</p>"
         "</td></tr></table></td></tr></table></body></html>")


@pytest.mark.parametrize("parser", ["html5lib", "html.parser"])
def test_duzen_tablosu_paragraflara_ayrilir(parser, monkeypatch):
    if parser == "html5lib":
        pytest.importorskip("html5lib")
    monkeypatch.setattr(rgm, "_parser", lambda: parser)
    B = asyncio.run(rgm._html_blocks(None, DUZEN, "https://www.resmigazete.gov.tr/eskiler/2026/11/20261105-2.htm", images=False))
    tablolar = [b for b in B if b["t"] == "table"]
    assert tablolar and tablolar[0]["rows"] == [["5 Kasım 2026 PERŞEMBE", "<b>Resmî Gazete</b>", "Sayı : 33421"]], B
    assert all(len(" ".join(c for r in t["rows"] for c in r)) < 200 for t in tablolar)  # hiçbir tablo hücresinde belge gövdesi yok
    ps = [b["h"] for b in B if b["t"] == "p"]
    for beklenen in ["<b>YÖNETMELİK</b>", "<b>BİRİNCİ BÖLÜM</b>", "<b>Amaç</b>", "<b>Kapsam</b>"]:
        assert beklenen in ps, (beklenen, ps)
    assert any(p.startswith("<b>MADDE 1-</b>") and "Kapsam" not in p for p in ps)


def test_veri_tablosu_tablo_kalir(monkeypatch):
    """Harç tarifesi gibi gerçek tablolar (hücrelerinde birden çok paragraf olsa bile) tablo olarak kalır."""
    html = ("<html><body><table><tr><td><p>1.</p><p>Başvurma harcı</p></td><td><p>Sulh</p></td><td><p>335,20</p></td></tr>"
            "<tr><td><p>2.</p></td><td><p>Asliye</p></td><td><p>732,00</p></td></tr></table></body></html>")
    for parser in ("html5lib", "html.parser"):
        monkeypatch.setattr(rgm, "_parser", lambda p=parser: p)
        B = asyncio.run(rgm._html_blocks(None, html, "https://www.resmigazete.gov.tr/x.htm", images=False))
        assert [b["t"] for b in B] == ["table"] and len(B[0]["rows"]) == 2 and B[0]["rows"][1][2] == "732,00" and B[0]["rows"][0][0] == "1.<br>Başvurma harcı", B
