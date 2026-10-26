"""YARGUCU: Resmî Gazete araçları.

resmigazete.gov.tr'den fihristi ve düzenleme metinlerini doğrudan çeker
(aracı arama servisi ve kota yok). Yalnızca resmigazete.gov.tr adresleri açılır.
"""
from __future__ import annotations

import asyncio
import io
import re
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from pydantic import Field

BASE = "https://www.resmigazete.gov.tr"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9",
}
ITEM_RE = re.compile(r"/eskiler/\d{4}/\d{2}/\d{8}(?:M\d+)?-\d+\.(?:pdf|htm|html)$", re.I)
ILAN_RE = re.compile(r"ilanlar/", re.I)
HEAD_RE = re.compile(r"(\d{1,2}\s+\S+\s+\d{4})\s*(?:Tarihli\s+ve\s+)?(\d{4,6})\s*Sayılı", re.I)
GENERIC_ILAN = re.compile(r"yargı ilân|yargı ilan|artırma|eksiltme|ihale ilân|ihale ilan|çeşitli ilân|çeşitli ilan|döviz kur", re.I)


def tr_lower(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


def _today_tr() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=3)).date()


def _parse_date(s: Optional[str]) -> date:
    if not s:
        return _today_tr()
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError("Tarih YYYY-AA-GG veya GG.AA.YYYY biçiminde olmalı: " + s)


def fihrist_url(d: date, mukerrer: int = 0) -> str:
    y, m, dd = f"{d.year:04d}", f"{d.month:02d}", f"{d.day:02d}"
    return f"{BASE}/eskiler/{y}/{m}/{y}{m}{dd}{'M' + str(mukerrer) if mukerrer else ''}.htm"


