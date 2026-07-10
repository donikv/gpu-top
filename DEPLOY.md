# Deploying gpu-top (client–server)

```
┌──────────────┐  push (HTTPS, bearer token)   ┌──────────────────┐
│ GPU server 1 │ ────────────────────────────► │                  │
│ gpu-top-agent│                               │  gpu-top-server  │   LDAP
├──────────────┤                               │  FastAPI+SQLite  │ ◄──────►
│ GPU server 2 │ ────────────────────────────► │  React dashboard │  directory
│ gpu-top-agent│                               └────────▲─────────┘
└──────────────┘                                        │ browser (LDAP login)
                                                     users
```

## Why agents push (instead of the server polling)

- GPU boxes only need **outbound** HTTP(S) — no inbound firewall holes per host.
- Zero central topology config: a new machine appears in the dashboard the
  moment its agent starts pushing with a valid token. Its display name comes
  from its own `agent.toml`.
- Credentials flow one way: each agent holds a bearer token; the server never
  stores per-host credentials.
- Outages are handled agent-side: samples are buffered in memory (about an
  hour's worth) and flushed as one batch when the server comes back, so short
  outages leave no gap in the charts.
- Tradeoff: the server can't distinguish "agent died" from "host died". The
  UI mitigates this with a **stale** badge once nothing has arrived for
  `stale_after` seconds.

## 1. Configuration

Two TOML files; annotated examples live in [examples/](examples/).

**Server** ([examples/server.toml](examples/server.toml)): listen address, SQLite
path, retention, session secret, agent tokens, LDAP settings.

**Agent** ([examples/agent.toml](examples/agent.toml)): the server's display
name (`server_name` — this is the name shown in the dashboard), central server
URL, token, push interval.

Secrets can be kept out of the files with environment variables:
`GPU_TOP_SESSION_SECRET`, `GPU_TOP_SERVICE_PASSWORD` (LDAP service account),
`GPU_TOP_AGENT_TOKEN`. Each also has a `*_FILE` variant
(e.g. `GPU_TOP_SERVICE_PASSWORD_FILE=/run/secrets/ldap_service_password`)
that reads the value from a file — the docker-secrets convention; see
[examples/docker-compose.zver0.yml](examples/docker-compose.zver0.yml) for a
complete example where the password lives only in a root-owned file on the
host.

Generate the session secret and a token:

```sh
python3 -c 'import secrets; print(secrets.token_hex(32))'   # session_secret
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'  # agent token
```

## 2. LDAP setup (search + bind)

The server logs users in by:
1. binding as a **service account**,
2. searching `base_dn` with `user_filter` (default `(uid={username})`) for the DN,
3. binding as that DN with the user's password.

You need a service account that can read your user subtree. Smoke-test your
values with ldapsearch before configuring gpu-top:

```sh
ldapsearch -H ldaps://ldap.example.org \
  -D "cn=gpu-top,ou=services,dc=example,dc=org" -W \
  -b "ou=people,dc=example,dc=org" "(uid=someuser)" dn
```

If that returns exactly one `dn:`, copy the same values into `[auth.ldap]`.
For Active Directory use `user_filter = "(sAMAccountName={username})"` and a
base DN like `CN=Users,DC=corp,DC=example,DC=org`.

For directories that use **STARTTLS on the plain ldap:// port** (OpenLDAP
`ssl start_tls`, NixOS `users.ldap.useTLS`), set `starttls = true`; add
`tls_verify = false` if the clients use `TLS_REQCERT allow` (self-signed
cert). To restrict dashboard access to one group, AND it into the filter the
same way pam_filter does, e.g.
`user_filter = "(&(uid={username})(memberOf=cn=monitoring,ou=Machines,dc=example,dc=org))"`.
A complete real-world example is [examples/server-ipg.toml](examples/server-ipg.toml).

To try LDAP locally first, `docker compose -f dev/ldap-compose.yml up -d`
starts a seeded OpenLDAP (user `alice`/`alice123`) on port 3389.

## 3. Docker

Build both images from the repo root:

```sh
docker build --target server -t gpu-top-server .
docker build --target agent  -t gpu-top-agent  .
```

### Server (on the central host)

```sh
docker run -d --name gpu-top-server \
  -p 8000:8000 \
  -v ./server.toml:/etc/gpu-top/server.toml:ro \
  -v gpu-top-data:/var/lib/gpu-top \
  gpu-top-server
```

