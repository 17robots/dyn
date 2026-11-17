`summary SOURCE OUTPUT`. For every file in directory SOURCE whose name ends in
`.txt`, count its lines (newline characters). Create directory OUTPUT if it
does not exist, and write `OUTPUT/summary.txt` with one line `NAME COUNT` per
file (any order) followed by `total COUNT`. Fail if SOURCE cannot be listed, a
file cannot be read, or OUTPUT/summary.txt cannot be written: print one
failure message and exit with status 1.
