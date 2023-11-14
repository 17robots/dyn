{
    description = "Dyn build environment nix";

    inputs = {
        nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
        utils.url = "github:numtide/flake-utils";
    };
    outputs = { self, nixpkgs, utils, ... }@inputs:
        utils.lib.eachDefaultSystem(system:
            let
                p = import nixpkgs { inherit system; };
                llvm = p.llvmPackages_16;
            in
            {
                devShell = p.mkShell.override { stdenv = p.clangStdenv; } rec {
                    packages = with p; [
                        bear
                        clang-tools_16
                        gdb
                        llvm.libcxx
                        llvm.libstdcxxClang
                        llvm.libllvm
                        llvm.lldb
                        ninja
                        premake5
                        valgrind
                    ];
                    name = "C";
                };
            }
        );
}
