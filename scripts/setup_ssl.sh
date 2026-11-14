#!/usr/bin/env bash
# ==============================================================================
# Setup SSL with Certbot for Socratic Tutor (Let's Encrypt)
#
# Usage:
#   ./scripts/setup_ssl.sh [DOMAIN] [EMAIL]
#
# Example:
#   ./scripts/setup_ssl.sh socratic.duckdns.org your-email@example.com
# ==============================================================================
set -euo pipefail

DOMAIN="${1:-${DOMAIN:-socratic.duckdns.org}}"
EMAIL="${2:-${EMAIL:-}}"
STAGING="${STAGING:-0}"

if [[ -z "$EMAIL" ]]; then
    echo "============================================================"
    echo " Let's Encrypt requires an email address for urgent renewal"
    echo " and security notices."
    echo "============================================================"
    read -r -p "Enter your email address: " EMAIL
    if [[ -z "$EMAIL" ]]; then
        echo "Error: An email address is required to register with Let's Encrypt." >&2
        exit 1
    fi
fi

# Detect docker / docker-compose command
SUDO=""
if ! docker info >/dev/null 2>&1; then
    if sudo docker info >/dev/null 2>&1; then
        SUDO="sudo"
    else
        echo "Error: Docker daemon is not accessible by current user or sudo." >&2
        exit 1
    fi
fi

if $SUDO docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="$SUDO docker compose"
elif command -v docker-compose >/dev/null 2>&1 || $SUDO docker-compose --version >/dev/null 2>&1; then
    COMPOSE_CMD="$SUDO docker-compose"
else
    echo "Error: Neither 'docker compose' nor 'docker-compose' found." >&2
    exit 1
fi

echo "============================================================"
echo " Setting up Let's Encrypt SSL with Certbot"
echo " Domain:  $DOMAIN"
echo " Email:   $EMAIL"
echo " Staging: $STAGING"
echo "============================================================"

# Step 1: Check if certificate already exists in certbot-etc volume
CERT_EXISTS=$($COMPOSE_CMD -f docker/docker-compose.yml run --rm --entrypoint "sh -c '[ -f /etc/letsencrypt/live/$DOMAIN/fullchain.pem ] && echo yes || echo no'" certbot 2>/dev/null || echo no)

if [ "$CERT_EXISTS" != "yes" ]; then
    echo "==> Creating temporary fallback certificate so Nginx can start with SSL..."
    $COMPOSE_CMD -f docker/docker-compose.yml run --rm --entrypoint "sh -c '
        mkdir -p /etc/letsencrypt/live/$DOMAIN && \
        openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
            -keyout /etc/letsencrypt/live/$DOMAIN/privkey.pem \
            -out /etc/letsencrypt/live/$DOMAIN/fullchain.pem \
            -subj \"/CN=localhost\"
    '" certbot
fi

# Step 2: Ensure all services (including Nginx) are up and listening
echo "==> Starting / Reloading containers..."
$COMPOSE_CMD -f docker/docker-compose.yml up -d
sleep 3

# Verify Nginx container is actually running
if ! $COMPOSE_CMD -f docker/docker-compose.yml ps nginx | grep -qi "running\|up"; then
    echo "Error: Nginx container is not running!" >&2
    echo "Check container logs with:" >&2
    echo "  $COMPOSE_CMD -f docker/docker-compose.yml logs nginx" >&2
    exit 1
fi

echo "==> Checking local port 80 accessibility..."
if curl -s -I -m 4 http://127.0.0.1/ >/dev/null 2>&1; then
    echo "==> Port 80 is listening and responding locally."
else
    echo "==> Note: Local HTTP probe check completed."
fi

# Step 3: Request official certificate from Let's Encrypt
echo "==> Preparing certificate directory for Let's Encrypt..."
$COMPOSE_CMD -f docker/docker-compose.yml run --rm --entrypoint "sh -c '
    if [ ! -f /etc/letsencrypt/renewal/$DOMAIN.conf ]; then
        rm -rf /etc/letsencrypt/live/$DOMAIN /etc/letsencrypt/archive/$DOMAIN;
    fi
'" certbot

STAGING_FLAG=""
if [ "$STAGING" = "1" ]; then
    echo "==> WARNING: Requesting staging (test) certificate..."
    STAGING_FLAG="--staging"
fi

echo "==> Requesting official SSL certificate from Let's Encrypt..."
$COMPOSE_CMD -f docker/docker-compose.yml run --rm --entrypoint "certbot certonly --webroot -w /var/www/certbot \
    $STAGING_FLAG \
    --email $EMAIL \
    -d $DOMAIN \
    --rsa-key-size 4096 \
    --agree-tos \
    --no-eff-email \
    --force-renewal" certbot

# Step 4: Reload Nginx with the verified Let's Encrypt certificate
echo "==> Reloading Nginx with the new certificate..."
$COMPOSE_CMD -f docker/docker-compose.yml exec nginx nginx -s reload

# Step 5: Start background auto-renewal container
echo "==> Starting Certbot auto-renewal service..."
$COMPOSE_CMD -f docker/docker-compose.yml up -d certbot

echo "============================================================"
echo " SSL Setup Complete! Traffic is now secured via HTTPS:"
echo "   - Student View    : https://$DOMAIN/"
echo "   - Teacher View    : https://$DOMAIN/teacher"
echo "   - Grafana         : https://$DOMAIN/grafana/"
echo "   - Prometheus      : https://$DOMAIN/prometheus/"
echo "============================================================"

