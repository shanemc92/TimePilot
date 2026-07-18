#!/usr/bin/env bash
set -uo pipefail

### ---- EDIT THESE ---- ###
DOMAIN="timepilot-demo.example.com"
CF_ZONE_NAME="example.com"          # <-- the Cloudflare zone this domain lives in
CF_PROXIED=false                    # <-- true = orange cloud (proxied), false = grey cloud (DNS only)
LE_EMAIL="you@example.com"          # <-- Let's Encrypt notification email
CF_API_TOKEN="cf_token_here"        # <-- Cloudflare token, Zone:DNS:Edit scope
NTFY_TOPIC="your-unique-topic-here" # <-- pick something unguessable
DEMO_USERNAME="demo"                # <-- account sample_data.py resets daily
DEMO_PASSWORD="ChangeThisDemoPass"  # <-- initial password, only used until the first nightly reset generates a random one
TIMEPILOT_DISABLE_SIGNUP=false		# <-- disables the signup option so only the demo user works
TIMEPILOT_LOGIN_BANNER_TEMPLATE="Demo instance - today's password is %s - all data is wiped every 24 hours."
DNS_PROPAGATION_BUFFER=30           # <-- seconds to wait before the final HTTPS check, for external resolvers to pick up the new record
SSH_PORT=2222                       # <-- custom SSH port (update your SSH client and cloud firewall config to match before running!)
FAIL2BAN_MAXRETRY=3                 # <-- how many ssh failed logins before IP is blocked
FAIL2BAN_BANTIME=3600               # <-- seconds = 1 hour
FAIL2BAN_FINDTIME=600               # <-- window within which maxretry failures count
### --------------------- ###

LOG_FILE="/var/log/timepilot-init.log"
exec > >(tee -a "$LOG_FILE") 2>&1

notify() {
    curl -fsS -m 10 -H "Title: $1" -H "Tags: ${3:-}" -d "$2" "https://ntfy.sh/${NTFY_TOPIC}" >/dev/null 2>&1 || true
}

# run_step "desc" check_fn action_fn
# Skips (silently, just logged) if check_fn already returns true.
# Notifies on actual action taken, and always notifies on failure.
run_step() {
    local desc="$1" check_fn="$2" action_fn="$3"
    if "$check_fn"; then
        echo "==> ${desc}: already done, skipping"
        return 0
    fi
    echo "==> ${desc}"
    if "$action_fn" >>"$LOG_FILE" 2>&1; then
        notify "TimePilot setup: OK" "${desc}" "white_check_mark"
    else
        local rc=$?
        local tail_output; tail_output=$(tail -n 20 "$LOG_FILE")
        notify "TimePilot setup: FAILED" "${desc} (exit ${rc})
---
${tail_output}" "rotating_light"
        echo "FAILED: ${desc} — see ${LOG_FILE}"
        exit "$rc"
    fi
}

if [[ $EUID -ne 0 ]]; then echo "Run as root (sudo)."; exit 1; fi

notify "TimePilot setup: started" "Running setup checks on $(hostname)."

### 1. Updates ###
check_updates() { false; }   # always safe/cheap to re-run, no meaningful skip condition
step_updates() { apt update && apt -y upgrade; }
run_step "apt update & upgrade" check_updates step_updates

### 2. Base deps ###
check_deps() { dpkg -s nginx certbot python3-certbot-dns-cloudflare git openssl iptables-persistent cron >/dev/null 2>&1 && systemctl is-active --quiet cron; }
step_deps() {
    echo iptables-persistent iptables-persistent/autosave_v4 boolean true | debconf-set-selections
    echo iptables-persistent iptables-persistent/autosave_v6 boolean true | debconf-set-selections
    # Ubuntu 24.04 minimal doesn't ship cron by default — needed for the nightly reset job.
    apt install -y ca-certificates curl gnupg nginx certbot python3-certbot-dns-cloudflare git openssl iptables-persistent cron
    systemctl enable --now cron
}
run_step "install base dependencies" check_deps step_deps

