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
            markdown
            markdownify
            miniflux
            httpx
            openai
          ];

          nativeCheckInputs = with pythonPkgs; [
            pytestCheckHook
            ruff
            mypy
          ];

          preCheck = ''
            ruff check src/ tests/
            mypy src/
          '';

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
          packages = [ pkgs.uv ];
        };
      });
}
