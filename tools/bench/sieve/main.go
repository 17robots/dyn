package main

import "fmt"

var flags [8000000]uint8

func main() {
	var total uint64
	for round := uint64(0); round < 10; round++ {
		for i := range flags {
			flags[i] = 1
		}
		var count uint64
		for i := 2; i < len(flags); i++ {
			if flags[i] == 1 {
				count++
				for j := i * 2; j < len(flags); j += i {
					flags[j] = 0
				}
			}
		}
		total += count + round
	}
	fmt.Println(total)
}
