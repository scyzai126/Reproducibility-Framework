#!/usr/bin/env bash
# infra/setup.sh — One-time EC2 provisioning script
# Ubuntu 24.04 LTS, t3.medium, 30 GB root volume
#
# Usage:
#   1. SSH into the instance: ssh -i your-key.pem ubuntu@<ELASTIC_IP>
#   2. git clone <repo> /opt/app && cd /opt/app
#   3. sudo bash infra/setup.sh

set -euo pipefail

APP_DIR="/opt/app"
API_DIR="$APP_DIR/apps/api"
WEB_DIR="$APP_DIR/apps/web"

# Ensure the ubuntu user owns the repo (in case it was cloned as root)
chown -R ubuntu:ubuntu "$APP_DIR"

# ── Helpers ───────────────────────────────────────────────────────────────────
info() { echo -e "\n\033[1;34m▶ $*\033[0m"; }
ok()   { echo -e "\033[1;32m✓ $*\033[0m"; }

# ── 1. System packages ────────────────────────────────────────────────────────
info "Updating system packages"
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    curl git unzip build-essential \
    nginx \
    python3.12 python3.12-venv python3-pip \
    mysql-server
ok "System packages installed"

# ── 2. Node.js 22 ─────────────────────────────────────────────────────────────
info "Installing Node.js 22"
if ! command -v node &>/dev/null || [[ "$(node --version)" != v22* ]]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y nodejs
fi
npm install -g pm2
ok "Node.js $(node --version) + pm2 installed"

# ── 3. MySQL ──────────────────────────────────────────────────────────────────
info "Configuring MySQL"
systemctl enable --now mysql

read -rsp $'\nEnter a password for MySQL app user (immport_user): ' DB_PASS
echo
read -rsp 'Enter MySQL root password (blank if none set yet): ' ROOT_PASS
echo

MYSQL_CMD=(mysql -u root)
[[ -n "$ROOT_PASS" ]] && MYSQL_CMD+=("-p$ROOT_PASS")

# Escape password for safe SQL string insertion (handles quotes/backslashes).
ESCAPED_DB_PASS=${DB_PASS//\\/\\\\}
ESCAPED_DB_PASS=${ESCAPED_DB_PASS//\'/\\\'}

"${MYSQL_CMD[@]}" <<SQL
CREATE DATABASE IF NOT EXISTS immport_dr62
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'immport_user'@'localhost' IDENTIFIED BY '${ESCAPED_DB_PASS}';
GRANT ALL PRIVILEGES ON immport_dr62.* TO 'immport_user'@'localhost';
FLUSH PRIVILEGES;
SQL
ok "MySQL: database 'immport_dr62' and user 'immport_user' ready"

# ── 4. Backend (FastAPI) ──────────────────────────────────────────────────────
info "Setting up FastAPI backend"
python3.12 -m venv "$API_DIR/.venv"
"$API_DIR/.venv/bin/pip" install --upgrade pip -q
"$API_DIR/.venv/bin/pip" install -r "$API_DIR/requirements.txt" -q

if [[ ! -f "$API_DIR/.env" ]]; then
    cat > "$API_DIR/.env" <<ENV
OPENAI_API_KEY=           # fill in
OPENAI_MODEL=gpt-5.4
MYSQL_URL=mysql+aiomysql://immport_user:${DB_PASS}@localhost:3306/immport_dr62
IMMPORT_USERNAME=         # fill in
IMMPORT_PASSWORD=         # fill in
ENV
    chown ubuntu:ubuntu "$API_DIR/.env"
    echo "  Created $API_DIR/.env — fill in OPENAI_API_KEY and IMMPORT credentials"
fi

cp "$APP_DIR/infra/api.service" /etc/systemd/system/reproducibility-api.service
systemctl daemon-reload
systemctl enable reproducibility-api   # start manually after filling in .env
ok "FastAPI service registered (not started yet — fill in .env first)"

# ── 5. Frontend (Next.js) ─────────────────────────────────────────────────────
info "Building Next.js frontend"
sudo -u ubuntu bash -c "
    cd '$WEB_DIR'
    npm ci
    NEXT_PUBLIC_BACKEND_ORIGIN=http://localhost:8000 npm run build
"

cat > "$WEB_DIR/ecosystem.config.js" <<'JS'
module.exports = {
  apps: [{
    name: 'reproducibility-web',
    script: 'node_modules/.bin/next',
    args: 'start',
    cwd: __dirname,
    env: {
      NODE_ENV: 'production',
      PORT: '3000',
      NEXT_PUBLIC_BACKEND_ORIGIN: 'http://localhost:8000',
    },
  }],
};
JS
chown ubuntu:ubuntu "$WEB_DIR/ecosystem.config.js"

sudo -u ubuntu pm2 start "$WEB_DIR/ecosystem.config.js"
sudo -u ubuntu pm2 save
# Register pm2 to start on reboot
env PATH="$PATH:/usr/bin" pm2 startup systemd -u ubuntu --hp /home/ubuntu >/dev/null
ok "Next.js running via pm2"

# ── 6. nginx ──────────────────────────────────────────────────────────────────
info "Configuring nginx"
cp "$APP_DIR/infra/nginx.conf" /etc/nginx/sites-available/reproducibility
ln -sf /etc/nginx/sites-available/reproducibility /etc/nginx/sites-enabled/reproducibility
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx
ok "nginx configured"

# ── Done ──────────────────────────────────────────────────────────────────────
PUBLIC_IP=$(curl -s ifconfig.me)
echo ""
echo "============================================================"
echo " Setup complete. Next steps:"
echo "============================================================"
echo ""
echo " 1. Fill in $API_DIR/.env (OPENAI_API_KEY, IMMPORT creds)"
echo "    then: sudo systemctl restart reproducibility-api"
echo ""
echo " 2. Load the ImmPort database (10 GB dump):"
echo "    mysql -u immport_user -p immport_dr62 < immport_dr62.sql"
echo ""
echo " 3. (Optional) Add TLS:"
echo "    sudo apt install certbot python3-certbot-nginx"
echo "    sudo certbot --nginx -d your.domain.com"
echo ""
echo " 4. Lock down the EC2 Security Group to your lab's IP."
echo ""
echo " App: http://$PUBLIC_IP"
echo "============================================================"
