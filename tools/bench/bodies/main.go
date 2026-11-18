package main

import "fmt"

type Body struct{ x, y, z, vx, vy, vz, mass, charge float64 }

var bodies [1024]Body

func energy(b Body, scale float64) float64 {
	return 0.5*b.mass*(b.vx*b.vx+b.vy*b.vy+b.vz*b.vz)*scale + b.charge*(b.x+b.y+b.z)
}

func main() {
	for i := range bodies {
		v := float64(i % 13)
		bodies[i] = Body{v, v * 2, v * 3, v * 0.5, v * 0.25, v * 0.125, 1 + v, 0.5}
	}
	total := 0.0
	for round := 0; round < 20000; round++ {
		for _, b := range bodies {
			total += energy(b, 1.0+float64(round%3))
		}
	}
	fmt.Println(uint64(total))
}