### 2b. SSH hardening: switch to SSH_PORT, disable root login + password auth. ###
### Old port 22 stays open in the firewall until the new port is CONFIRMED listening — ###
### only then is 22 closed. If verification fails, this step aborts and leaves 22 open ###
### rather than risk locking you out over a config problem. ###
check_ssh_hardening() {
    [[ -f /etc/ssh/sshd_config.d/99-hardening.conf ]] \
      && grep -q "^Port ${SSH_PORT}$" /etc/ssh/sshd_config.d/99-hardening.conf \
      && ss -tlnp 2>/dev/null | grep -q ":${SSH_PORT} " \
      && ! iptables -C INPUT -p tcp --dport 22 -j ACCEPT >/dev/null 2>&1
}
step_ssh_hardening() {
    # Ubuntu 24.04 often ships ssh.socket for socket-activation, which hardcodes ListenStream=22
    # independent of sshd_config's Port directive — restarting ssh.service alone won't rebind
    # the actual listening socket while this is active. Disable it in favor of plain ssh.service.
    if systemctl is-active --quiet ssh.socket 2>/dev/null; then
        systemctl disable --now ssh.socket
        systemctl enable ssh.service
    fi

    # Figure out what port was previously configured (default 22 on a first-ever run) so we
    # know exactly what to close later — not just literal 22 — if SSH_PORT has changed again.
    local old_port="22"
    if [[ -f /etc/ssh/sshd_config.d/99-hardening.conf ]]; then
        old_port=$(grep -oP '^Port \K[0-9]+' /etc/ssh/sshd_config.d/99-hardening.conf 2>/dev/null || echo "22")
    fi

    # Open the new port first so sshd has somewhere safe to land before we touch its config
    iptables -C INPUT -p tcp --dport "${SSH_PORT}" -j ACCEPT >/dev/null 2>&1 \
        || iptables -I INPUT -p tcp --dport "${SSH_PORT}" -j ACCEPT

    cat > /etc/ssh/sshd_config.d/99-hardening.conf <<EOF
Port ${SSH_PORT}
PermitRootLogin no
PasswordAuthentication no
PermitEmptyPasswords no
MaxAuthTries 3
X11Forwarding no
ClientAliveInterval 300
ClientAliveCountMax 2
LoginGraceTime 30
EOF

    if ! sshd -t; then
        echo "sshd config test failed — leaving old config/port in place"
        rm -f /etc/ssh/sshd_config.d/99-hardening.conf
        return 1
    fi

    systemctl restart ssh

    local listening=false
    for i in $(seq 1 10); do
        if ss -tlnp 2>/dev/null | grep -q ":${SSH_PORT} "; then listening=true; break; fi
        sleep 1
    done
    if [[ "${listening}" != "true" ]]; then
        echo "sshd did not come up on port ${SSH_PORT} — aborting, old port ${old_port} stays open"
        return 1
    fi

    # New port confirmed working — safe to close whatever the old port was
    if [[ "${old_port}" != "${SSH_PORT}" ]]; then
        while iptables -C INPUT -p tcp --dport "${old_port}" -j ACCEPT >/dev/null 2>&1; do
            iptables -D INPUT -p tcp --dport "${old_port}" -j ACCEPT
        done
        # Oracle's default image also ships this exact variant for port 22 specifically
        while iptables -C INPUT -p tcp --dport "${old_port}" -m state --state NEW -j ACCEPT >/dev/null 2>&1; do
            iptables -D INPUT -p tcp --dport "${old_port}" -m state --state NEW -j ACCEPT
        done
    fi
    netfilter-persistent save
}
run_step "harden SSH + switch to port ${SSH_PORT}" check_ssh_hardening step_ssh_hardening

