package main

import "core:fmt"

LIMIT :: 100000000

main :: proc() {
	composite := make([]bool, LIMIT + 1)
	defer delete(composite)
	count := 0
	for i in 2 ..= LIMIT {
		if !composite[i] {
			count += 1
			for j := i * i; j <= LIMIT; j += i {
				composite[j] = true
			}
		}
	}
	fmt.println(count)
}
