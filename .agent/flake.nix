{
  description = "OpenCode autonomous agent environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    ralphy = {
      url = "github:michaelshimeles/ralphy";
      flake = false;
    };
  };

  outputs = { self, nixpkgs, ralphy }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];

      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs {
            inherit system;
          };

          ralphyPkg = pkgs.writeShellScriptBin "ralphy" ''
            exec ${pkgs.bash}/bin/bash ${ralphy}/ralphy.sh "$@"
          '';
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              # Ralphy
              ralphyPkg
              bashInteractive

              # Ralphy dependencies
              git
              jq
              yq-go
              bc

              # Agent tooling
              nodejs_22
              tmux
              gh

              # Useful Unix tools for agents/scripts
              coreutils
              findutils
              gnugrep
              gnused
              gawk
              curl
              rsync
              ripgrep
              fd
              procps
            ];

            shellHook = ''
              echo "Agent environment"
              echo "  ralphy:   $(command -v ralphy)"
              echo "  git:      $(command -v git)"
              echo "  node:     $(node --version)"

              if command -v opencode >/dev/null 2>&1; then
                echo "  opencode: $(command -v opencode)"
              else
                echo
                echo "WARNING: opencode is not currently on PATH."
                echo "Install/expose OpenCode through your normal NixOS/Home Manager config."
              fi
            '';
          };
        });
    };
}
