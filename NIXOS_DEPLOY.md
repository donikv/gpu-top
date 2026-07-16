# Deploying the gpu-top agent via dotfiles-nixos (zveri branch)

Concrete changes for `donikv/dotfiles-nixos` (branch `zveri`) to run
`gpu-top-agent` declaratively on the zver fleet, using the flake's
`nixosModules.agent` (see [flake.nix](flake.nix) and DEPLOY.md §4).
Paths below are exact paths in that repo, assuming this repo's changes are
merged to `main` first (so the flake input tracks `main`, no branch pin).

## Scope

- Targets: `zver1` … `zver13` — the machines this flake actually builds
  (`nixosConfigurations` in `dotfiles-nixos/flake.nix`). **`zver0` is not a
  `nixosConfigurations` entry in that repo** (it's managed outside this
  flake) — it doesn't need the agent anyway, since it runs the gpu-top
  *server*, not an agent.
- Every zver host already has `hardware.nvidia` and `virtualisation.docker`
  enabled via `hosts/zver/nvidia/` and `hosts/zver/virtualisation/` (shared
  modules), so `nvidia-smi` and `docker` are already on the host PATH —
  nothing to add there for the agent's sake.
- Assumed target system is `x86_64-linux` (the flake also builds
  `aarch64-linux`, but that's not relevant to this fleet).

## 0. Current state: zver10 and zver13 already run the Docker agent

Before this NixOS module existed, `zver10` and `zver13` were deployed with
`gpu-top`'s `./deploy.sh agent zverN` — the "for now" Docker path (see
DEPLOY.md §3 / the runbook used at the time). That command, run from zver0,
left the following on each of those two hosts:

- `/etc/gpu-top/agent-token` — the bearer token, written **as the `ipg` user**
  (no `sudo`), mode 600. Root-owned it is not, but that's fine: the systemd
  service the NixOS module creates runs as root by default, and root can read
  a 600 file regardless of who owns it. **This file is reusable as-is** —
  nothing to redistribute for these two hosts (see §4).
- `/etc/gpu-top/agent.toml` — a plain file (not nix-managed). The NixOS
  module manages the *same path* via `environment.etc`, so `nixos-rebuild
  switch` simply replaces it with its own symlinked version on first
  activation. Nothing to clean up by hand.
- `~/gpu-top-src` — a git checkout used only to `docker build` the agent
  image; irrelevant to the NixOS path, safe to delete once migrated.
- A running `docker run --name gpu-top-agent --restart unless-stopped ...`
  container, built from the `gpu-top-agent` image.

The other 11 hosts (`zver1`–`zver9`, `zver11`, `zver12`) have no agent
deployed yet — for them, follow §1–§6 below as a normal first-time install
(nothing to migrate, no existing container to stop).

For `zver10` and `zver13`, do §1–§3 as written (they're idempotent — the
Docker deployment never touched `flake.nix` or `hosts/`), **skip §4** for
those two specifically (token already present), then follow **§4b** before
`nixos-rebuild switch` to retire the Docker container cleanly.

## 1. Add the flake input

`flake.nix` (repo root), in the `inputs` block:

```nix
inputs = {
  nixpkgs.url = "github:nixos/nixpkgs/nixos-25.11";
  nixpkgs-unstable.url = "github:nixos/nixpkgs/nixos-unstable";
  home-manager.url = "github:nix-community/home-manager/release-25.11";
  home-manager.inputs.nixpkgs.follows = "nixpkgs";
  nix-flatpak.url = "github:gmodena/nix-flatpak";

  gpu-top.url = "github:donikv/gpu-top";   # NEW
};
```

Plain `github:` ref tracking the default branch, same style as the other
inputs here — no `follows` needed (the module doesn't touch nixpkgs directly
beyond stock `lib`/`pkgs`).

