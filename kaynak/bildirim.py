"""Alarmların yöneticiye iletilmesi: e-posta (SMTP) ve/veya web kancası.

Ortam değişkenleri:
  SMTP_SUNUCU, SMTP_PORT (587), SMTP_KULLANICI, SMTP_SIFRE, BILDIRIM_EPOSTA (alıcı)
  BILDIRIM_WEBHOOK : alarmlar JSON olarak POST edilir (ör. kendi ntfy sunucunuz)
Hiçbiri tanımlı değilse alarmlar yalnız MCP aracıyla (kaynak_durumu) ve uygulamada görünür.
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
from email.message import EmailMessage

import httpx

from .depo import Depo

SEVIYE = {"kritik": "KRİTİK", "uyari": "Uyarı", "bilgi": "Bilgi"}


def gonder(depo: Depo) -> dict:
    yeni = depo.bildirilmemis()
    if not yeni:
        return {"gonderilen": 0}
    metin = "\n\n".join(f"[{SEVIYE.get(a['seviye'], a['seviye'])}] {a['mesaj']}" for a in yeni)
    kanallar, hatalar = [], []
    if os.environ.get("SMTP_SUNUCU") and os.environ.get("BILDIRIM_EPOSTA"):
        try:
            m = EmailMessage()
            kritik = any(a["seviye"] == "kritik" for a in yeni)
            m["Subject"] = f"YARGUCU Kaynak Motoru: {len(yeni)} {'KRİTİK ' if kritik else ''}bildirim"
            m["From"] = os.environ.get("SMTP_KULLANICI", "")
            m["To"] = os.environ["BILDIRIM_EPOSTA"]
            m.set_content(metin + "\n\nAyrıntı: YARGUCU → Ayarlar → Kaynak durumu")
            with smtplib.SMTP(os.environ["SMTP_SUNUCU"], int(os.environ.get("SMTP_PORT", "587")), timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                if os.environ.get("SMTP_KULLANICI"):
                    s.login(os.environ["SMTP_KULLANICI"], os.environ.get("SMTP_SIFRE", ""))
                s.send_message(m)
            kanallar.append("eposta")
        except Exception as e:
            hatalar.append(f"eposta: {type(e).__name__}: {e}")
    if os.environ.get("BILDIRIM_WEBHOOK"):
        try:
            r = httpx.post(os.environ["BILDIRIM_WEBHOOK"], content=json.dumps({"bildirimler": yeni}, ensure_ascii=False).encode(),
                           headers={"Content-Type": "application/json"}, timeout=20)
            r.raise_for_status()
            kanallar.append("webhook")
        except Exception as e:
            hatalar.append(f"webhook: {type(e).__name__}: {e}")
    if kanallar:
        depo.bildirildi([a["id"] for a in yeni])
    return {"gonderilen": len(yeni) if kanallar else 0, "kanallar": kanallar, "hatalar": hatalar}
