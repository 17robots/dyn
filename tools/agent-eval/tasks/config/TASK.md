`config PATH`. PATH is a JSON file like `{"name": "web", "port": 8080}`.
Print `name=web port=8080`. Fail if the file is missing or unreadable, is not
valid JSON, or lacks "name" (a string) or "port" (a number): print one failure
message and exit with status 1.
