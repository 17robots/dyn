package main

import "core:fmt"

SIZE :: 3000
ITERATIONS :: 50

main :: proc() {
	inside := 0
	for py in 0 ..< SIZE {
		y0 := f64(py) / f64(SIZE) * 2.0 - 1.0
		for px in 0 ..< SIZE {
			x0 := f64(px) / f64(SIZE) * 3.0 - 2.0
			x, y := 0.0, 0.0
			n := 0
			for n < ITERATIONS && x * x + y * y <= 4.0 {
				next := x * x - y * y + x0
				y = 2.0 * x * y + y0
				x = next
				n += 1
			}
			if n == ITERATIONS {
				inside += 1
			}
		}
	}
	fmt.println(inside)
}