If `donikv/gpu-top` is a **private** repo, nix needs credentials to fetch it:
either add an entry to `nix.extraOptions`/`access-tokens` in `nix.conf` on
each host, or switch the URL to
`git+ssh://git@github.com/donikv/gpu-top` so it reuses the host's existing
SSH key (the zver machines already SSH out for other things).

## 2. Add the shared module

New file `hosts/zver/gpu-top-agent/default.nix` — mirrors the shape of the
existing `hosts/zver/ldap/`, `hosts/zver/nvidia/`, etc. Needs `inputs` in its
arguments (NixOS's module system passes `specialArgs` — which already
includes `inputs` here, per `nixosConfigurations.zverN.specialArgs` in
`flake.nix` — to every module in the tree, not just the entry point, so this
works without extra plumbing):

```nix
{ inputs, ... }:
{
  imports = [ inputs.gpu-top.nixosModules.agent ];

  services.gpu-top-agent = {
    enable = true;
    url = "http://zver0.zesoi.fer.hr:8000";     # agents push HTTP, on the LAN
    tokenFile = "/etc/gpu-top/agent-token";      # written once per host, see §4
    # serverName defaults to config.networking.hostName; overridden per-host
    # below for explicitness (same reason each host already overrides
    # users.ldap.extraConfig instead of relying on an implicit default).
  };
}
```

`url` stays `http://…:8000` deliberately — agents push over the trusted local
network; the HTTPS proxy (`:8443`, see DEPLOY.md §5) is for browser users
only and was never meant to sit in this path.

Wire it into every host by adding one line to `hosts/zver/default.nix`'s
`imports` (alongside `./ldap`, `./nvidia`, `./virtualisation`, …):

```nix
imports = [
  ./fonts
  ./virtualisation
  ./nvidia
  ./locale
  ./ldap
  ./networking
  ./gpu-top-agent        # NEW
];
```

This reaches all 13 hosts transitively, the same way `./ldap` does.

## 3. Per-host display name

Add one line to each `hosts/zverN/default.nix`, right next to the existing
`pam_filter` override (same file, same convention):

```nix
# hosts/zver1/default.nix
imports = [ ../zver ];
users.ldap.extraConfig = ''
    pam_filter memberOf=cn=zver1,ou=Machines,dc=ipg,dc=com
'';
services.gpu-top-agent.serverName = "zver1";   # NEW — repeat per host, zver2.."zver1" -> "zverN"
```

Repeat for `zver2` … `zver13`, substituting the matching name each time.
(If `networking.hostName` is already set to `zverN` per host, the module's
default would resolve to the same value automatically — but setting it
explicitly here costs one line and removes any doubt, matching how this repo
already treats `pam_filter` as a per-host override rather than something
derived implicitly.)

## 4. Distribute the agent token (once per host)

**Skip this for `zver10` and `zver13`** — they already have
`/etc/gpu-top/agent-token` from the earlier Docker deployment (see §0); the
module's `tokenFile` just points at the same path and reads it as-is.

For the other 11 hosts: the token is a shared bearer secret between every
agent and the server's `[agents].tokens` — it must **not** go into this git
repo (unlike, notably, the LDAP bind password currently sitting in
`hosts/zver/ldap/default.nix` — worth fixing separately, but don't repeat
that pattern here). Get it from `gpu-top`'s `deploy.sh` on zver0 and pipe it
straight to each host's root-owned file:

```sh
# on zver0, in the gpu-top checkout:
for h in zver1 zver2 zver3 zver4 zver5 zver6 zver7 zver8 zver9 zver11 zver12; do
  ./deploy.sh token 2>/dev/null | ssh -p 443 ipg@$h.zesoi.fer.hr \
    'sudo mkdir -p /etc/gpu-top && sudo tee /etc/gpu-top/agent-token >/dev/null && sudo chmod 600 /etc/gpu-top/agent-token'
done
```

This only needs to be done once per host (or again if the token ever
rotates); it's independent of nixos-rebuild and survives rebuilds since it
lives outside the nix store.