### 2c. Firewall: only SSH_PORT and HTTPS (443) reachable; everything else dropped ###
check_firewall() {
    iptables -C INPUT -p tcp --dport "${SSH_PORT}" -j ACCEPT >/dev/null 2>&1 \
      && iptables -C INPUT -p tcp --dport 443 -j ACCEPT >/dev/null 2>&1 \
      && ! iptables -C INPUT -p tcp --dport 80 -j ACCEPT >/dev/null 2>&1 \
      && ! iptables -C INPUT -p tcp --dport 22 -j ACCEPT >/dev/null 2>&1
}
step_firewall() {
    iptables -C INPUT -p tcp --dport "${SSH_PORT}" -j ACCEPT >/dev/null 2>&1 || iptables -I INPUT -p tcp --dport "${SSH_PORT}" -j ACCEPT
    iptables -C INPUT -p tcp --dport 443 -j ACCEPT >/dev/null 2>&1 || iptables -I INPUT -p tcp --dport 443 -j ACCEPT
    # Remove port 80 and the old SSH port 22 if either is still open
    while iptables -C INPUT -p tcp --dport 80 -j ACCEPT >/dev/null 2>&1; do
        iptables -D INPUT -p tcp --dport 80 -j ACCEPT
    done
    while iptables -C INPUT -p tcp --dport 22 -j ACCEPT >/dev/null 2>&1; do
        iptables -D INPUT -p tcp --dport 22 -j ACCEPT
    done
    # Ensure a final catch-all reject exists so nothing else is reachable
    iptables -C INPUT -j REJECT --reject-with icmp-host-prohibited >/dev/null 2>&1 \
      || iptables -A INPUT -j REJECT --reject-with icmp-host-prohibited
    netfilter-persistent save
}
run_step "lock down firewall to ${SSH_PORT}+443 only" check_firewall step_firewall

### 2d. Unattended security upgrades ###
check_unattended() { dpkg -s unattended-upgrades >/dev/null 2>&1 && [[ -f /etc/apt/apt.conf.d/20auto-upgrades ]]; }
step_unattended() {
    apt install -y unattended-upgrades
    cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
    systemctl enable --now unattended-upgrades
}
run_step "enable unattended security upgrades" check_unattended step_unattended

### 2e. fail2ban — bans an IP for FAIL2BAN_BANTIME after FAIL2BAN_MAXRETRY failed SSH attempts ###
check_fail2ban() {
    dpkg -s fail2ban >/dev/null 2>&1 || return 1
    systemctl is-active --quiet fail2ban || return 1
    [[ -f /etc/fail2ban/jail.d/sshd.local ]] || return 1
    grep -q "^port = ${SSH_PORT}$" /etc/fail2ban/jail.d/sshd.local \
      && grep -q "^maxretry = ${FAIL2BAN_MAXRETRY}$" /etc/fail2ban/jail.d/sshd.local \
      && grep -q "^findtime = ${FAIL2BAN_FINDTIME}$" /etc/fail2ban/jail.d/sshd.local \
      && grep -q "^bantime = ${FAIL2BAN_BANTIME}$" /etc/fail2ban/jail.d/sshd.local
}
step_fail2ban() {
    apt install -y fail2ban
    cat > /etc/fail2ban/jail.d/sshd.local <<EOF
[sshd]
enabled = true
port = ${SSH_PORT}
maxretry = ${FAIL2BAN_MAXRETRY}
findtime = ${FAIL2BAN_FINDTIME}
bantime = ${FAIL2BAN_BANTIME}
EOF
    systemctl enable --now fail2ban
    systemctl restart fail2ban
}
run_step "configure fail2ban for sshd" check_fail2ban step_fail2ban

### 3. Docker ###
check_docker_repo() { [[ -f /etc/apt/sources.list.d/docker.list ]]; }
step_docker_repo() {
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      > /etc/apt/sources.list.d/docker.list
    apt update
}
run_step "add Docker repo" check_docker_repo step_docker_repo

check_docker_install() { command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; }
step_docker_install() { apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin; }
run_step "install Docker" check_docker_install step_docker_install

