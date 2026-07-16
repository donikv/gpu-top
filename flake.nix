{
  description = "htop-style GPU monitor with docker container attribution, plus a client-server web dashboard";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems
        (system: f nixpkgs.legacyPackages.${system});
      version = "0.2.0";
    in
    {
      packages = forAllSystems (pkgs: rec {
        # TUI + agent: zero Python deps, one derivation providing both
        # `gpu-top` and `gpu-top-agent`.
        gpu-top = pkgs.python3Packages.buildPythonApplication {
          pname = "gpu-top";
          inherit version;
          pyproject = true;
          src = ./.;
          build-system = [ pkgs.python3Packages.hatchling ];
          # Runtime deps are deliberately unwrapped:
          #  - nvidia-smi must come from the host driver
          #    (/run/current-system/sw/bin via hardware.nvidia), never a pinned one
          #  - docker CLI from the host, so it matches the running daemon
          meta = {
            description = "htop-style GPU monitor with docker container attribution";
            mainProgram = "gpu-top";
            platforms = [ "x86_64-linux" "aarch64-linux" ];
          };
        };

        # The built React bundle. When web/package-lock.json changes, update
        # npmDepsHash: set it to nixpkgs.lib.fakeHash, build once, and paste
        # the hash from the error message (see DEPLOY.md).
        gpu-top-web = pkgs.buildNpmPackage {
          pname = "gpu-top-web";
          inherit version;
          src = ./web;
          npmDepsHash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
          installPhase = ''
            runHook preInstall
            cp -r dist $out
            runHook postInstall
          '';
        };

        # Central server: FastAPI app with the web bundle baked in.
        gpu-top-server = pkgs.python3Packages.buildPythonApplication {
          pname = "gpu-top-server";
          inherit version;
          pyproject = true;
          src = ./.;
          build-system = [ pkgs.python3Packages.hatchling ];
          dependencies = with pkgs.python3Packages; [
            fastapi
            uvicorn
            ldap3
            itsdangerous
          ];
          postPatch = ''
            cp -r ${gpu-top-web}/. src/gpu_top/server/static/
          '';
          meta = {
            description = "gpu-top central server: metrics receiver + web dashboard";
            mainProgram = "gpu-top-server";
            platforms = [ "x86_64-linux" "aarch64-linux" ];
          };
        };

        default = gpu-top;
      });

      apps = forAllSystems (pkgs:
        let
          pkgSet = self.packages.${pkgs.stdenv.hostPlatform.system};
        in
        {
          default = {
            type = "app";
            program = nixpkgs.lib.getExe pkgSet.gpu-top;
          };
          agent = {
            type = "app";
            program = "${pkgSet.gpu-top}/bin/gpu-top-agent";
          };
          server = {
            type = "app";
            program = nixpkgs.lib.getExe pkgSet.gpu-top-server;
          };
        });

      overlays.default = final: prev: {
        gpu-top = self.packages.${final.stdenv.hostPlatform.system}.default;
        gpu-top-server = self.packages.${final.stdenv.hostPlatform.system}.gpu-top-server;
      };

      # NixOS module for the push agent: import this on each GPU machine.
      #   services.gpu-top-agent = {
      #     enable = true;
      #     url = "http://zver0.zesoi.fer.hr:8000";
      #     tokenFile = "/etc/gpu-top/agent-token";   # written once, chmod 600
      #   };
      nixosModules.agent = { config, lib, pkgs, ... }:
        let
          cfg = config.services.gpu-top-agent;
        in
        {
          options.services.gpu-top-agent = {
            enable = lib.mkEnableOption "gpu-top metrics push agent";

            package = lib.mkOption {
              type = lib.types.package;
              default = self.packages.${pkgs.stdenv.hostPlatform.system}.gpu-top;
              defaultText = "gpu-top from this flake";
              description = "Package providing the gpu-top-agent binary.";
            };

            serverName = lib.mkOption {
              type = lib.types.str;
              default = config.networking.hostName;
              defaultText = "config.networking.hostName";
              description = "Display name of this machine in the dashboard.";
            };

            url = lib.mkOption {
              type = lib.types.str;
              example = "http://zver0.zesoi.fer.hr:8000";
              description = "Base URL of the central gpu-top server.";
            };

            tokenFile = lib.mkOption {
              type = with lib.types; nullOr str;
              default = null;
              example = "/etc/gpu-top/agent-token";
              description = ''
                Path to a root-owned file containing the agent bearer token
                (recommended: the token never enters the world-readable nix
                store). Create it once with:
                  install -m 600 /dev/null /etc/gpu-top/agent-token
                  printf '%s' "THE-TOKEN" > /etc/gpu-top/agent-token
              '';
            };

            token = lib.mkOption {
              type = with lib.types; nullOr str;
              default = null;
              description = "Inline token. WARNING: ends up world-readable in /nix/store; prefer tokenFile.";
            };

            interval = lib.mkOption {
              type = lib.types.str;
              default = "5.0";
              description = "Seconds between samples (TOML float literal).";
            };
          };

          config = lib.mkIf cfg.enable {
            assertions = [{
              assertion = (cfg.token != null) != (cfg.tokenFile != null);
              message = "services.gpu-top-agent: set exactly one of `token` or `tokenFile`.";
            }];

            environment.etc."gpu-top/agent.toml" = {
              mode = "0600";
              text = ''
                [agent]
                server_name = "${cfg.serverName}"
                url = "${cfg.url}"
                ${lib.optionalString (cfg.token != null) ''token = "${cfg.token}"''}
                interval = ${cfg.interval}
              '';
            };

            systemd.services.gpu-top-agent = {
              description = "gpu-top metrics push agent";
              wantedBy = [ "multi-user.target" ];
              wants = [ "network-online.target" ];
              after = [ "network-online.target" ];
              serviceConfig = {
                ExecStart = "${cfg.package}/bin/gpu-top-agent -c /etc/gpu-top/agent.toml";
                Restart = "always";
                RestartSec = 5;
                # nvidia-smi and the docker CLI deliberately come from the
                # host system profile (see the gpu-top package comment).
                Environment =
                  [ "PATH=/run/current-system/sw/bin" ]
                  ++ lib.optional (cfg.tokenFile != null)
                    "GPU_TOP_AGENT_TOKEN_FILE=${cfg.tokenFile}";
              };
            };
          };
        };

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: [
              ps.hatchling ps.fastapi ps.uvicorn ps.ldap3 ps.itsdangerous
              ps.pytest ps.httpx
            ]))
            pkgs.nodejs_22
          ];
        };
      });
    };
}
