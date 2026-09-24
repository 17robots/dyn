# Command-line parsing

`std/flags` parses borrowed argument slices against caller-owned option
specifications. `parse(options, arguments, value_storage, positional_storage)`
never allocates. The caller supplies one `Value` slot per option and enough slice
slots for positional arguments. Returned strings borrow arguments or defaults;
result views borrow the supplied output storage.

Long bool options use `--name`; value options accept `--name=value` or
`--name value`. Short options use `-n`; `--` ends option parsing. Structured errors
distinguish unknown options, missing/invalid values, required options, and capacity.
Integer, float, and choice options validate supplied values and defaults.

Completion writes into a caller buffer. See `compiler/std/flags/flags.dyn` and
`tests/stdlib-cli` for the exact constructors and supported syntax.
