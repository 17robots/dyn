package main

import "core:fmt"

COUNT :: 10000000

quicksort :: proc(values: []u64) {
	if len(values) < 2 {
		return
	}
	pivot := values[(len(values) - 1) / 2]
	i, j := 0, len(values) - 1
	for {
		for values[i] < pivot {
			i += 1
		}
		for values[j] > pivot {
			j -= 1
		}
		if i >= j {
			break
		}
		values[i], values[j] = values[j], values[i]
		i += 1
		j -= 1
	}
	quicksort(values[:j + 1])
	quicksort(values[j + 1:])
}

main :: proc() {
	values := make([]u64, COUNT)
	defer delete(values)
	state: u64 = 42
	for &value in values {
		state = state * 6364136223846793005 + 1442695040888963407
		value = state >> 1
	}
	quicksort(values)
	fmt.println(values[0], values[COUNT / 2], values[COUNT - 1])
}
