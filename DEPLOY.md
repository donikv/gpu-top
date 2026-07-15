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

### NixOS module (the recommended way to run agents)

The flake exports `nixosModules.agent`. In the flake that builds your GPU
machines:

```nix
{
  inputs.gpu-top.url = "github:donikv/gpu-top/client-server";  # branch ref; drop /client-server once merged to main

  # in the machine's configuration:
  imports = [ inputs.gpu-top.nixosModules.agent ];

  services.gpu-top-agent = {
    enable = true;
    url = "http://zver0.zesoi.fer.hr:8000";
    # serverName defaults to networking.hostName
    tokenFile = "/etc/gpu-top/agent-token";   # root-owned, mode 600
  };
}
```

Write the token file once per machine (it never enters the nix store):

```sh
install -m 600 /dev/null /etc/gpu-top/agent-token
printf '%s' "THE-TOKEN" > /etc/gpu-top/agent-token
```

The module writes `/etc/gpu-top/agent.toml` and a systemd unit whose PATH is
`/run/current-system/sw/bin`, so nvidia-smi and docker come from the host
system as intended. For non-NixOS bare-metal installs, an equivalent
hand-written unit is a 6-liner: `ExecStart=gpu-top-agent -c
/etc/gpu-top/agent.toml`, `Restart=always`, `WantedBy=multi-user.target`.

The server can run the same way (`gpu-top-server -c ...` +
`StateDirectory=gpu-top`), though the Docker image is the tested path.

## 5. Serving the app over HTTPS (reverse proxy)

Out of the box the server speaks plain HTTP, so **browser logins cross the
network in cleartext**. Put a TLS-terminating reverse proxy in front of the
*user-facing* side before real use. Agents are a separate matter: they push a
bearer token (not a login password) over the trusted local network and are
left on plain `:8000` — the proxy does not touch that path.

### The one-command way (ipg/zver0)

On zver0, `./deploy.sh caddy` does all of the below: signs a web cert for
`zver0.zesoi.fer.hr` with the **same ipg CA** used for LDAP, renders
[examples/Caddyfile](examples/Caddyfile), joins Caddy to the server's docker
network, and starts it on **:8443** (443 is sshd, 6443 is phpLDAPadmin). Then
set `cookie_secure = "always"` in `server.toml` (already the default in
[examples/server-ipg.toml](examples/server-ipg.toml)), re-run `./deploy.sh
server`, and open port 8443 in the host firewall. Users browse
`https://zver0.zesoi.fer.hr:8443`; anyone who already trusts `ipg-ldap-ca`
(the LDAP rollout) gets a clean lock.

Two environment specifics worth knowing: **443 can't be used** (sshd owns it),
and **Let's Encrypt likely can't** — public ACME needs inbound 80/443 from the
internet, which the FER firewall + ssh-on-443 setup blocks; signing with your
own CA sidesteps that entirely. `tls internal` (Caddy's own auto CA) is the
zero-config alternative if you'd rather not reuse the ipg CA.

### The manual way (other environments)

The proxy handles certificates; the gpu-top server keeps speaking HTTP but only
to the proxy.

Three changes turn the plaintext setup into a proper HTTPS one:

1. In `server.toml`, stop exposing the plaintext port and trust the proxy:
   ```toml
   [server]
   host = "127.0.0.1"       # only the proxy (same host) can reach it
   behind_proxy = true      # trust X-Forwarded-Proto from the proxy
   trusted_proxies = "127.0.0.1"   # the proxy's source IP
   cookie_secure = "auto"   # now resolves to Secure, because scheme is https
   ```
   `behind_proxy = true` makes uvicorn honor the proxy's `X-Forwarded-Proto`, so
   `request.url.scheme` becomes `https` and the session cookie is issued with the
   `Secure` flag. If your proxy runs on a **different host/container**, set
   `trusted_proxies` to its IP (uvicorn ignores forwarded headers from untrusted
   sources), or just set `cookie_secure = "always"`.

   In Docker, don't publish 8000 to the world — put the proxy and the server on
   the same docker network and let the proxy reach `server:8000`, or bind the
   published port to localhost (`-p 127.0.0.1:8000:8000`).

2. Point a proxy at it. **Caddy** (gets a Let's Encrypt cert automatically):
   ```
   gpu.example.org {
       reverse_proxy 127.0.0.1:8000
   }
   ```
   Caddy sends `X-Forwarded-Proto` by default. **nginx**:
   ```nginx
   server {
       listen 443 ssl;
       server_name gpu.example.org;
       ssl_certificate     /etc/ssl/gpu.example.org.crt;
       ssl_certificate_key /etc/ssl/gpu.example.org.key;
       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-Proto $scheme;
           proxy_set_header X-Forwarded-For $remote_addr;
       }
   }
   # optional: redirect :80 -> :443
   ```
   On NixOS, `services.caddy.virtualHosts."gpu.example.org".extraConfig =
   "reverse_proxy 127.0.0.1:8000";` is the whole thing (plus opening 80/443 in
   the firewall for the ACME challenge).

3. Point the agents at the HTTPS URL: `url = "https://gpu.example.org"` in each
   `agent.toml` (or `services.gpu-top-agent.url`), and set `SERVER_URL` in
   `deploy.sh` to the same. Their pushes are then TLS-protected too, and the
   agent (stdlib urllib) validates the certificate normally.

Verify: `curl -sI https://gpu.example.org/api/me` should return `401` over TLS,
and the `Set-Cookie` on a login response should include `Secure`.

## 6. Encrypting the LDAP connection

The dashboard authenticates against the same directory as your NixOS clients.
The example config mirrors those clients' `TLS_REQCERT allow` with
`tls_verify = false`, which means the STARTTLS connection is encrypted **but the
server's certificate is not validated** — an attacker who can MITM the
server↔LDAP path could capture the `cn=administrator` bind password. To close
that:

1. Get the CA certificate that signed the LDAP server's cert (on the zver
   clients it may be referenced as `TLS_CACERT /etc/ldap_ssl/ca.crt`). Copy it
   to the monitoring host, e.g. `/etc/gpu-top/ldap-ca.crt`, and mount it into
   the container (`-v /etc/gpu-top/ldap-ca.crt:/etc/gpu-top/ldap-ca.crt:ro`).
2. Flip the config to validate against that CA:
   ```toml
   [auth.ldap]
   uri = "ldaps://zver0.zesoi.fer.hr"   # or keep ldap:// with starttls = true
   starttls = true                      # (drop if you switch to ldaps://)
   tls_verify = true
   ca_cert_file = "/etc/gpu-top/ldap-ca.crt"   # omit to use the system trust store
   ```
`tls_verify = true` also requires the certificate's subject/SAN to match the
`uri` hostname, so use the FQDN the cert was issued for. Test the whole chain
with `ldapsearch` from the monitoring host first (see §2) using `-ZZ` (which
*requires* a valid STARTTLS handshake) — if that succeeds, gpu-top will too.

Also consider swapping `cn=administrator` for a **read-only service account**
that can only search the user subtree: the dashboard only needs to find DNs and
test-bind, never write, so an admin-level bind is more privilege than required.

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
