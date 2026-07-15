#!/usr/bin/env bash
# gpu-top deployment — run ON zver0, from the repo root:
#
#   git pull && ./deploy.sh server       deploy/upgrade the dashboard server (here)
#   ./deploy.sh caddy                    put an HTTPS reverse proxy in front (users only)
#   ./deploy.sh agent zver10 [zver11..]  deploy the docker agent to GPU machine(s)
#   ./deploy.sh token                    print the agent token (for NixOS tokenFile)
#   ./deploy.sh status [zver10 ...]      server container state (+ named agents)
#
# The docker agent is the "for now" deployment; the tidier endgame per machine
# is the flake's NixOS module (services.gpu-top-agent) with the same token file.
#
# `caddy` is only the USER-facing TLS entrypoint. Agents keep pushing straight
# to the server on :8000 over the local network — this proxy does not touch
# that path.
#
# One-time setup on this machine (as root):
#   mkdir -p /etc/gpu-top && chown ipg /etc/gpu-top

CONFIG_TEMPLATE="examples/server-ipg.toml"
LDAP_CA_SOURCE=~/certs-2026/ipg-ldap-ca.crt
PUBLIC_URL="http://zver0.zesoi.fer.hr:8000"

# --- agent deployment ---
SSH_PORT="443"                 # zver machines run sshd on 443
SSH_USER="ipg"
HOST_SUFFIX=".zesoi.fer.hr"
AGENT_GPU_FLAG="--device=nvidia.com/gpu=all"   # NixOS CDI; use "--gpus all" elsewhere
AGENT_DOCKER_SOCK="yes"        # mount docker.sock for container names (root-equiv on host)

# --- caddy HTTPS proxy (browser users) ---
CADDY_DOMAIN="zver0.zesoi.fer.hr"
CADDY_PORT="8443"              # NOT 443 (sshd) and NOT 6443 (phpldapadmin)
CADDY_DIR=~/caddy              # Caddyfile + web cert live here
LDAP_CA_KEY=~/certs-2026/ipg-ldap-ca.key   # signs the web cert (same CA as LDAP)
GPU_NET="gpu-top-net"          # shared user-defined net: caddy -> gpu-top-server by name

set -euo pipefail
cd "$(dirname "$0")"

SECRETS_FILE=".deploy-secrets.env"      # generated here, gitignored
LDAP_SECRET_PATH="/etc/gpu-top/ldap_service_password"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# ssh to a zver machine; ControlMaster multiplexing = one password prompt per host
SSH_OPTS=(-p "$SSH_PORT" -o ControlMaster=auto -o ControlPath="$HOME/.ssh/cm-%r@%h-%p" -o ControlPersist=120)
zssh() { local host=$1; shift; ssh "${SSH_OPTS[@]}" "$SSH_USER@$host$HOST_SUFFIX" "$@"; }

# a user-defined network (unlike the default bridge) gives containers DNS by
# name; idempotent.
ensure_net() { docker network inspect "$GPU_NET" >/dev/null 2>&1 || docker network create "$GPU_NET" >/dev/null; }

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

  # also join the shared proxy network so caddy can reach us by name. Docker
  # DNS re-points to this fresh container automatically, so redeploying the
  # server does NOT require re-running `./deploy.sh caddy`.
  ensure_net
  docker network connect "$GPU_NET" gpu-top-server 2>/dev/null || true

  log "smoke test: /api/me should answer 401 (auth up, not logged in)"
  sleep 2
  code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/me)
  [[ $code == 401 ]] && log "server OK — open $PUBLIC_URL and log in via LDAP" \
                     || die "unexpected HTTP $code from /api/me — check: docker logs gpu-top-server"

  log "next: install the agent token on each GPU machine (see ./deploy.sh token)"
}

# --- agent: everything for one GPU machine, from here --------------------------
deploy_agent() { # $1 = short host name (zver10); also used as the dashboard name
  local name=$1
  load_secrets
  log "=== $name: deploying agent to $SSH_USER@$name$HOST_SUFFIX ==="

  log "[1/5] $name: /etc/gpu-top setup (may prompt for sudo password)"
  ssh -t "${SSH_OPTS[@]}" "$SSH_USER@$name$HOST_SUFFIX" \
    "sudo mkdir -p /etc/gpu-top && sudo chown \$USER /etc/gpu-top"

  log "[2/5] $name: installing token + agent.toml"
  printf '%s' "$AGENT_TOKEN" \
    | zssh "$name" "umask 077 && cat > /etc/gpu-top/agent-token"
  printf '[agent]\nserver_name = "%s"\nurl = "%s"\ninterval = 5.0\n' \
      "$name" "$PUBLIC_URL" \
    | zssh "$name" "umask 077 && cat > /etc/gpu-top/agent.toml"

  log "[3/5] $name: shipping repo (committed tree @ HEAD)"
  git archive --format=tar.gz HEAD \
    | zssh "$name" "mkdir -p ~/gpu-top-src && find ~/gpu-top-src -mindepth 1 -delete && tar xzf - -C ~/gpu-top-src"

  log "[4/5] $name: building agent image"
  zssh "$name" "cd ~/gpu-top-src && docker build --target agent -t gpu-top-agent ."

  local sock=""
  [[ $AGENT_DOCKER_SOCK == yes ]] && sock="-v /var/run/docker.sock:/var/run/docker.sock"
  log "[5/5] $name: starting gpu-top-agent"
  zssh "$name" "
    docker rm -f gpu-top-agent >/dev/null 2>&1 || true
    docker run -d --name gpu-top-agent --restart unless-stopped \
      $AGENT_GPU_FLAG --pid=host \
      -v /etc/gpu-top/agent.toml:/etc/gpu-top/agent.toml:ro \
      -v /etc/gpu-top/agent-token:/etc/gpu-top/agent-token:ro \
      -e GPU_TOP_AGENT_TOKEN_FILE=/etc/gpu-top/agent-token \
      $sock \
      gpu-top-agent >/dev/null
  "

  sleep 3
  log "$name: GPUs visible in the container:"
  zssh "$name" "docker exec gpu-top-agent nvidia-smi -L" \
    || log "WARNING: nvidia-smi failed inside the container on $name (CDI injection?)"
  log "$name: agent log:"
  zssh "$name" "docker logs --tail 3 gpu-top-agent"
  log "=== $name: done — it should appear in the dashboard within ~5s ==="
}

