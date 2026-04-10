# Lightsail Day-1 Deploy Checklist (Single Instance)

## 1) Provision server
- Create Ubuntu 22.04 Lightsail instance (start with 8 GB RAM).
- Attach static IP.
- Open Lightsail networking ports: `22`, `80`, `443`.

## 2) Bootstrap server
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl gnupg lsb-release git nginx

# Docker
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
```
Log out/in once after adding Docker group.

## 3) Deploy code
```bash
sudo mkdir -p /opt/claim-reproduce
sudo chown -R $USER:$USER /opt/claim-reproduce
git clone https://github.com/<your-org>/<your-repo>.git /opt/claim-reproduce
cd /opt/claim-reproduce
git checkout main
```

## 4) Prepare env
```bash
cd /opt/claim-reproduce
cp ops/env/api.env.example ops/env/api.env
```
Edit `ops/env/api.env` with real values, especially:
- `OPENAI_API_KEY`
- `MYSQL_PASSWORD`
- `MYSQL_ROOT_PASSWORD`

## 5) Start stack
```bash
cd /opt/claim-reproduce/ops
docker compose -f docker-compose.prod.yml --env-file env/api.env up -d --build
```

## 6) Configure Nginx
```bash
sudo cp /opt/claim-reproduce/ops/nginx/claim-reproduce.conf /etc/nginx/sites-available/claim-reproduce
sudo ln -s /etc/nginx/sites-available/claim-reproduce /etc/nginx/sites-enabled/claim-reproduce
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```
Update `server_name` in `/etc/nginx/sites-available/claim-reproduce` first.

## 7) Add HTTPS
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d app.example.com -d api.example.com
```

## 8) Validate
```bash
curl -I http://127.0.0.1:8000/health
curl -I https://app.example.com
curl -I https://app.example.com/backend/health
```

## 9) Optional: auto-start on reboot
```bash
sudo cp /opt/claim-reproduce/ops/systemd/claim-reproduce.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable claim-reproduce
sudo systemctl start claim-reproduce
```

## 10) Day-1 operations
```bash
# update and redeploy
cd /opt/claim-reproduce
git pull
cd ops
docker compose -f docker-compose.prod.yml --env-file env/api.env up -d --build

# logs
docker compose -f docker-compose.prod.yml --env-file env/api.env logs -f api
docker compose -f docker-compose.prod.yml --env-file env/api.env logs -f web
```
