package main

import "fmt"

var text [1048576]uint8

func fnv(d []uint8) uint64 {
	h := uint64(14695981039346656037)
	for _, b := range d {
		h = (h ^ uint64(b)) * 1099511628211
	}
	return h
}

func main() {
	for i := range text {
		text[i] = uint8(i % 251)
	}
	var total uint64
	for round := 0; round < 100; round++ {
		text[round] = uint8(round)
		total += fnv(text[:])
	}
	fmt.Println(total)
}
