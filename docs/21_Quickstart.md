# Dyn Quickstart

## Build the CLI

```bash
zig build
```

This installs `dyn` to `zig-out/bin/dyn`.

## Create a program

`main.dyn`

```dyn
module main

main := () i32 => 0
```

## Check the program

```bash
zig build run -- check main.dyn
```

## Build an executable

```bash
zig build run -- build main.dyn -o app.out
```

## Run it

```bash
zig build run -- run main.dyn
```

## Clean intermediate artifacts

```bash
zig build run -- clean
```
