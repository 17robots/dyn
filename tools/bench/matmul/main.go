package main

import "fmt"

var a, b, c [65536]float64

func main() {
	n := 256
	for i := 0; i < n*n; i++ {
		a[i] = float64(i%7) * 0.5
		b[i] = float64(i%5) * 0.25
	}
	for round := 0; round < 8; round++ {
		for i := 0; i < n; i++ {
			for j := 0; j < n; j++ {
				sum := 0.0
				for k := 0; k < n; k++ {
					sum += a[i*n+k] * b[k*n+j]
				}
				c[i*n+j] = sum + float64(round)
			}
		}
	}
	total := 0.0
	for _, v := range c {
		total += v
	}
	fmt.Println(uint64(total))
}
