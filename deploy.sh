#!/usr/bin/env bash
# gpu-top server deployment — run ON the server (zver0), from the repo root:
#
#   git pull && ./deploy.sh server     deploy/upgrade the dashboard server
#   ./deploy.sh token                  print the agent token (for clients' tokenFile)
#   ./deploy.sh status                 show the server container state
#
# Agents are NOT deployed by this script: they are built declaratively on each
# GPU machine via the flake's NixOS module (nixosModules.agent); the only thing
# they need from here is the token printed by `./deploy.sh token`.
#
# One-time setup on this machine (as root):
#   mkdir -p /etc/gpu-top && chown ipg /etc/gpu-top

CONFIG_TEMPLATE="examples/server-ipg.toml"
LDAP_CA_SOURCE=~/certs-2026/ipg-ldap-ca.crt
PUBLIC_URL="http://zver0.zesoi.fer.hr:8000"

set -euo pipefail
cd "$(dirname "$0")"

SECRETS_FILE=".deploy-secrets.env"      # generated here, gitignored
LDAP_SECRET_PATH="/etc/gpu-top/ldap_service_password"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# --- secrets: generated once on this machine, reused on every run -------------
load_secrets() {
  if [[ ! -f $SECRETS_FILE ]]; then
    log "generating $SECRETS_FILE (agent token + session secret)"
    umask 077
    {
      echo "AGENT_TOKEN=$(openssl rand -hex 32)"
      echo "SESSION_SECRET=$(openssl rand -hex 32)"
    } > "$SECRETS_FILE"
  fi
  # shellcheck source=/dev/null
  source "$SECRETS_FILE"
}

# --- server -------------------------------------------------------------------
deploy_server() {
  load_secrets
  [[ -w /etc/gpu-top || ! -e /etc/gpu-top ]] || die \
    "cannot write /etc/gpu-top — one-time fix: sudo mkdir -p /etc/gpu-top && sudo chown $USER /etc/gpu-top"
  mkdir -p /etc/gpu-top

  log "writing /etc/gpu-top/server.toml (from $CONFIG_TEMPLATE)"
  umask 077
  sed -e "s|session_secret = \"FILL-ME\"|session_secret = \"$SESSION_SECRET\"|" \
      -e "s|tokens = \[\"FILL-ME\"\]|tokens = [\"$AGENT_TOKEN\"]|" \
      "$CONFIG_TEMPLATE" > /etc/gpu-top/server.toml

  # LDAP CA for tls_verify=true (config: ca_cert_file = /etc/gpu-top/ldap-ca.crt)
  if [[ ! -f /etc/gpu-top/ldap-ca.crt ]]; then
    log "installing LDAP CA from $LDAP_CA_SOURCE"
    cp "$LDAP_CA_SOURCE" /etc/gpu-top/ldap-ca.crt
  fi

  if [[ -f $LDAP_SECRET_PATH ]]; then
    log "LDAP bind password already present at $LDAP_SECRET_PATH — keeping it"
  else
    read -r -s -p "LDAP bind password for cn=administrator (stored only in $LDAP_SECRET_PATH): " pw
    echo >&2
    [[ -n $pw ]] || die "empty password"
    (umask 077 && printf '%s' "$pw" > "$LDAP_SECRET_PATH")
    unset pw
  fi

  log "building server image (first build downloads node/python base images)"
  docker build --target server -t gpu-top-server .

  log "starting gpu-top-server container"
  docker rm -f gpu-top-server >/dev/null 2>&1 || true
  docker run -d --name gpu-top-server --restart unless-stopped \
    -p 8000:8000 \
    -v /etc/gpu-top/server.toml:/etc/gpu-top/server.toml:ro \
    -v /etc/gpu-top/ldap-ca.crt:/etc/gpu-top/ldap-ca.crt:ro \
    -v "$LDAP_SECRET_PATH":/run/secrets/ldap_service_password:ro \
    -e GPU_TOP_SERVICE_PASSWORD_FILE=/run/secrets/ldap_service_password \
    -v gpu-top-data:/var/lib/gpu-top \
    gpu-top-server >/dev/null

  # join the LDAP container's docker network so uri = ldap://ldap-server
  # resolves container-to-container (host firewall on :389 doesn't apply)
  ldap_net=$(docker inspect ldap-server \
    -f '{{range $k,$_ := .NetworkSettings.Networks}}{{$k}}{{end}}' 2>/dev/null || true)
  if [[ -n ${ldap_net:-} ]]; then
    log "connecting gpu-top-server to docker network '$ldap_net' (ldap-server)"
    docker network connect "$ldap_net" gpu-top-server 2>/dev/null || true
  else
    log "WARNING: no running 'ldap-server' container found - ldap://ldap-server will not resolve"
  fi

  log "smoke test: /api/me should answer 401 (auth up, not logged in)"
  sleep 2
  code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/me)
  [[ $code == 401 ]] && log "server OK — open $PUBLIC_URL and log in via LDAP" \
                     || die "unexpected HTTP $code from /api/me — check: docker logs gpu-top-server"

  log "next: install the agent token on each GPU machine (see ./deploy.sh token)"
}

# --- token: what the clients need ----------------------------------------------
show_token() {
  load_secrets
  log "agent token (matches the server's [agents].tokens):"
  printf '%s\n' "$AGENT_TOKEN"          # token itself on stdout, pipeable
  log "install it on a client (from here) with:"
  log "  ./deploy.sh token | ssh -p 443 ipg@zverN.zesoi.fer.hr \\"
  log "      'sudo mkdir -p /etc/gpu-top && sudo tee /etc/gpu-top/agent-token >/dev/null && sudo chmod 600 /etc/gpu-top/agent-token'"
  log "then set services.gpu-top-agent.tokenFile = \"/etc/gpu-top/agent-token\";"
}

status() {
  docker ps --filter name=gpu-top-server --format '{{.Names}}  {{.Status}}'
}

case "${1:-}" in
  server) deploy_server ;;
  token)  show_token ;;
  status) status ;;
  *) sed -n '2,12p' "$0"; exit 1 ;;
esac
