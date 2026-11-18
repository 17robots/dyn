`concat OUTPUT INPUT...`. Write the bytes of every INPUT, in order, into
OUTPUT (created or replaced). Inputs may be large: stream them, do not load
whole files. Fail if any input cannot be read or the output cannot be written:
print one failure message and exit with status 1.
