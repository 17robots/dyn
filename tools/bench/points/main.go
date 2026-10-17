package main

import "fmt"

type Point struct{ x, y int64 }

var points [4096]Point

func step(p, d Point) Point { return Point{(p.x + d.x) % 1000003, (p.y*3 + d.y) % 1000003} }

func main() {
	for i := range points {
		points[i] = Point{int64(i), int64(i * 7)}
	}
	delta := Point{5, 11}
	for round := 0; round < 2000; round++ {
		for i := range points {
			points[i] = step(points[i], delta)
		}
	}
	var total int64
	for _, p := range points {
		total += p.x + p.y
	}
	fmt.Println(total)
}
