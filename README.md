# YARGUCU – kendi MCP sunucusu

Bu depo YARGUCU'nun dış servislere bağımlı olmadan çalışan kendi sunucusudur. Üç parçadan oluşur:

| Parça | Ne yapar | Kaynak |
|---|---|---|
| Yargı araçları | Yargıtay, Danıştay, istinaf ve yerel mahkeme kararları (Bedesten), UYAP Emsal, AYM, Uyuşmazlık, KİK, Rekabet, Sayıştay, KVKK, BDDK, BTK, GİB, Sigorta Tahkim | Açık kaynak (MIT) [yargi-mcp](https://pypi.org/project/yargi-mcp/) paketi, kendi sunucunuzda |
| Resmî Gazete araçları | Fihrist, metin, biçimli belge, kelime taraması | `resmi_gazete.py`, doğrudan resmigazete.gov.tr |
| **Kaynak Motoru** | Hukuki hesaplardaki oran ve tarifelerin doğrulanmış, tarihe bağlı deposu | `kaynak/`, doğrudan resmî kaynaklar |

Hiçbir parça yapay zekâ kullanmaz. Aracı arama servisi, ücretli eklenti veya dış barındırma gerekmez.

## Kaynak Motoru'nun temel kuralı: sessiz hata yok

Bir oran ya **doğrulanmış** olarak kullanılır ya da kullanılmaz ve alarm verilir.

1. **Toplayıcılar** her gün 00:20, 07:05, 10:35, 14:05 ve 18:05'te çalışır:
   - Resmî Gazete (mükerrerler dahil) arşivlenir; harç, AAÜT, bilirkişi, arabuluculuk, gider avansı, asgari ücret, gecikme zammı ve tecil faizi düzenlemeleri başlıktan tanınır.
   - TCMB reeskont ve avans oranları TCMB sayfasından okunur.
   - TÜFE, Yİ-ÜFE ve diğer seriler TCMB EVDS'ten okunur (anahtar gerekir).
   - Değeri otomatik okunamayan sayfalar (kredi kartı azami faiz, kıdem tavanı, PTT, vekâlet pulu) değişiklik için izlenir.
2. **Doğrulama kapıları:**
   - *Kalibrasyon:* Bir kaynak, geçmişte doğrulanmış değerleri birebir vermiyorsa (sayfa yapısı değiştiyse, seri kodu yanlışsa) o kaynaktan hiç değer alınmaz.
   - *Çift kaynak:* Otomatik onay ancak iki bağımsız kaynak aynı değeri verirse olur. Tek kaynaktan gelen değer 48 saat sonra yöneticinin onayına düşer.
   - *Makullük:* Aralık dışı değer, olağan dışı sıçrama, düşen tutar, geçmişe dönük kayıt otomatik onaylanmaz.
   - *Karmaşık tarifeler* (harç, AAÜT, bilirkişi…) her zaman yönetici onayıyla girer.
3. **Değişmezlik:** Onaylı bir değer silinemez, değiştirilemez. Farklı bir değer gelirse kritik alarm açılır.
4. **Bekçi:** Beklenen güncelleme gelmezse (ör. ayın 4'üne kadar TÜFE, ocakta yeni harç tebliği) veya bir kaynak üst üste iki kez okunamazsa alarm açılır; durum düzelince kendiliğinden kapanır. Alarmlar e-posta veya web kancasıyla iletilir.

Başlangıç verisi (`kaynak/tohum.json`), YARGUCU uygulamasında gömülü olan ve daha önce doğrulanmış tablolardır. Testler, sunucunun kanuni faiz ve ticari temerrüt faizini 1997–2027 arasında uygulamayla **birebir aynı** hesapladığını doğrular.

## MCP araçları

| Araç | Açıklama |
|---|---|
| `oran_getir(seri, tarih)` | O tarihte yürürlükte olan doğrulanmış değer ve güncellik uyarıları. Türetilenler: `kanuni_faiz`, `avans_faizi_3095` |
| `oran_serisi(seri)` | Bir serinin tüm değişiklik noktaları |
| `oran_katalogu()` | Takip edilen tüm seriler ve güncellik durumu |
| `kaynak_durumu()` | Açık alarmlar, kaynak sağlığı, onay bekleyenler, yeni yayımlanan tarifeler |
| `oran_onay_listesi`, `oran_karar`, `oran_elle_gir` | Yönetici işlemleri (yönetici anahtarı gerekir) |
| `rg_arsiv(tarih)` | Arşivlenmiş Resmî Gazete fihristi |

## Kurulum

Ayrıntılı adımlar: [KURULUM.md](KURULUM.md). Kısaca, Türkiye'de bir Ubuntu 24.04 sunucuda:

```bash
bash deploy/kur.sh mcp.alanadiniz.com.tr
```

## Testler

```bash
python -m pytest -q
```

Testler ağ gerektirmez; dış kaynaklar örnek verilerle taklit edilir.
