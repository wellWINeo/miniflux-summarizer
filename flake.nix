{
  description = "Generate LLM-powered digests and newsletters from Miniflux RSS entries";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        pythonPkgs = pkgs.python312Packages;
        projectName = "miniflux-summarizer";
      in
      {
        packages.default = pythonPkgs.buildPythonPackage {
          pname = projectName;
          version = "0.1.0";
          src = ./.;
          pyproject = true;

          build-system = with pythonPkgs; [
            setuptools
            setuptools-scm
          ];

          dependencies = with pythonPkgs; [
            miniflux
            httpx
            openai
            markdownify
          ];

          nativeCheckInputs = with pythonPkgs; [
            pytestCheckHook
          ];

          meta = {
            description = "Generate LLM-powered digests and newsletters from Miniflux RSS entries";
            mainProgram = projectName;
          };
        };

        apps.default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/${projectName}";
        };

        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            (pythonPkgs.python.withPackages (ps: with ps; [
              miniflux
              httpx
              openai
              markdownify
              pytest
            ]))
          ];
        };
      });
}
