package main
import "fmt"
func main() { var value uint64 = 1; for i := 0; i < 50000000; i++ { value = (value*1664525+1013904223)&0xffffffff }; fmt.Println(value) }