The named volume holds the SQLite history so it survives container upgrades.

If the LDAP server runs on the **same host** as the server container (e.g.
zver0), no special networking is needed as long as the `[auth.ldap].uri` uses
the host's FQDN: it resolves to the host's public address, which containers
reach over the default bridge — the same path remote clients use. Only an
slapd bound exclusively to 127.0.0.1 requires `network_mode: host`.
[examples/docker-compose.zver0.yml](examples/docker-compose.zver0.yml) is a
ready-made compose file for that setup, with the bind password supplied as a
docker secret.

### Agent (on each GPU server)

Requires the [NVIDIA container toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).

```sh
docker run -d --name gpu-top-agent \
  --gpus all \
  --pid=host \
  -v ./agent.toml:/etc/gpu-top/agent.toml:ro \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gpu-top-agent
```

- `--gpus all` — injects the driver and `nvidia-smi` into the container.
- `--pid=host` — lets the agent read `/proc/<pid>` of host processes to
  attribute GPU usage to users and containers.
- The **docker.sock mount is optional** and is what resolves container names.
  ⚠️ Access to the docker socket is **root-equivalent on the host** — anyone
  who can talk to it can start privileged containers. If that tradeoff isn't
  acceptable, omit the mount: everything still works, container names just
  show as `?`.

Because the agent needs this much host access anyway, a **bare-metal install
(Nix or pip) is often the better fit for the agent**; the container is a
convenience.

See [docker-compose.example.yml](docker-compose.example.yml) for the compose
equivalent.

## 4. Nix flake

```sh
nix build .#gpu-top          # TUI + agent (zero Python deps)
nix build .#gpu-top-server   # server incl. built web UI
nix run .#agent -- -c /etc/gpu-top/agent.toml
nix run .#server -- -c /etc/gpu-top/server.toml
```

`nvidia-smi` and the docker CLI are deliberately **not** wrapped into the
package — they must come from the host (on NixOS: `hardware.nvidia` and
`virtualisation.docker`), so the tools always match the running driver/daemon.

**Updating `npmDepsHash`:** when `web/package-lock.json` changes, the
`gpu-top-web` build will fail with a hash mismatch. Set `npmDepsHash =
nixpkgs.lib.fakeHash;` (or leave the stale value), run
`nix build .#gpu-top-server`, and paste the `got: sha256-...` value from the
error message into `flake.nix`. The placeholder hash committed initially must
be replaced the same way on first build.

### systemd units (bare-metal)

Agent (`/etc/systemd/system/gpu-top-agent.service`):

```ini
[Unit]
Description=gpu-top agent
After=network-online.target

[Service]
ExecStart=/run/current-system/sw/bin/gpu-top-agent -c /etc/gpu-top/agent.toml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

The server unit is identical with `gpu-top-server -c /etc/gpu-top/server.toml`
plus `StateDirectory=gpu-top` (and point `db_path` at `/var/lib/gpu-top/`).
A proper NixOS module (services.gpu-top.*) is future work.

## 5. Reverse proxy / TLS

Run the server behind a TLS-terminating proxy; the session cookie is set with
`Secure` automatically when the request scheme is https. Caddy:

```
gpu.example.org {
    reverse_proxy localhost:8000
}
```

nginx:

```nginx
server {
    listen 443 ssl;
    server_name gpu.example.org;
    # ssl_certificate ...; ssl_certificate_key ...;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

If TLS is terminated at the proxy, run uvicorn with `--proxy-headers` semantics
by fronting it on localhost only (the default config binds 0.0.0.0 — restrict
`[server].host` to 127.0.0.1 when a proxy is in front).

Agents talk to the same public URL (`url = "https://gpu.example.org"`), so
their pushes are TLS-protected too.

## 6. Local development (no GPU needed)

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[server]'
GPU_TOP_DEV=1 .venv/bin/gpu-top-server -c dev/server-dev.toml   # terminal 1
PATH="$PWD/dev:$PATH" .venv/bin/gpu-top-agent -c dev/agent-dev.toml  # terminal 2
cd web && npm install && npm run dev                             # terminal 3
```

`dev/fake-nvidia-smi` fakes two GPUs with wobbling load;
`dev/server-dev.toml` disables LDAP (`auth.mode = "none"`, hence
`GPU_TOP_DEV=1`). Open http://localhost:5173 and log in with any credentials.