### 4. Clone TimePilot (never wipe an existing checkout — it holds .env/secrets) ###
check_clone() { [[ -d /opt/TimePilot/.git ]]; }
step_clone() {
    cd /opt
    git clone https://github.com/shanemc92/TimePilot.git
    cd /opt/TimePilot
    cp .env.example .env
}
run_step "clone TimePilot repo" check_clone step_clone

### 5. Generate secrets into .env — NEVER regenerate if already set. ###
### Rotating TIMEPILOT_MASTER_KEY after data exists makes all existing data unrecoverable. ###
check_secrets() {
    [[ -f /opt/TimePilot/.env ]] \
      && grep -q '^POSTGRES_PASSWORD=.\+' /opt/TimePilot/.env \
      && grep -q '^FLASK_SECRET_KEY=.\+' /opt/TimePilot/.env \
      && grep -q '^TIMEPILOT_MASTER_KEY=.\+' /opt/TimePilot/.env
}
step_secrets() {
    cd /opt/TimePilot
    local pg_pass flask_secret master_key
    pg_pass=$(openssl rand -hex 24)
    flask_secret=$(openssl rand -hex 32)
    master_key=$(python3 -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())")
    sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${pg_pass}|" .env
    sed -i "s|^FLASK_SECRET_KEY=.*|FLASK_SECRET_KEY=${flask_secret}|" .env
    sed -i "s|^TIMEPILOT_MASTER_KEY=.*|TIMEPILOT_MASTER_KEY=${master_key}|" .env
}
run_step "generate .env secrets" check_secrets step_secrets

### 5b. Demo-mode env vars — not secrets, safe to always keep in sync (unlike the guarded values above). ###
### Requires app support for these two vars in TimePilot's code (not upstream by default). ###
check_demo_env() {
    [[ -f /opt/TimePilot/.env ]] || return 1
    grep -q "^TIMEPILOT_DISABLE_SIGNUP=${TIMEPILOT_DISABLE_SIGNUP}$" /opt/TimePilot/.env || return 1
    # Compare only the template's fixed text (prefix/suffix around %s), not the whole line —
    # the password portion legitimately changes every night via daily-reset.sh and shouldn't
    # cause this to re-fire and stomp on that night's already-rotated password.
    local prefix="${TIMEPILOT_LOGIN_BANNER_TEMPLATE%%%s*}"
    local suffix="${TIMEPILOT_LOGIN_BANNER_TEMPLATE##*%s}"
    local current
    current=$(grep '^TIMEPILOT_LOGIN_BANNER=' /opt/TimePilot/.env | sed 's/^TIMEPILOT_LOGIN_BANNER=//')
    [[ -n "${current}" && "${current}" == "${prefix}"*"${suffix}" ]]
}
step_demo_env() {
    cd /opt/TimePilot
    local banner
    banner=$(printf "${TIMEPILOT_LOGIN_BANNER_TEMPLATE}" "${DEMO_PASSWORD}")
    grep -q '^TIMEPILOT_DISABLE_SIGNUP=' .env \
        && sed -i "s|^TIMEPILOT_DISABLE_SIGNUP=.*|TIMEPILOT_DISABLE_SIGNUP=${TIMEPILOT_DISABLE_SIGNUP}|" .env \
        || echo "TIMEPILOT_DISABLE_SIGNUP=${TIMEPILOT_DISABLE_SIGNUP}" >> .env
    grep -q '^TIMEPILOT_LOGIN_BANNER=' .env \
        && sed -i "s|^TIMEPILOT_LOGIN_BANNER=.*|TIMEPILOT_LOGIN_BANNER=${banner}|" .env \
        || echo "TIMEPILOT_LOGIN_BANNER=${banner}" >> .env
}
run_step "set demo-mode env vars" check_demo_env step_demo_env

