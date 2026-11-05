# Kurulum kılavuzu

Toplam süre: yaklaşık 1 saat (sunucu kiralama dahil).

## 1. Sizin yapacaklarınız (ödeme ve kimlik gerektirir)

1. **Türkiye'de bir sunucu (VPS) kiralayın:** Ubuntu 24.04, en az 2 çekirdek, 4 GB bellek, 40 GB disk. Yerli sağlayıcılarda aylık yaklaşık 1.500–2.000 TL.
2. **Alan adı:** Sahip olduğunuz bir alan adında, örneğin `mcp.alanadiniz.com.tr` için sunucunun IP adresine yönlenen bir **A kaydı** açın.
3. **TCMB EVDS anahtarı:** evds2.tcmb.gov.tr'ye ücretsiz üye olun → Profil → API Anahtarı.
4. **(İsteğe bağlı) Bildirim e-postası:** Alarmların gelmesini istediğiniz e-posta için SMTP bilgileri (ör. kurumsal e-postanızın gönderim ayarları).

## 2. Sunucuya kurulum

Sunucuya SSH ile root olarak bağlanın ve şu iki komutu çalıştırın:

```bash
git clone https://github.com/cihancebecim-hash/yargucu-yargi.git /root/yargucu-yargi
bash /root/yargucu-yargi/deploy/kur.sh mcp.alanadiniz.com.tr
```

Betik şunları yapar:
- gerekli paketleri kurar (Python, Türkçe yazı tanıma, HTTPS sunucusu),
- otomatik güvenlik güncellemelerini açar,
- gizli MCP adresini ve yönetici anahtarını rastgele üretir,
- **testleri çalıştırır; bir test geçmezse kurulum durur,**
- servisleri, günlük toplama zamanlayıcısını ve günlük yedeği başlatır,
- güvenlik duvarını açar (yalnız SSH, 80, 443).

Sonunda ekrana claude.ai'ye eklenecek bağlayıcı adresi yazılır.

## 3. Ayarları tamamlama

`/etc/yargucu/ortam` dosyasını açın (`nano /etc/yargucu/ortam`):
- `EVDS_ANAHTARI=` satırına TCMB anahtarınızı yazın.
- Bildirim için SMTP satırlarını doldurun.

Sonra: `systemctl restart yargucu-mcp`

### EVDS seri kodları

`kaynak/evds_seriler.json` dosyasında TÜFE ve Yİ-ÜFE kodları hazır. Reeskont, avans ve haftalık mevduat faizi kodları boş. EVDS sitesinde ilgili seriyi açıp "Seri Kodu"nu bu dosyaya yazın.

Kod yanlışsa endişelenmeyin: ilk çalışmada kalibrasyon, kodun geçmiş değerlerini doğrulanmış verilerle karşılaştırır. Tek bir uyuşmazlıkta o koddan değer alınmaz ve alarm gelir.

Deneme: `sudo -u yargucu env $(grep -v '^#' /etc/yargucu/ortam | xargs) /opt/yargucu/venv/bin/python -m kaynak evds`

### İzlenen sayfalar

`kaynak/izlenen_sayfalar.json` dosyasına kredi kartı azami faiz, kıdem tavanı, PTT tebligat ücreti ve vekâlet pulu için resmî sayfa adreslerini yazın. Bu sayfalar her gün kontrol edilir; değiştiklerinde alarm gelir.

## 4. claude.ai'ye bağlama

claude.ai → Ayarlar → Bağlayıcılar:
1. Mevcut "Yargı MCP" bağlayıcısının adresini, kurulumun sonunda yazılan yeni adresle değiştirin. Araç adları aynı kaldığı için YARGUCU uygulaması değişiklik gerektirmeden yeni sunucuyu kullanır.
2. Yeni araçlar (`oran_getir`, `kaynak_durumu`…) aynı bağlayıcıda görünür.

Bundan sonra Prefect Horizon'daki eski sunucuyu kapatabilirsiniz.

## 5. Günlük işleyiş

- Toplama günde beş kez kendiliğinden çalışır. Sorun yoksa sizden hiçbir şey beklenmez.
- **Otomatik onaylananlar:** İki bağımsız kaynağın aynı değeri verdiği oranlar (ör. reeskont oranı). Size "yeni değer onaylandı" bilgisi gelir.
- **Onayınızı bekleyenler:** Yeni harç tebliği, AAÜT, bilirkişi tarifesi gibi tablolar ve tek kaynaktan gelen değerler. Size alarm gelir. Claude'a "Kaynak Motoru'nda onay bekleyenleri göster" dediğinizde liste ve önceki değerle karşılaştırma gelir. Resmî Gazete'deki tabloya bakıp onaylarsınız.
- Onaylanmayan yeni bir tarife hesaplara girmez. Hesaplar önceki tarifeyle yapılır ve uygulama bunu açıkça uyarır.

## 6. Bakım

| İş | Komut |
|---|---|
| Durum | `sudo -u yargucu env $(grep -v '^#' /etc/yargucu/ortam \| xargs) /opt/yargucu/venv/bin/python -m kaynak durum` |
| Günlükler | `journalctl -u yargucu-mcp -u yargucu-kaynak --since today` |
| Güncelleme | `bash /opt/yargucu/yargucu-yargi/deploy/kur.sh mcp.alanadiniz.com.tr` (testler yeniden çalışır) |
| Yedekler | `/var/lib/yargucu/yedek/` (her gece 03:15, 30 gün saklanır) |
