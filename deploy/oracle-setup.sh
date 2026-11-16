#!/usr/bin/env bash
# Sets up HomeFlix on a fresh Ubuntu server (Oracle Cloud Always Free, Arm or AMD).
# Run from the unpacked HomeFlix folder, with .env already copied in:  sudo bash deploy/oracle-setup.sh
# Safe to run again after uploading a new version: it rebuilds and restarts HomeFlix.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run it with sudo: sudo bash deploy/oracle-setup.sh" >&2
    exit 1
fi
if [ ! -f .env ]; then
    echo "No .env in $APP_DIR. Copy your .env from the PC first (see deploy/ORACLE.md)." >&2
    exit 1
fi
if [ ! -f homeflix.db ]; then
    echo "No homeflix.db in $APP_DIR. The upload bundle should contain it (see deploy/ORACLE.md)." >&2
    exit 1
fi

# The smallest free server (1 GB memory) needs swap to build the image
if [ "$(awk '/MemTotal/ {print $2}' /proc/meminfo)" -lt 2000000 ] && ! swapon --show | grep -q .; then
    echo "== Adding 2 GB of swap"
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

if ! command -v docker >/dev/null; then
    echo "== Installing Docker (from docker.com)"
    curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

if ! command -v cloudflared >/dev/null; then
    echo "== Installing cloudflared (from Cloudflare's GitHub releases)"
    deb="/tmp/cloudflared.deb"
    curl -fsSL -o "$deb" "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$(dpkg --print-architecture).deb"
    dpkg -i "$deb"
    rm -f "$deb"
fi

echo "== Building and starting HomeFlix"
docker compose -f docker-compose.yml -f deploy/docker-compose.server.yml up -d --build

echo "== Starting the public link"
cat > /etc/systemd/system/homeflix-tunnel.service <<'EOF'
[Unit]
Description=HomeFlix public link (Cloudflare quick tunnel)
After=network-online.target docker.service
Wants=network-online.target

[Service]
ExecStart=/usr/bin/cloudflared tunnel --no-autoupdate --url http://localhost:5000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# `homeflix-link` prints the current link; it changes only when the tunnel or server restarts
cat > /usr/local/bin/homeflix-link <<'EOF'
#!/usr/bin/env bash
journalctl -u homeflix-tunnel -o cat --no-pager | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1
EOF
chmod +x /usr/local/bin/homeflix-link

systemctl daemon-reload
systemctl enable homeflix-tunnel >/dev/null 2>&1
systemctl restart homeflix-tunnel

link=""
for _ in $(seq 1 60); do
    link="$(homeflix-link)"
    [ -n "$link" ] && break
    sleep 1
done

if [ -z "$link" ]; then
    echo "The tunnel didn't give a link within a minute. Details: journalctl -u homeflix-tunnel" >&2
    exit 1
fi
echo
echo "HomeFlix is online: $link"
echo "To see the link again later, run: homeflix-link"
