{
  description = "Palimpsest – Wikipedia diff bias verification";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        devShells.default = pkgs.mkShell {
          packages = [ pkgs.python312 pkgs.uv ];
          # Native wheels (pyarrow) need libstdc++ and zlib at runtime.
          LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib pkgs.zlib ];
          UV_PYTHON = "${pkgs.python312}/bin/python3.12";
        };
      }
    );
}
