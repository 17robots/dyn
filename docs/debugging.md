# Debugging Dyn programs

Debug builds contain DWARF function and source-line information and retain Dyn's bounded runtime
stack trace. Release builds omit both to keep binaries small. `--debug` is the default.

```sh
dyn build --debug --output build/app path/to/project
gdb build/app
```

Useful GDB commands are `break main`, `break function_name`, `break file.dyn:line`, `run`, `next`,
`step`, `bt`, `frame N`, `info locals`, `print name`, and `disassemble /m function_name`.
Equivalent LLDB commands are `breakpoint set --name main`, `breakpoint set --file file.dyn
--line N`, `run`, `next`, `step`, `bt`, `frame select N`, `frame variable`, `expression name`, and
`disassemble --name function_name --mixed`.

For example:

```text
$ gdb build/app
(gdb) break worker
(gdb) run
(gdb) next
(gdb) info locals
(gdb) print count
```

Debug builds describe statement lines, parameters, source locals, globals, structs, enums, arrays,
pointers, strings, and slices. Payload enums expose a named tag and typed union, allowing
`print value.payload.Variant` instead of decoding raw bytes. Plain release builds omit metadata. `--release --debug-info` retains
DWARF while optimizing and prevents user-function inlining so breakpoints and backtraces remain
useful. Parameters and promoted scalar locals retain SSA value locations when LLVM can describe them; values may still become optimized out after their last use. A variable becomes inspectable after execution reaches its declaration
and can become unavailable after leaving its lexical scope. Values are represented using their
native machine layout; slices and aggregates may be shown as debugger fields rather than Dyn
syntax.

Dyn panic output needs no debugger and reports active functions with declaration locations:

```text
message
stack trace:
  at fail (src/work.dyn:12)
  at main (src/main.dyn:4)
```

Native FFI libraries remain visible through their own debug information. Debugger expression
parsers do not understand Dyn expressions, so use simple variable names, fields, addresses, and
the debugger's C-like casts when inspecting values.
