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
