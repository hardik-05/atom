#!/bin/bash
# Install one ATOM release on the engine host. Run as root, via SSM:
#
#   install.sh <version> <artifacts-bucket> <public-host>
#
# Idempotent: re-running with the same version re-installs it, and anything
# already in place (the atom user, Caddy, the env file) is left as it is or
# brought to the state below. A release that fails its health check is rolled
# back to the previous one before this script exits non-zero.
set -euo pipefail

VERSION="${1:?version}"
BUCKET="${2:?artifacts bucket}"
PUBLIC_HOST="${3:?public host}"
REGION="ap-south-1"
ROOT=/opt/atom
RELEASE="$ROOT/releases/$VERSION"
MARKER_DIR=/run/atom

log() { echo "[install $(date -u +%H:%M:%S)] $*"; }

# Count this deploy as activity, or the idle timer can stop the instance half way.
install -d -m 0755 "$MARKER_DIR"
date +%s > "$MARKER_DIR/last-activity"

# ------------------------------------------------------------------ user
id atom >/dev/null 2>&1 || useradd --system --home-dir "$ROOT" --shell /sbin/nologin atom
install -d -m 0755 -o root -g root "$ROOT" "$ROOT/releases" /etc/atom
install -d -m 0750 -o atom -g atom /var/log/atom
chown atom:atom "$MARKER_DIR"

# --------------------------------------------------------------- release
log "fetching release $VERSION"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
aws s3 cp --only-show-errors "s3://$BUCKET/releases/$VERSION.tar.gz" "$TMP/release.tar.gz" --region "$REGION"
rm -rf "$RELEASE"
install -d -m 0755 "$RELEASE"
tar -xzf "$TMP/release.tar.gz" -C "$RELEASE"

log "building the virtualenv"
python3.11 -m venv "$RELEASE/.venv"
"$RELEASE/.venv/bin/pip" install --quiet --upgrade pip
# Editable, so the package resolves to THIS release directory — its data/ and
# migrations/ travel with it, and two releases never share a site-packages.
"$RELEASE/.venv/bin/pip" install --quiet -e "$RELEASE"
chown -R root:root "$RELEASE"
chmod -R a+rX "$RELEASE"

# -------------------------------------------------------------- env file
cat > /etc/atom/atom.env <<ENV
# Non-secret settings only. Secrets are SSM parameters under /atom/, read at start.
ATOM_ENV=prod
ATOM_REGION=$REGION
AWS_DEFAULT_REGION=$REGION
ATOM_PUBLIC_BASE_URL=https://$PUBLIC_HOST
ATOM_SECRET_BACKEND=ssm
ATOM_STATIC_DIR=$ROOT/current/web/dist
ATOM_ACTIVITY_MARKER=$MARKER_DIR/last-activity
ATOM_DATA_PROXY_URL=http://127.0.0.1:3128
ENV
chmod 0644 /etc/atom/atom.env

# ----------------------------------------------- idle shutdown, marker path
# The original timer read /var/run/atom-last-activity, which the unprivileged
# engine cannot write — so console use never counted as activity and the
# instance would stop an hour after boot however busy it was.
if [ -f /usr/local/bin/atom-idle-check ]; then
  sed -i "s|^MARKER=.*|MARKER=$MARKER_DIR/last-activity|" /usr/local/bin/atom-idle-check
fi

# ------------------------------------------------------------------ Caddy
if ! command -v caddy >/dev/null 2>&1; then
  log "installing Caddy"
  curl -fsSL "https://caddyserver.com/api/download?os=linux&arch=amd64" -o /usr/local/bin/caddy
  chmod 0755 /usr/local/bin/caddy
  id caddy >/dev/null 2>&1 || useradd --system --home-dir /var/lib/caddy --create-home --shell /sbin/nologin caddy
  install -d -m 0750 -o caddy -g caddy /var/log/caddy /etc/caddy
  cat > /etc/systemd/system/caddy.service <<'UNIT'
[Unit]
Description=Caddy — TLS for the ATOM console
After=network-online.target
Wants=network-online.target

[Service]
User=caddy
Group=caddy
ExecStart=/usr/local/bin/caddy run --environ --config /etc/caddy/Caddyfile
ExecReload=/usr/local/bin/caddy reload --config /etc/caddy/Caddyfile --force
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes
ProtectSystem=full
PrivateTmp=yes
Restart=on-failure
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
UNIT
fi
sed "s|__PUBLIC_HOST__|$PUBLIC_HOST|" "$RELEASE/deploy/Caddyfile.tmpl" > /etc/caddy/Caddyfile
/usr/local/bin/caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
chown caddy:caddy /etc/caddy/Caddyfile

# ---------------------------------------------------------------- switch
PREVIOUS=$(readlink -f "$ROOT/current" 2>/dev/null || true)
install -m 0644 "$RELEASE/deploy/atom.service" /etc/systemd/system/atom.service
ln -sfn "$RELEASE" "$ROOT/current"
systemctl daemon-reload
systemctl enable atom caddy >/dev/null 2>&1
systemctl restart atom
systemctl reload-or-restart caddy

log "health check"
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    log "healthy: $(curl -fsS http://127.0.0.1:8000/api/health)"
    # keep the three newest releases
    ls -1dt "$ROOT"/releases/* | tail -n +4 | xargs -r rm -rf
    exit 0
  fi
  sleep 2
done

log "UNHEALTHY — last engine log lines:"
journalctl -u atom -n 40 --no-pager || true
if [ -n "$PREVIOUS" ] && [ "$PREVIOUS" != "$RELEASE" ]; then
  log "rolling back to $PREVIOUS"
  ln -sfn "$PREVIOUS" "$ROOT/current"
  systemctl restart atom
fi
exit 1
