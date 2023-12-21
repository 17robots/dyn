{
  description = "";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, utils, ... }@inputs: utils.lib.eachDefaultSystem(
    system:
    let
      p = import nixpkgs { inherit system; };
      llvm = p.llvmPackages_latest;
      in
      {
        devShell = p.mkShell.override { stdenv = p.clangStdenv; } rec {
          packages = with p; [
            gcc
            ninja
            meson
            clang-tools
          ];
          name = "dyn";
        };        
      }
  );
}