### 6. Publish the app port to localhost via an override file (upstream compose.yml deliberately keeps it internal-only). ###
### Using an override, not editing docker-compose.yml directly, so this survives `git pull` / image updates. ###
### The `ports:` mapping alone isn't enough: docker-compose.yml's `internal` network has `internal: true`, ###
### which blocks Docker's NAT/port-publish machinery for any container solely on it. Fix: attach timepilot ###
### to a second, non-internal network too (postgres stays untouched, still internal-only). ###
### Also passes TIMEPILOT_DISABLE_SIGNUP/TIMEPILOT_LOGIN_BANNER through, since docker-compose.yml ###
### doesn't reference them upstream — .env alone wouldn't reach the container without this. ###
check_override() {
    [[ -f /opt/TimePilot/docker-compose.override.yml ]] \
      && grep -q "proxy" /opt/TimePilot/docker-compose.override.yml \
      && grep -q "TIMEPILOT_DISABLE_SIGNUP" /opt/TimePilot/docker-compose.override.yml
}
step_override() {
    cat > /opt/TimePilot/docker-compose.override.yml <<'EOF'
networks:
  proxy:
    internal: false

services:
  timepilot:
    ports:
      - "127.0.0.1:5170:5170"
    networks:
      - internal
      - proxy
    environment:
      TIMEPILOT_DISABLE_SIGNUP: ${TIMEPILOT_DISABLE_SIGNUP}
      TIMEPILOT_LOGIN_BANNER: ${TIMEPILOT_LOGIN_BANNER}
EOF
}
run_step "add port-publish + network override" check_override step_override

### 7. Bring up the stack — docker compose up -d is naturally idempotent, always safe to re-run ###
check_compose_up() { false; }
step_compose_up() { cd /opt/TimePilot && docker compose pull && docker compose up -d; }
run_step "docker compose up" check_compose_up step_compose_up

check_healthcheck() { curl -fsS http://127.0.0.1:5170/healthz >/dev/null 2>&1; }
step_healthcheck() {
    for i in {1..12}; do
        if curl -fsS http://127.0.0.1:5170/healthz >/dev/null 2>&1; then return 0; fi
        sleep 5
    done
    return 1
}
run_step "wait for TimePilot healthz" check_healthcheck step_healthcheck

### 8. Cloudflare credentials ###
check_cf_creds() { [[ -f /root/.secrets/cloudflare.ini ]] && grep -qF "dns_cloudflare_api_token = ${CF_API_TOKEN}" /root/.secrets/cloudflare.ini; }
step_cf_creds() {
    mkdir -p /root/.secrets
    cat > /root/.secrets/cloudflare.ini <<EOF
dns_cloudflare_api_token = ${CF_API_TOKEN}
EOF
    chmod 600 /root/.secrets/cloudflare.ini
}
run_step "write Cloudflare credentials" check_cf_creds step_cf_creds

### 9. Sync the DNS A record to this box's public IP via Cloudflare API — no manual DNS step needed ###
CF_API="https://api.cloudflare.com/client/v4"

cf_zone_id() {
    curl -fsS -H "Authorization: Bearer ${CF_API_TOKEN}" -H "Content-Type: application/json" \
        "${CF_API}/zones?name=${CF_ZONE_NAME}" \
      | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['result'][0]['id'])" 2>/dev/null
}

cf_record_id() {
    local zone_id="$1"
    curl -fsS -H "Authorization: Bearer ${CF_API_TOKEN}" -H "Content-Type: application/json" \
        "${CF_API}/zones/${zone_id}/dns_records?type=A&name=${DOMAIN}" \
      | python3 -c "import sys,json; d=json.load(sys.stdin); r=d['result']; print(r[0]['id'] if r else '')" 2>/dev/null
}

cf_record_content() {
    local zone_id="$1"
    curl -fsS -H "Authorization: Bearer ${CF_API_TOKEN}" -H "Content-Type: application/json" \
        "${CF_API}/zones/${zone_id}/dns_records?type=A&name=${DOMAIN}" \
      | python3 -c "import sys,json; d=json.load(sys.stdin); r=d['result']; print(r[0]['content'] if r else '')" 2>/dev/null
}

