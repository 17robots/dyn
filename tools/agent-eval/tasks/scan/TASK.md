`scan DIR`. For every file in DIR whose name ends in `.json`, read its "port"
(a whole number). Print `NAME port=N` for each good file, and for each bad
file (unreadable, invalid JSON, missing or bad "port") print its failure
message to standard error and carry on. Finally print `good G bad B`. Exit
with status 1 if DIR cannot be listed (print one message) or if any file was
bad, else 0. The order of the file lines does not matter.
