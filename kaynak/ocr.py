"""Taranmış PDF'ler için sunucuda yazı tanıma (Tesseract, Türkçe dil paketi).

Dış bir servise belge gönderilmez. Kurulum: apt install tesseract-ocr tesseract-ocr-tur
"""
from __future__ import annotations

import io
import shutil


def hazir_mi() -> bool:
    if not shutil.which("tesseract"):
        return False
    try:
        import pytesseract
        return "tur" in pytesseract.get_languages(config="")
    except Exception:
        return False


def pdf_metni(veri: bytes, en_cok_sayfa: int = 30, olcek: float = 300 / 72) -> str:
    """PDF sayfalarını 300 dpi görüntüye çevirip Türkçe OCR uygular."""
    import pypdfium2 as pdfium
    import pytesseract

    pdf = pdfium.PdfDocument(io.BytesIO(veri))
    parcalar = []
    try:
        for i in range(min(len(pdf), en_cok_sayfa)):
            sayfa = pdf[i]
            img = sayfa.render(scale=olcek).to_pil().convert("L")
            parcalar.append(f"[s. {i + 1}]\n" + pytesseract.image_to_string(img, lang="tur", config="--psm 6"))
    finally:
        pdf.close()
    return "\n".join(parcalar)