# --- caddy: user-facing HTTPS proxy --------------------------------------------
deploy_caddy() {
  command -v docker >/dev/null || die "docker not found"
  [[ -f $LDAP_CA_SOURCE && -f $LDAP_CA_KEY ]] \
    || die "need the ipg CA at $LDAP_CA_SOURCE and $LDAP_CA_KEY to sign the web cert"

  mkdir -p "$CADDY_DIR/certs"

  # 1. web cert for the dashboard hostname, signed by the SAME CA as LDAP so
  #    clients that already trust ipg-ldap-ca trust this too. Issued once.
  if [[ ! -f $CADDY_DIR/certs/web.crt ]]; then
    log "issuing web cert for $CADDY_DOMAIN from the ipg CA"
    ( umask 077
      openssl req -newkey rsa:4096 -sha256 -nodes \
        -keyout "$CADDY_DIR/certs/web.key" -out /tmp/web.csr \
        -subj "/O=FER IPG ZVERI/CN=$CADDY_DOMAIN"
      openssl x509 -req -in /tmp/web.csr -CA "$LDAP_CA_SOURCE" -CAkey "$LDAP_CA_KEY" \
        -CAcreateserial -days 1825 -sha256 \
        -extfile <(printf "subjectAltName=DNS:%s" "$CADDY_DOMAIN") \
        -out "$CADDY_DIR/certs/web.crt"
      rm -f /tmp/web.csr )
  else
    log "web cert already present at $CADDY_DIR/certs — keeping it"
  fi

  # 2. render the Caddyfile (domain + port are the only variables)
  sed -e "s/__DOMAIN__/$CADDY_DOMAIN/" -e "s/__PORT__/$CADDY_PORT/" \
      examples/Caddyfile > "$CADDY_DIR/Caddyfile"

  # 3. shared user-defined network so the proxy reaches the server by name.
  #    Docker DNS re-resolves after a server redeploy, so this only needs the
  #    server to exist, not to be the same container as last time.
  docker inspect gpu-top-server >/dev/null 2>&1 \
    || die "gpu-top-server isn't running — ./deploy.sh server first"
  ensure_net
  docker network connect "$GPU_NET" gpu-top-server 2>/dev/null || true

  # 4. (re)start caddy
  log "starting caddy on :$CADDY_PORT (network '$GPU_NET' -> gpu-top-server:8000)"
  docker rm -f caddy >/dev/null 2>&1 || true
  docker run -d --name caddy --restart unless-stopped \
    --network "$GPU_NET" -p "$CADDY_PORT:$CADDY_PORT" \
    -v "$CADDY_DIR/Caddyfile":/etc/caddy/Caddyfile:ro \
    -v "$CADDY_DIR/certs":/etc/caddy/certs:ro \
    -v caddy-data:/data \
    caddy:2 >/dev/null

  # 5. smoke test through the proxy (SNI = the real name, connect to localhost)
  sleep 2
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' \
    --resolve "$CADDY_DOMAIN:$CADDY_PORT:127.0.0.1" --cacert "$LDAP_CA_SOURCE" \
    "https://$CADDY_DOMAIN:$CADDY_PORT/api/me" 2>/dev/null || echo ERR)
  if [[ $code == 401 ]]; then
    log "caddy OK (TLS + cert chain verified) — browse https://$CADDY_DOMAIN:$CADDY_PORT"
  else
    log "WARNING: got '$code' via caddy — check: docker logs caddy"
  fi
  log "reminder: set cookie_secure = \"always\" in $CONFIG_TEMPLATE and re-run"
  log "  ./deploy.sh server, and open port $CADDY_PORT in the host firewall."
  log "agents are unaffected: they keep pushing to :8000 on the local network."
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
  log "server (local):"
  docker ps --filter name=gpu-top-server --format '  {{.Names}}  {{.Status}}'
  local name
  for name in "$@"; do
    log "agent ($name):"
    zssh "$name" "docker ps --filter name=gpu-top-agent --format '  {{.Names}}  {{.Status}}'" || true
  done
}

case "${1:-}" in
  server) deploy_server ;;
  caddy)  deploy_caddy ;;
  agent)  shift
          [[ $# -ge 1 ]] || die "usage: ./deploy.sh agent zver10 [zver11 ...]"
          for name in "$@"; do deploy_agent "$name"; done ;;
  token)  show_token ;;
  status) shift || true; status "$@" ;;
  *) sed -n '2,17p' "$0"; exit 1 ;;
esac
