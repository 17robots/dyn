package main

import "fmt"

const size = 3000
const iterations = 50

func main() {
	inside := 0
	for py := 0; py < size; py++ {
		y0 := float64(py)/float64(size)*2.0 - 1.0
		for px := 0; px < size; px++ {
			x0 := float64(px)/float64(size)*3.0 - 2.0
			x, y := 0.0, 0.0
			n := 0
			for n < iterations && x*x+y*y <= 4.0 {
				next := x*x - y*y + x0
				y = 2.0*x*y + y0
				x = next
				n++
			}
			if n == iterations {
				inside++
			}
		}
	}
	fmt.Println(inside)
}
