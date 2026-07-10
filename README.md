# gpu-top

htop-style GPU monitoring for NVIDIA machines, in two flavors:

- **`gpu-top`** — the original local curses TUI: live graphs, process table,
  docker container attribution.
- **`gpu-top-agent` + `gpu-top-server`** — a client-server mode: agents on each
  GPU machine push metrics to a central server with a Grafana-style web
  dashboard (React), LDAP login, per-server filtering, and SQLite-backed
  history.

## Quick start (TUI)

```sh
pip install .
gpu-top
```

## Client-server mode

Each GPU machine runs an agent that pushes samples to the central server:

```toml
# /etc/gpu-top/agent.toml
[agent]
server_name = "hydra1"          # name shown in the dashboard
url = "https://gpu.example.org"
token = "..."
```

The server stores history in SQLite, authenticates dashboard users against
LDAP, and serves the web UI. See **[DEPLOY.md](DEPLOY.md)** for full setup
(Docker images, Nix flake, LDAP, reverse proxy) and
[examples/](examples/) for annotated configs.

## Development

The React app in [web/](web/) is deliberately heavily commented — each file
explains the React concept it demonstrates. `dev/` contains a fake
`nvidia-smi` so everything runs on machines without a GPU; see the bottom of
DEPLOY.md for the three-terminal dev loop.

```sh
.venv/bin/python -m pytest        # backend tests
```
