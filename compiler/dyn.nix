{ pkgs ? import <nixpkgs> {} }:
pkgs.mkShell {
    nativeBuildInputs = with pkgs.buildPackages; [
        clang_16
        meson
        ninja
    ];
}
