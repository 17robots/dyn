package main

import "fmt"

const count = 10000000

func quicksort(values []uint64) {
	if len(values) < 2 {
		return
	}
	pivot := values[(len(values)-1)/2]
	i, j := 0, len(values)-1
	for {
		for values[i] < pivot {
			i++
		}
		for values[j] > pivot {
			j--
		}
		if i >= j {
			break
		}
		values[i], values[j] = values[j], values[i]
		i++
		j--
	}
	quicksort(values[:j+1])
	quicksort(values[j+1:])
}

func main() {
	values := make([]uint64, count)
	state := uint64(42)
	for i := range values {
		state = state*6364136223846793005 + 1442695040888963407
		values[i] = state >> 1
	}
	quicksort(values)
	fmt.Println(values[0], values[count/2], values[count-1])
}