check_dns_record() {
    local public_ip zone_id
    public_ip=$(curl -fsS -m 10 https://ifconfig.me) || return 1
    zone_id=$(cf_zone_id) || return 1
    [[ -n "${zone_id}" ]] || return 1
    [[ "$(cf_record_content "${zone_id}")" == "${public_ip}" ]]
}

step_dns_record() {
    local public_ip zone_id record_id payload
    public_ip=$(curl -fsS -m 10 https://ifconfig.me)
    zone_id=$(cf_zone_id)
    [[ -n "${zone_id}" ]] || { echo "Could not find Cloudflare zone ${CF_ZONE_NAME} — check the token's zone access"; return 1; }
    record_id=$(cf_record_id "${zone_id}")
    payload="{\"type\":\"A\",\"name\":\"${DOMAIN}\",\"content\":\"${public_ip}\",\"ttl\":300,\"proxied\":${CF_PROXIED}}"

    if [[ -n "${record_id}" ]]; then
        curl -fsS -X PATCH -H "Authorization: Bearer ${CF_API_TOKEN}" -H "Content-Type: application/json" \
            "${CF_API}/zones/${zone_id}/dns_records/${record_id}" --data "${payload}" >/dev/null
    else
        curl -fsS -X POST -H "Authorization: Bearer ${CF_API_TOKEN}" -H "Content-Type: application/json" \
            "${CF_API}/zones/${zone_id}/dns_records" --data "${payload}" >/dev/null
    fi
}
run_step "sync DNS A record via Cloudflare API" check_dns_record step_dns_record

### 10. Obtain cert — only if not already valid. DNS-01 uses a TXT record, independent of the A record above, so no wait needed here. ###
check_cert_valid() {
    [[ -f /etc/letsencrypt/live/${DOMAIN}/fullchain.pem ]] \
      && openssl x509 -checkend 604800 -noout -in /etc/letsencrypt/live/${DOMAIN}/fullchain.pem >/dev/null 2>&1
}
step_cert() {
    certbot certonly \
      --dns-cloudflare \
      --dns-cloudflare-credentials /root/.secrets/cloudflare.ini \
      --dns-cloudflare-propagation-seconds 30 \
      -d "${DOMAIN}" \
      -m "${LE_EMAIL}" \
      --agree-tos --non-interactive
}
run_step "obtain Let's Encrypt cert" check_cert_valid step_cert

### 11. Nginx reverse proxy config ###
check_nginx_config() { [[ -L /etc/nginx/sites-enabled/timepilot ]] && nginx -t >/dev/null 2>&1; }
step_nginx_config() {
    cat > /etc/nginx/sites-available/timepilot <<EOF
# Port 80 is intentionally not served — the firewall only allows 22 and 443,
# so there's nothing to redirect from an http:// hit anyway.
server {
    listen 443 ssl;
    server_name ${DOMAIN};

    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5170;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
    ln -sf /etc/nginx/sites-available/timepilot /etc/nginx/sites-enabled/timepilot
    rm -f /etc/nginx/sites-enabled/default
    nginx -t
    systemctl reload nginx
}
run_step "configure nginx" check_nginx_config step_nginx_config

### 12. Renewal hook ###
check_renew_hook() { [[ -x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh ]]; }
step_renew_hook() {
    cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh <<'EOF'
#!/bin/sh
systemctl reload nginx
EOF
    chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
}
run_step "install renewal hook" check_renew_hook step_renew_hook

### 13. Daily ephemeral reset — wipes the DB (fresh schema), reseeds demo data, cleans logs/temp files ###
check_daily_reset() {
    [[ -x /opt/TimePilot/daily-reset.sh ]] || return 1
    [[ -f /etc/cron.d/timepilot-demo-reset ]] || return 1
    grep -qF "${TIMEPILOT_LOGIN_BANNER_TEMPLATE}" /opt/TimePilot/daily-reset.sh || return 1
    grep -qF "\"${DEMO_USERNAME}\"" /opt/TimePilot/daily-reset.sh || return 1
}
step_daily_reset() {
    cat > /opt/TimePilot/daily-reset.sh <<EOF
#!/usr/bin/env bash
set -uo pipefail
cd /opt/TimePilot

# Generate a fresh demo password for today and splice it into the login banner
NEW_PASSWORD=\$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 12)
BANNER=\$(printf "${TIMEPILOT_LOGIN_BANNER_TEMPLATE}" "\${NEW_PASSWORD}")
sed -i "s|^TIMEPILOT_LOGIN_BANNER=.*|TIMEPILOT_LOGIN_BANNER=\${BANNER}|" .env

# Full wipe: tear down and drop the postgres volume so the app recreates its schema from scratch,
# same as a brand-new install. (docker compose down -v only touches this project's own volumes.)
docker compose down -v
docker compose up -d

# Wait for the app to report healthy before reseeding
for i in {1..24}; do
    curl -fsS http://127.0.0.1:5170/healthz >/dev/null 2>&1 && break
    sleep 5
done

docker compose exec -T timepilot python sample_data.py --username "${DEMO_USERNAME}" --password "\${NEW_PASSWORD}" --force

# Clean host-level logs and temp data
truncate -s 0 /var/log/timepilot-init.log /var/log/timepilot-demo-reset.log 2>/dev/null || true
find /tmp -mindepth 1 -exec rm -rf {} + 2>/dev/null || true
docker system prune -f >/dev/null 2>&1 || true
journalctl --vacuum-time=1d >/dev/null 2>&1 || true
EOF
    chmod 700 /opt/TimePilot/daily-reset.sh

    cat > /etc/cron.d/timepilot-demo-reset <<'EOF'
# Wipes the DB, reseeds demo data, and cleans logs/temp files daily so the box stays ephemeral.
0 0 * * * root /opt/TimePilot/daily-reset.sh >> /var/log/timepilot-demo-reset.log 2>&1
EOF
    chmod 600 /etc/cron.d/timepilot-demo-reset

    # Seed it once now too, so there's demo data immediately rather than waiting for midnight
    # (no wipe needed here — the DB was just created fresh moments ago by the earlier compose-up step)
    cd /opt/TimePilot && docker compose exec -T timepilot python sample_data.py --username "${DEMO_USERNAME}" --password "${DEMO_PASSWORD}" --force
}
run_step "schedule daily ephemeral reset" check_daily_reset step_daily_reset

### 14. Final verification (always runs, cheap, no state to guard) ###
sleep "${DNS_PROPAGATION_BUFFER}"
if curl -fsSk "https://${DOMAIN}/healthz" >/dev/null 2>&1; then
    notify "TimePilot setup: COMPLETE" "https://${DOMAIN}/ is live." "tada"
    echo "Done. Visit https://${DOMAIN}/"
else
    notify "TimePilot setup: FAILED" "All steps reported OK but https://${DOMAIN}/healthz is not responding." "rotating_light"
    exit 1
fi

### 15. Delete this script from disk after a clean run — it carries CF_API_TOKEN/DEMO_PASSWORD in plaintext. ###
### cloudflare.ini in /root/.secrets is left in place intentionally (certbot's renewal timer needs it). ###
### Deferred via systemd-run so the delete happens in a separate process after this one has fully exited — ###
### no risk of racing bash's own read of the still-running script. ###
notify "TimePilot setup: cleanup" "Deleting init script from disk in 15s (secrets stay only in /root/.secrets)." "broom"
SCRIPT_PATH="$(readlink -f "$0" 2>/dev/null || echo "$0")"
if [[ -f "${SCRIPT_PATH}" ]]; then
    systemd-run --on-active=15 --unit="timepilot-init-cleanup" --description="Delete TimePilot init script" \
        -- shred -u -- "${SCRIPT_PATH}"
fi
exit 0
