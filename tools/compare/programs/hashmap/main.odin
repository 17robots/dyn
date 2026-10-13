package main

import "core:fmt"

BITS :: 23
CAPACITY :: 1 << 23
INSERTS :: 4000000

slot :: proc(key: u64) -> int {
	return int((key * 11400714819323198485) >> (64 - BITS))
}

main :: proc() {
	keys := make([]u64, CAPACITY)
	counts := make([]u64, CAPACITY)
	defer delete(keys)
	defer delete(counts)
	state: u64 = 7
	for _ in 0 ..< INSERTS {
		state = state * 6364136223846793005 + 1442695040888963407
		key := (state >> 40) | 1
		at := slot(key)
		for keys[at] != 0 && keys[at] != key {
			at = (at + 1) & (CAPACITY - 1)
		}
		keys[at] = key
		counts[at] += 1
	}
	found: u64 = 0
	state = 7
	for _ in 0 ..< 2 * INSERTS {
		state = state * 6364136223846793005 + 1442695040888963407
		key := (state >> 40) | 1
		at := slot(key)
		for keys[at] != 0 && keys[at] != key {
			at = (at + 1) & (CAPACITY - 1)
		}
		if keys[at] == key {
			found += counts[at]
		}
	}
	fmt.println(found)
}