## 4b. Migrating zver10 / zver13 off the Docker agent

Do this **before** `nixos-rebuild switch` on these two hosts — otherwise, for
a window, you'd have both the Docker container and the new systemd unit
pushing samples under the same `server_name`. The server doesn't crash or
corrupt anything in that scenario (each ingest just does a last-write-wins
update per server row, per `db.py`'s `ingest()`), but it's wasted work and
makes the history briefly noisier than it needs to be, so cut over cleanly
rather than let it self-resolve.

```sh
# on zver10 (repeat on zver13):
ssh -p 443 ipg@zver10.zesoi.fer.hr '
  docker rm -f gpu-top-agent            # stop + remove; restart policy means
                                         # a plain "docker stop" is not enough
  docker rmi gpu-top-agent 2>/dev/null || true   # optional: reclaim image space
  rm -rf ~/gpu-top-src                  # optional: the build checkout, unused by nix
'
```

Then proceed with the normal §5 rebuild for that host
(`nixos-rebuild switch --flake .#zver10`). The gap between stopping the
container and the new systemd unit coming up is a few seconds to however
long the rebuild takes — well under `stale_after` in a typical config, so
expect at most a brief "stale" flash in the dashboard for that host, not a
lost-data event (the agent has no local history of its own to lose; it only
ever held an in-memory push buffer).

This is a **per-host, independent operation** — migrate zver10 and zver13 on
their own schedule, in either order, without touching the other one or any
of the 11 hosts getting a first-time install via §4. There's no fleet-wide
cutover moment required.

## 5. Build and switch

Standard flake rebuild, once the token file exists on a host and the module
changes are committed/merged. From each host itself:

```sh
cd /path/to/dotfiles-nixos && git pull
sudo nixos-rebuild switch --flake .#zver1     # substitute the host's own name
```

Or, from a machine that can reach them all over SSH (mirroring `gpu-top`'s
own `deploy.sh agent` loop pattern):

```sh
for h in zver1 zver2 zver3 zver4 zver5 zver6 zver7 zver8 zver9 zver10 zver11 zver12 zver13; do
  ssh -p 443 ipg@$h.zesoi.fer.hr \
    "cd /path/to/dotfiles-nixos && git pull && sudo nixos-rebuild switch --flake .#$h"
done
```

First build on each host will fetch `github:donikv/gpu-top` and evaluate
`nixosModules.agent` — expect a `flake.lock` update in `dotfiles-nixos`
(commit it) the first time any host runs the rebuild, or run
`nix flake update gpu-top` once beforehand to pin it deliberately.

## 6. Verify

```sh
ssh -p 443 ipg@zver1.zesoi.fer.hr systemctl status gpu-top-agent
ssh -p 443 ipg@zver1.zesoi.fer.hr journalctl -u gpu-top-agent -n 20
```

Look for `pushing to http://zver0.zesoi.fer.hr:8000 as 'zver1' every 5s` with
no repeated 401s, then check the dashboard — the `zver1` section should
appear within one push interval (~5s). Repeat spot-checks for a couple more
hosts; if one host 401s while others succeed, its `/etc/gpu-top/agent-token`
wasn't written (step 4) or doesn't match the server's current token.

For `zver10`/`zver13` specifically, also confirm the old container is
actually gone rather than quietly still running alongside the new unit
(easy to forget if §4b was skipped or ran before the rebuild finished):

```sh
ssh -p 443 ipg@zver10.zesoi.fer.hr docker ps -a --filter name=gpu-top-agent
# want: no output (or "Exited" from `docker rm -f`, never a second live agent)
```

## Rollback

`services.gpu-top-agent.enable = false;` (or remove the `./gpu-top-agent`
import) + `nixos-rebuild switch` stops and removes the unit and the rendered
`/etc/gpu-top/agent.toml`; the token file is untouched (owned by the host,
not by nix) so re-enabling later doesn't require re-distributing it.
