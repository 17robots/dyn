# Platform Support Policy

## v1 Baseline

Supported:
- Linux x86_64

Current backend target enum:
- `linux_x86_64`

## Unsupported targets

When codegen is asked to build for unsupported configurations, backend code returns `UnsupportedArtifact`.

CLI behavior:
- emits: `error: unsupported target/artifact configuration`

Coverage:
- unsupported configuration test in `src/backend_codegen.zig`
- Linux x86_64 direct/object/executable paths exercised by backend and driver test suites

## Roadmap

Additional targets can be added by extending backend target support and adding conformance tests per target.