def _check_url(u: str) -> str:
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not (p.hostname or "").lower().endswith("resmigazete.gov.tr"):
        raise ValueError("Yalnızca resmigazete.gov.tr adresleri açılabilir: " + u)
    return u.replace("http://", "https://", 1)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=HEADERS, timeout=httpx.Timeout(40.0, connect=15.0), follow_redirects=True, verify=True)


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    last = None
    for attempt in range(3):
        try:
            r = await client.get(url)
            if r.status_code in (429, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                await asyncio.sleep(2 * (attempt + 1))
                continue
            return r
        except httpx.HTTPError as e:  # ağ hatası: yeniden dene
            last = f"{type(e).__name__}: {e}"
            await asyncio.sleep(2 * (attempt + 1))
    raise RuntimeError("Resmî Gazete'ye ulaşılamadı (" + str(last) + ")")


def _decode(r: httpx.Response) -> str:
    """Resmî Gazete sayfaları çoğunlukla windows-1254; başlık bilgisi güvenilmez.
    Önce katı UTF-8 dene, olmazsa sayfadaki charset'i, o da yoksa windows-1254'ü kullan."""
    raw = r.content
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    m = re.search(rb"charset=['\"]?([\w-]+)", raw[:4000], re.I)
    enc = m.group(1).decode("ascii", "ignore").lower() if m else ""
    if not enc or enc in ("utf-8", "utf8", "iso-8859-1", "latin-1", "ascii"):
        enc = "windows-1254"
    try:
        return raw.decode(enc, errors="replace")
    except LookupError:
        return raw.decode("windows-1254", errors="replace")


def _is_heading(text: str) -> bool:
    t = text.strip(" \t\r\n:–-")
    if len(t) < 4 or len(t) > 90:
        return False
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 4:
        return False
    return all(not c.islower() for c in letters)


def parse_fihrist(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()
    text_all = " ".join(soup.get_text(" ").split())
    out: dict = {"url": url, "sayi": None, "tarih_metni": None, "pdf": None, "bolumler": []}
    m = HEAD_RE.search(text_all)
    if m:
        out["tarih_metni"], out["sayi"] = m.group(1), m.group(2)
    current = {"bolum": "", "ana": "", "kalemler": []}
    major = ""
    sections = [current]
    seen = set()
    for node in soup.descendants:
        name = getattr(node, "name", None)
        if name == "a":
            href = node.get("href") or ""
            full = urljoin(url, href)
            title = " ".join(node.get_text(" ").split()).lstrip("–—- ").strip()
            if re.search(r"/eskiler/\d{4}/\d{2}/\d{8}(?:M\d+)?\.pdf$", full, re.I):
                out["pdf"] = out["pdf"] or full.replace("http://", "https://", 1)
                continue
            is_item = bool(ITEM_RE.search(full))
            is_ilan = bool(ILAN_RE.search(full))
            if not title or not (is_item or is_ilan) or full in seen:
                continue
            seen.add(full)
            kn = re.search(r"\((?:Karar|Kararname)\s+Sayısı:\s*([\d/]+)\)", title, re.I)
            current["kalemler"].append({"baslik": title, "url": full.replace("http://", "https://", 1), "karar_sayisi": kn.group(1) if kn else None, "ilan": is_ilan})
        elif name is None and isinstance(node, str):
            if node.find_parent("a") is not None:
                continue
            t = " ".join(str(node).split())
            if not t or not _is_heading(t) or HEAD_RE.search(t):
                continue
            t = t.strip(" :")
            if tr_lower(t) in ("mevzuat", "resmî gazete", "resmi gazete"):
                continue
            if tr_lower(t).endswith("bölümü"):
                major = t
                current = {"bolum": t, "ana": t, "kalemler": []}
            else:
                current = {"bolum": t, "ana": major, "kalemler": []}
            sections.append(current)
    out["bolumler"] = [s for s in sections if s["kalemler"]]
    out["adet"] = sum(1 for s in out["bolumler"] for k in s["kalemler"] if not k["ilan"])
    return out


async def _fetch_fihrist(client, d: date, mukerrer: int = 0) -> Optional[dict]:
    url = fihrist_url(d, mukerrer)
    r = await _get(client, url)
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise RuntimeError(f"Resmî Gazete HTTP {r.status_code}: {url}")
    p = parse_fihrist(_decode(r), url)
    if not p["bolumler"]:
        return None
    p["tarih"] = d.isoformat()
    p["mukerrer"] = mukerrer
    return p


async def _fetch_all(client, d: date, mukerrer: bool) -> list[dict]:
    issues = []
    main = await _fetch_fihrist(client, d, 0)
    if main:
        issues.append(main)
    if mukerrer:
        for n in range(1, 4):
            try:
                p = await _fetch_fihrist(client, d, n)
            except Exception:
                p = None
            if not p:
                break
            issues.append(p)
    return issues


def _pdf_text(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader  # yargi-mcp bağımlılıklarıyla gelir

    reader = PdfReader(io.BytesIO(data))
    parts = []
    for i, page in enumerate(reader.pages):
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    return "\n".join(parts), len(reader.pages)


def _looks_garbage(text: str) -> bool:
    """Gömülü yazı tipi eşlemesi olmayan PDF'lerde pypdf denetim karakterleri üretir."""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return True
    letters = sum(1 for c in chars if c.isalnum())
    control = sum(1 for c in chars if ord(c) < 32 or 0xE000 <= ord(c) <= 0xF8FF or c == "\ufffd")
    return letters / len(chars) < 0.55 or control / len(chars) > 0.05


async def _doc_text(client, url: str) -> dict:
    url = _check_url(url)
    r = await _get(client, url)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}")
    ctype = r.headers.get("content-type", "").lower()
    if url.lower().endswith(".pdf") or "pdf" in ctype:
        text, pages = await asyncio.to_thread(_pdf_text, r.content)
        if len(text.strip()) < 40 or _looks_garbage(text):
            return {"url": url, "metin": "", "sayfa": pages, "taranmis": True, "uyari": "Taranmış PDF: metin katmanı yok veya okunamıyor; OCR gerekir"}
        return {"url": url, "metin": text, "sayfa": pages}
    soup = BeautifulSoup(_decode(r), "html.parser")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()
    text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
    return {"url": url, "metin": text, "sayfa": None}


def _snippets(text: str, word: str, limit: int = 2, width: int = 160) -> list[str]:
    low, w = tr_lower(text), tr_lower(word)
    out, start = [], 0
    while len(out) < limit:
        i = low.find(w, start)
        if i < 0:
            break
        a, b = max(0, i - width), min(len(text), i + len(word) + width)
        out.append(("…" if a else "") + " ".join(text[a:b].split()) + ("…" if b < len(text) else ""))
        start = i + len(w)
    return out


def register(mcp) -> None:
    @mcp.tool(
        name="resmi_gazete_fihrist",
        description=(
            "Resmî Gazete'nin belirli bir günkü fihristini resmigazete.gov.tr'den doğrudan getirir: sayı, tam nüsha PDF, "
            "bölümler (Yürütme ve İdare, Cumhurbaşkanı Kararları, Yönetmelikler, Tebliğler, Kurul Kararları, Yargı, İlan) ve "
            "her düzenlemenin başlığı ile bağlantısı. mukerrer=true ise aynı günün mükerrer sayılarını da getirir."
        ),
    )
    async def resmi_gazete_fihrist(
        tarih: Annotated[Optional[str], Field(description="YYYY-AA-GG veya GG.AA.YYYY; boşsa bugün (İstanbul)")] = None,
        mukerrer: Annotated[bool, Field(description="Mükerrer sayıları da getir")] = True,
    ) -> dict:
        d = _parse_date(tarih)
        async with _client() as c:
            issues = await _fetch_all(c, d, mukerrer)
        if not issues:
            return {"tarih": d.isoformat(), "bulundu": False, "url": fihrist_url(d), "not": "Bu tarih için fihrist bulunamadı (henüz yayımlanmamış, eski arşiv biçimi veya site yanıt vermedi)."}
        return {"tarih": d.isoformat(), "bulundu": True, "sayilar": issues}

    @mcp.tool(
        name="resmi_gazete_metin",
        description=(
            "Resmî Gazete'de yayımlanmış bir düzenlemenin (PDF veya HTM) tam metnini düz metin olarak getirir. "
            "Yalnızca resmigazete.gov.tr adresleri. Uzun metinlerde baslangic ile sonraki parçayı iste."
        ),
    )
    async def resmi_gazete_metin(
        url: Annotated[str, Field(description="resmigazete.gov.tr'deki düzenleme adresi (fihristteki bağlantı)")],
        baslangic: Annotated[int, Field(description="Metnin kaçıncı karakterinden başlanacağı", ge=0)] = 0,
        uzunluk: Annotated[int, Field(description="Döndürülecek karakter sayısı (en çok 60000)", ge=1000, le=60000)] = 30000,
    ) -> dict:
        async with _client() as c:
            doc = await _doc_text(c, url)
        full = doc.get("metin", "")
        doc["toplam_karakter"] = len(full)
        doc["metin"] = full[baslangic: baslangic + uzunluk]
        doc["devami_var"] = baslangic + uzunluk < len(full)
        return doc

    @mcp.tool(
        name="resmi_gazete_tara",
        description=(
            "Bir günün Resmî Gazete'sini (mükerrerler dahil) takip kelimelerine göre tarar. kelimeler başlıklarda aranır; "
            "metinde_ara verilirse bu ifadeler ayrıca her düzenlemenin tam metninde aranır (PDF'ler sunucuda okunur) ve "
            "eşleşen cümleler alıntılanır. Türkçe büyük/küçük harf duyarsız, kelime kökü yeterli."
        ),
    )
    async def resmi_gazete_tara(
        kelimeler: Annotated[list[str], Field(description="Başlıkta aranacak kelimeler/kökler")],
        tarih: Annotated[Optional[str], Field(description="YYYY-AA-GG; boşsa bugün (İstanbul)")] = None,
        metinde_ara: Annotated[Optional[list[str]], Field(description="Tam metinde de aranacak ayırt edici ifadeler (ör. '6100 sayılı', 'İcra ve İflas Kanunu')")] = None,
    ) -> dict:
        d = _parse_date(tarih)
        words = [w.strip() for w in (kelimeler or []) if w and w.strip()]
        deep = [w.strip() for w in (metinde_ara or []) if w and w.strip()]
        async with _client() as c:
            issues = await _fetch_all(c, d, True)
            if not issues:
                return {"tarih": d.isoformat(), "durum": "yayim_yok", "eslesmeler": [], "toplam": 0}
            items = []
            for iss in issues:
                for sec in iss["bolumler"]:
                    for k in sec["kalemler"]:
                        if k["ilan"] and GENERIC_ILAN.search(k["baslik"]):
                            continue
                        items.append({**k, "bolum": sec["bolum"], "sayi": iss["sayi"], "mukerrer": iss["mukerrer"]})
            hits: dict[str, dict] = {}
            for it in items:
                tl = tr_lower(it["baslik"])
                for w in words:
                    if tr_lower(w) in tl:
                        h = hits.setdefault(it["url"], {"baslik": it["baslik"], "url": it["url"], "bolum": it["bolum"], "kelimeler": [], "yer": "başlık", "alintilar": []})
                        if w not in h["kelimeler"]:
                            h["kelimeler"].append(w)
            okunamayan = []
            if deep:
                sem = asyncio.Semaphore(4)

                async def scan(it):
                    async with sem:
                        try:
                            doc = await _doc_text(c, it["url"])
                        except Exception as e:
                            okunamayan.append({"baslik": it["baslik"], "url": it["url"], "neden": str(e)[:120]})
                            return
                        if doc.get("uyari"):
                            okunamayan.append({"baslik": it["baslik"], "url": it["url"], "bolum": it["bolum"], "taranmis": bool(doc.get("taranmis")), "neden": doc["uyari"]})
                        text = doc.get("metin", "")
                        for w in deep:
                            sn = _snippets(text, w)
                            if sn:
                                h = hits.setdefault(it["url"], {"baslik": it["baslik"], "url": it["url"], "bolum": it["bolum"], "kelimeler": [], "yer": "metin", "alintilar": []})
                                if w not in h["kelimeler"]:
                                    h["kelimeler"].append(w)
                                if h["yer"] == "başlık":
                                    h["yer"] = "başlık ve metin"
                                for x in sn:
                                    if len(h["alintilar"]) < 3 and x not in h["alintilar"]:
                                        h["alintilar"].append(x)

                await asyncio.gather(*(scan(it) for it in items if not it["ilan"]))
        sayi = issues[0]["sayi"] or ""
        if len(issues) > 1:
            sayi = (sayi + " + " + str(len(issues) - 1) + " mükerrer").strip()
        return {
            "tarih": d.isoformat(),
            "sayi": sayi,
            "durum": "tamam",
            "toplam": len(items),
            "metin_tarandi": bool(deep),
            "eslesmeler": list(hits.values()),
            "okunamayan": okunamayan,
            "not": ("Taranmış PDF'ler sunucuda okunamaz; metin araması için okunamayan listesindeki bağlantıları OCR yapan bir araçla (ör. web_fetch) okuyun." if any(o.get("taranmis") for o in okunamayan) else None),
        }
