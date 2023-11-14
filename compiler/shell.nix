with import <nixpkgs> {};
llvmPackages_16.libcxxStdenv.mkDerivation {
    name = "";
    nativeBuildInputs = [ clang-tools ];
    buildInputs = [ premake5 ] ++ lib.optionals
}
