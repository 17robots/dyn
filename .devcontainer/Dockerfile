FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git build-essential python3 clang-19 llvm-19-dev lld-19 \
    bubblewrap libseccomp2 pkg-config just && rm -rf /var/lib/apt/lists/*
# Runtime only; generated Dyn parser is checked into the workspace.
RUN git clone --depth 1 --branch v0.25.8 https://github.com/tree-sitter/tree-sitter.git /tmp/tree-sitter \
    && test "$(git -C /tmp/tree-sitter rev-parse HEAD)" = f2f197b6b27ce75c280c20f131d4f71e906b86f7 \
    && make -C /tmp/tree-sitter install PREFIX=/usr/local \
    && rm -rf /tmp/tree-sitter && ldconfig
RUN ln -s /usr/bin/clang-19 /usr/local/bin/clang \
    && ln -s /usr/bin/ld.lld-19 /usr/local/bin/ld.lld \
    && ln -s /usr/bin/wasm-ld-19 /usr/local/bin/wasm-ld
ENV LLVM_CONFIG=llvm-config-19 CLANG=clang-19
USER ubuntu
