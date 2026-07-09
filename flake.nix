{
  description = "htop-style GPU monitor with docker container attribution";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems
        (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAllSystems (pkgs: rec {
        gpu-top = pkgs.python3Packages.buildPythonApplication {
          pname = "gpu-top";
          version = "0.1.0";
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
        default = gpu-top;
      });

      apps = forAllSystems (pkgs: {
        default = {
          type = "app";
          program = nixpkgs.lib.getExe self.packages.${pkgs.stdenv.hostPlatform.system}.default;
        };
      });

      overlays.default = final: prev: {
        gpu-top = self.packages.${final.stdenv.hostPlatform.system}.default;
      };

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [ (pkgs.python3.withPackages (ps: [ ps.hatchling ])) ];
        };
      });
    };
}
