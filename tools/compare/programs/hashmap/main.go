package main

import "fmt"

const bits = 23
const capacity = 1 << 23
const inserts = 4000000

func slot(key uint64) int {
	return int((key * 11400714819323198485) >> (64 - bits))
}

func main() {
	keys := make([]uint64, capacity)
	counts := make([]uint64, capacity)
	state := uint64(7)
	for n := 0; n < inserts; n++ {
		state = state*6364136223846793005 + 1442695040888963407
		key := (state >> 40) | 1
		at := slot(key)
		for keys[at] != 0 && keys[at] != key {
			at = (at + 1) & (capacity - 1)
		}
		keys[at] = key
		counts[at]++
	}
	found := uint64(0)
	state = 7
	for n := 0; n < 2*inserts; n++ {
		state = state*6364136223846793005 + 1442695040888963407
		key := (state >> 40) | 1
		at := slot(key)
		for keys[at] != 0 && keys[at] != key {
			at = (at + 1) & (capacity - 1)
		}
		if keys[at] == key {
			found += counts[at]
		}
	}
	fmt.Println(found)
}
