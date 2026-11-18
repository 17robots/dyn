`settings FIRST SECOND`. Reads JSON settings like `{"name": "web", "port":
8080}` from the file FIRST; if FIRST does not exist, from SECOND instead.
Print `name=web port=8080 from=PATH` (PATH is the file used). If FIRST exists
but cannot be read or is invalid, that is a failure: do not fall back to
SECOND. Also a failure: SECOND missing when needed, invalid JSON, "name" not
a string, "port" not a whole number from 1 to 65535. On failure print one
message, print nothing on standard output, and exit with status 1.
