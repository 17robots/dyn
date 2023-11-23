{ pkgs ? import <nixpkgs> { } }:
pkgs.mkShell
{
    name = "dyn";

    nativeBuildInputs = with pkgs; [
        pkgconfig
        ninja
        clang_16
        meson
    ]
} 
