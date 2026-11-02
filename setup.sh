#!/usr/bin/env bash
# JobNova installer for Ubuntu 22.04 (Oracle Always Free VM, 1 GB RAM).
# Usage:  bash setup.sh https://github.com/YOUR_USER/YOUR_REPO.git
set -euo pipefail
REPO_URL="${1:?Usage: bash setup.sh https://github.com/YOUR_USER/YOUR_REPO.git}"
APP_DIR=/opt/jobnova
RUN_USER="$(whoami)"

echo "== 1/7 Packages"
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip git sqlite3 curl

echo "== 2/7 Swap (2 GB, protects a 1 GB machine)"
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "== 3/7 Code"
sudo mkdir -p "$APP_DIR" && sudo chown "$RUN_USER":"$RUN_USER" "$APP_DIR"
if [ -d "$APP_DIR/.git" ]; then git -C "$APP_DIR" pull --ff-only; else git clone "$REPO_URL" "$APP_DIR"; fi
mkdir -p "$APP_DIR/data" "$APP_DIR/backups"

echo "== 4/7 Python environment"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "== 5/7 Settings file"
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/env.example" "$APP_DIR/.env"; chmod 600 "$APP_DIR/.env"
  SK="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
  AP="$(python3 -c 'import secrets;print(secrets.token_urlsafe(14))')"
  AK="$(python3 -c 'import secrets,string;print("".join(secrets.choice(string.ascii_letters+string.digits) for _ in range(28)))')"
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SK|; s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=$AP|; s|^ADMIN_KEY=.*|ADMIN_KEY=$AK|" "$APP_DIR/.env"
  echo "   New admin password: $AP   (also saved in $APP_DIR/.env)"
  echo "   New ADMIN_KEY for Cloudflare Worker: $AK"
fi

echo "== 6/7 Service (gunicorn, only reachable from this machine)"
sudo tee /etc/systemd/system/jobnova.service >/dev/null <<UNIT
[Unit]
Description=JobNova Flask app
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/gunicorn -w 1 --threads 4 --timeout 120 -b 127.0.0.1:8000 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now jobnova

echo "== 7/7 Daily backup (03:30) + cloudflared"
cat > "$APP_DIR/backup.sh" <<'BK'
#!/usr/bin/env bash
set -e
cd /opt/jobnova
DB=data/jobnova.db
[ -f "$DB" ] || exit 0
sqlite3 "$DB" ".backup 'backups/jobnova-$(date +%F).db'"
find backups -name 'jobnova-*.db' -mtime +14 -delete
[ -f data/site_ui.json ] && cp data/site_ui.json "backups/site_ui-$(date +%F).json"
[ -d data/uploads ] && tar czf "backups/uploads-$(date +%F).tgz" -C data uploads
find backups -name 'site_ui-*.json' -mtime +14 -delete
find backups -name 'uploads-*.tgz' -mtime +14 -delete
BK
chmod +x "$APP_DIR/backup.sh"
( crontab -l 2>/dev/null | grep -v jobnova/backup.sh || true; echo "30 3 * * * /opt/jobnova/backup.sh" ) | crontab -

if ! command -v cloudflared >/dev/null; then
  sudo mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
  echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' | sudo tee /etc/apt/sources.list.d/cloudflared.list >/dev/null
  sudo apt-get update -y && sudo apt-get install -y cloudflared
fi

echo
echo "DONE. Check the app:  curl -I http://127.0.0.1:8000/"
echo "Next: connect the Cloudflare Tunnel (see README step 4)."
