#!/usr/bin/env bash
# YARGUCU kendi sunucu kurulumu — Ubuntu 24.04 LTS (Türkiye'deki VPS)
# Kullanım (root olarak):  bash kur.sh ALAN_ADI
#   ALAN_ADI: sunucunuzun IP adresine yönlendirdiğiniz alan adı (ör. mcp.ornekhukuk.com.tr)
set -euo pipefail
ALAN="${1:?Kullanım: bash kur.sh ALAN_ADI}"
DEPO_URL="${DEPO_URL:-https://github.com/cihancebecim-hash/yargucu-yargi.git}"
KOK=/opt/yargucu; VERI=/var/lib/yargucu; ORTAM=/etc/yargucu/ortam

echo "== 1/8 Sistem paketleri"
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip git sqlite3 tesseract-ocr tesseract-ocr-tur caddy ufw unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades || true

echo "== 2/8 Kullanıcı ve klasörler"
id yargucu >/dev/null 2>&1 || useradd --system --home "$KOK" --shell /usr/sbin/nologin yargucu
mkdir -p "$KOK" "$VERI/yedek" /etc/yargucu
chown -R yargucu:yargucu "$KOK" "$VERI"; chmod 750 "$VERI"

echo "== 3/8 Kod"
if [ -d "$KOK/yargucu-yargi/.git" ]; then sudo -u yargucu git -C "$KOK/yargucu-yargi" pull --ff-only
else sudo -u yargucu git clone "$DEPO_URL" "$KOK/yargucu-yargi"; fi

echo "== 4/8 Python ortamı"
[ -d "$KOK/venv" ] || sudo -u yargucu python3 -m venv "$KOK/venv"
sudo -u yargucu "$KOK/venv/bin/pip" install -q --upgrade pip
sudo -u yargucu "$KOK/venv/bin/pip" install -q -r "$KOK/yargucu-yargi/requirements.txt" pytest

echo "== 5/8 Gizli ayarlar"
if [ ! -f "$ORTAM" ]; then
  cp "$KOK/yargucu-yargi/deploy/ortam.ornek" "$ORTAM"
  sed -i "s#^MCP_YOL=.*#MCP_YOL=/mcp-$(openssl rand -hex 24)#" "$ORTAM"
  sed -i "s#^YONETICI_ANAHTARI=.*#YONETICI_ANAHTARI=$(openssl rand -base64 33 | tr -d '/+=' | cut -c1-40)#" "$ORTAM"
fi
chown root:yargucu "$ORTAM"; chmod 640 "$ORTAM"
MCP_YOL=$(grep ^MCP_YOL= "$ORTAM" | cut -d= -f2)

echo "== 6/8 Testler (geçmezse kurulum durur)"
cd "$KOK/yargucu-yargi" && sudo -u yargucu env KAYNAK_DB=":memory:" "$KOK/venv/bin/python" -m pytest -q -p no:cacheprovider

echo "== 7/8 Servisler"
cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sed "s#ALAN_ADI#$ALAN#; s#MCP_YOL#$MCP_YOL#g" deploy/Caddyfile > /etc/caddy/Caddyfile
systemctl daemon-reload
sudo -u yargucu env $(grep -v '^#' "$ORTAM" | xargs) "$KOK/venv/bin/python" -m kaynak tohumla
systemctl enable --now yargucu-mcp.service yargucu-kaynak.timer yargucu-yedek.timer
systemctl restart caddy

echo "== 8/8 Güvenlik duvarı"
ufw allow OpenSSH; ufw allow 80/tcp; ufw allow 443/tcp; ufw --force enable

echo
echo "Kurulum tamam."
echo "claude.ai → Ayarlar → Bağlayıcılar → Özel bağlayıcı ekle → URL:"
echo "   https://$ALAN$MCP_YOL"
echo "Yönetici anahtarı ve diğer ayarlar: $ORTAM  (EVDS_ANAHTARI ve bildirim ayarlarını buradan girin, sonra: systemctl restart yargucu-mcp)"
echo "İlk toplama: sudo -u yargucu env \$(grep -v '^#' $ORTAM | xargs) $KOK/venv/bin/python -m kaynak gunluk"
