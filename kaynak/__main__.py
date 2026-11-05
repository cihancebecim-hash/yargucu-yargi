"""Komut satırı: python -m kaynak <komut>

  tohumla        Boş depoya YARGUCU'nun doğrulanmış tablolarını yükler
  gunluk         Resmî Gazete + TCMB + EVDS + bekçi + bildirim (zamanlayıcı bunu çalıştırır)
  rg [TARİH]     Yalnız Resmî Gazete
  tcmb           Yalnız TCMB oran sayfası
  evds           Yalnız EVDS (kalibrasyon dahil)
  izle           Yalnız sayfa değişikliği izleyicisi
  bekci          Yalnız bekçi ve bildirim
  durum          Açık alarmlar ve onay bekleyenler
  bekleyenler    Onay bekleyen değerler (önceki değerle birlikte)
  onayla ID AD   Bekleyen değeri onaylar (AD: onaylayan kişi)
  reddet ID AD   Bekleyen değeri reddeder
  elle SERİ TARİH DEĞER URL [AÇIKLAMA]
                 Resmî kaynaktan okunan değeri girer (ayrıca 'onayla' gerekir)
  yedek HEDEF    Veritabanının tutarlı yedeği
"""
from __future__ import annotations

import json
import sys
from datetime import date

from . import bekci, bildirim, gorevler
from .depo import Depo
from .tohum import tohumla


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "yardim"):
        print(__doc__)
        return 0
    d = Depo()
    k = argv[0]
    if k == "tohumla":
        print(json.dumps({"eklenen": tohumla(d)}, ensure_ascii=False))
        return 0
    tohumla(d)
    if k == "gunluk":
        r = gorevler.calistir(gorevler.gunluk(d))
    elif k == "rg":
        r = gorevler.calistir(gorevler.rg(d, date.fromisoformat(argv[1]) if len(argv) > 1 else None))
    elif k == "tcmb":
        r = gorevler.calistir(gorevler.tcmb(d))
    elif k == "evds":
        r = gorevler.calistir(gorevler.evds_hepsi(d))
    elif k == "izle":
        from . import izleyici
        r = gorevler.calistir(izleyici.calistir(d))
    elif k == "bekci":
        r = {"bekci": bekci.calistir(d), "bildirim": bildirim.gonder(d)}
    elif k == "durum":
        r = {"alarmlar": d.acik_alarmlar(), "bekleyenler": d.bekleyenler(), "kaynaklar": d.saglik()}
    elif k == "bekleyenler":
        from .seriler import SERILER
        r = [{**x, "ad": SERILER[x["seri"]].ad, "onceki": (d.onayli(x["seri"], x["yururluk"]) or {}).get("deger")} for x in d.bekleyenler()]
    elif k in ("onayla", "reddet"):
        from .mcp_araclari import karar_ver
        r = karar_ver(d, int(argv[1]), k, " ".join(argv[2:]))
    elif k == "elle":
        from .mcp_araclari import elle_gir
        deger = argv[3]
        try:
            deger = json.loads(deger)
        except ValueError:
            pass
        r = elle_gir(d, argv[1], argv[2], deger, argv[4], " ".join(argv[5:]))
    elif k == "yedek":
        d.yedekle(argv[1])
        r = {"yedek": argv[1]}
    else:
        print("Bilinmeyen komut: " + k + "\n" + __doc__)
        return 2
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    kritik = any(a["seviye"] == "kritik" for a in d.acik_alarmlar())
    return 1 if kritik else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
