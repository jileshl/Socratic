#!/usr/bin/env bash
# ==============================================================================
# Deploy Socratic Tutor Package to Production
#
# Usage:
#   ./scripts/deploy_prod.sh [PROD_HOST] [PROD_DIR]
#
# Defaults:
#   PROD_HOST = socratic
#   PROD_DIR  = socratic (relative to remote user's home: ~/socratic)
# ==============================================================================
set -euo pipefail

PROD_HOST="${1:-${PROD_HOST:-socratic}}"
PROD_DIR="${2:-${PROD_DIR:-socratic}}"
DIST_DIR="${DIST_DIR:-dist}"
PACKAGE_NAME="${PACKAGE_NAME:-socratic-deploy.tar.gz}"
PACKAGE_PATH="${DIST_DIR}/${PACKAGE_NAME}"

# If PROD_DIR was expanded by the local shell (e.g. ~/socratic -> /Users/idda/socratic on macOS),
# convert it back to a relative path so it creates ~/socratic on the remote Linux host.
if [[ -n "${HOME:-}" && "$PROD_DIR" == "$HOME"* ]]; then
    REL_PATH="${PROD_DIR#$HOME/}"
    if [[ -n "$REL_PATH" ]]; then
        PROD_DIR="$REL_PATH"
    fi
fi

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: $0 [PROD_HOST] [PROD_DIR]"
    echo ""
    echo "Arguments:"
    echo "  PROD_HOST   SSH host or alias (default: 'socratic')"
    echo "  PROD_DIR    Remote directory for deployment (default: '~/socratic')"
    echo ""
    echo "Environment overrides:"
    echo "  PROD_HOST, PROD_DIR, DIST_DIR, PACKAGE_NAME"
    exit 0
fi

echo "============================================================"
echo " Socratic Tutor: Deploying to Production"
echo " Host:      $PROD_HOST"
echo " Directory: $PROD_DIR"
echo " Package:   $PACKAGE_PATH"
echo "============================================================"

# 1. Build package if not present
if [ ! -f "$PACKAGE_PATH" ]; then
    echo "==> Package not found at $PACKAGE_PATH. Creating package..."
    make package
fi

# 2. Verify SSH connectivity
echo "==> Checking SSH connection to $PROD_HOST..."
if ! ssh -o ConnectTimeout=10 "$PROD_HOST" "echo 'SSH connection verified.'" >/dev/null 2>&1; then
    echo "==> Testing SSH directly (you may be prompted for authentication)..."
    ssh -o ConnectTimeout=10 "$PROD_HOST" "echo 'SSH connection verified.'"
fi

# 3. Create target directory on remote host
echo "==> Ensuring remote directory $PROD_DIR exists..."
ssh "$PROD_HOST" "mkdir -p $PROD_DIR"

# 4. Copy package to remote host
echo "==> Uploading $PACKAGE_PATH to $PROD_HOST:$PROD_DIR/..."
scp "$PACKAGE_PATH" "$PROD_HOST:$PROD_DIR/$PACKAGE_NAME"

# 5. Extract and start docker-compose on remote host
echo "==> Unpacking and launching services on $PROD_HOST..."
ssh -t "$PROD_HOST" bash <<REMOTE_SCRIPT
set -euo pipefail
cd "$PROD_DIR"

echo "--> Unpacking deployment package..."
tar -xzf "$PACKAGE_NAME"
rm -f "$PACKAGE_NAME"

# Preserve existing .env or seed from .env.example
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo "--> Creating .env from .env.example..."
        cp .env.example .env
        echo "--> NOTE: Remember to verify your API keys and TEACHER_PIN in $PROD_DIR/.env"
    else
        touch .env
    fi
else
    echo "--> Existing .env found, preserving configuration."
fi

# Detect docker / docker-compose permissions and command
SUDO=""
if ! docker info >/dev/null 2>&1; then
    if sudo docker info >/dev/null 2>&1; then
        SUDO="sudo"
    else
        echo "Error: Docker daemon is not accessible by current user or sudo." >&2
        exit 1
    fi
fi
DOCKER_CMD="\${SUDO:+\$SUDO }docker"

if \$SUDO docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="\$SUDO docker compose"
elif command -v docker-compose >/dev/null 2>&1 || \$SUDO docker-compose --version >/dev/null 2>&1; then
    COMPOSE_CMD="\$SUDO docker-compose"
else
    echo "Error: Neither 'docker compose' nor 'docker-compose' found on target server." >&2
    exit 1
fi

echo "--> Building application image directly with fresh code..."
\$DOCKER_CMD build -f docker/Dockerfile -t socratic-tutor:local .

echo "--> Recreating all containers (--force-recreate) with fresh code..."
\$COMPOSE_CMD -f docker/docker-compose.yml up -d --force-recreate --remove-orphans

echo "--> Checking status..."
sleep 3
\$COMPOSE_CMD -f docker/docker-compose.yml ps

echo "============================================================"
echo " Deployment Complete! Containers recreated with fresh code."
echo " Secured Endpoints:"
echo "   - Student View    : https://socratic.duckdns.org/  (or http://$PROD_HOST/)"
echo "   - Teacher View    : https://socratic.duckdns.org/teacher"
echo "   - Grafana         : https://socratic.duckdns.org/grafana/"
echo "   - Prometheus      : https://socratic.duckdns.org/prometheus/"
echo "============================================================"
REMOTE_SCRIPT

echo "==> Done!"

