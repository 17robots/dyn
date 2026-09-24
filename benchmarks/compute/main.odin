package main
import "core:fmt"
main :: proc() { value: u64 = 1; for i := 0; i < 50000000; i += 1 { value = (value*1664525+1013904223)&0xffffffff }; fmt.println(value) }
