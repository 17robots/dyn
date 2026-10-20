# Target benchmark evidence

All nine benchmark jobs passed on PR #122 head `6bc0665ead457b5271161fe4bb28af6f3e11e401`.
Each executable hash and every sample checksum were verified. Raw JSON includes
seven samples after one warmup, sizes, compiler hash and runner metadata.

Values below are median milliseconds. Machines differ; these rows are not
architecture speed comparisons. Browser timings include page creation and Wasm
compilation; WASI includes Node startup and module compilation. QEMU is emulation.

|Target|Execution|Fibonacci|Hash|Matrix multiply|Points|Sieve|
|---|---|---:|---:|---:|---:|---:|
|aarch64-linux|Native|369.6|99.0|123.9|35.5|361.1|
|aarch64-macos|Native|531.5|170.2|119.2|29.3|322.6|
|aarch64-windows|Native|517.4|107.6|130.6|43.8|375.9|
|riscv64-linux|QEMU|9778.6|204.0|3171.0|488.3|1630.2|
|wasm32-browser|Chromium|829.7|400.9|1077.5|327.5|2685.7|
|wasm32-wasi|Node WASI|1920.4|194.6|1406.4|466.9|2034.4|
|x86_64-linux|Native|60.0|133.9|119.4|22.3|272.0|
|x86_64-macos|Native|66.9|135.1|169.0|41.6|701.8|
|x86_64-windows|Native|224.6|106.1|176.3|16.8|192.0|

[CI run](https://github.com/17robots/dyn/actions/runs/39455712174).
