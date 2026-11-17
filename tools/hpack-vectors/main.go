// Regenerates tests/hpack/vectors.txt. Go's hpack package is vendored, not
// importable: copy $(go env GOROOT)/src/vendor/golang.org/x/net/http2/hpack
// into ./hpack beside this file, add a go.mod naming module "vectors", and
// run `go run . > ../../tests/hpack/vectors.txt`.
//
// Writes HPACK test vectors: random header lists encoded by Go's encoder with
// a 256-byte dynamic table (evictions, size updates, Huffman), one block per
// line as "hex<TAB>name=value|name=value...". With -decode, reads hex blocks
// from stdin and prints what they decode to.
package main

import (
	"bufio"
	"bytes"
	"encoding/hex"
	"flag"
	"fmt"
	"math/rand"
	"os"
	"strings"

	"vectors/hpack"
)

func main() {
	decode := flag.Bool("decode", false, "")
	flag.Parse()
	if *decode {
		d := hpack.NewDecoder(4096, nil)
		scanner := bufio.NewScanner(os.Stdin)
		for scanner.Scan() {
			block, _ := hex.DecodeString(scanner.Text())
			fields, err := d.DecodeFull(block)
			if err != nil {
				fmt.Println("error", err)
				continue
			}
			parts := []string{}
			for _, f := range fields {
				parts = append(parts, f.Name+"="+f.Value)
			}
			fmt.Println(strings.Join(parts, "|"))
		}
		return
	}
	r := rand.New(rand.NewSource(7))
	var buffer bytes.Buffer
	e := hpack.NewEncoder(&buffer)
	e.SetMaxDynamicTableSizeLimit(4096)
	names := []string{":method", ":path", ":authority", ":scheme", "accept", "cookie", "user-agent", "x-trace", "content-type", "x-custom-long-header-name"}
	values := []string{"GET", "POST", "/", "/index.html", "/api/items?page=2", "example.com", "https", "text/html,application/xhtml+xml", "sid=abc123; theme=dark", "Mozilla/5.0 (X11; Linux x86_64)", "", "\x01\xff binary ~"}
	for i := 0; i < 300; i++ {
		if i == 40 {
			e.SetMaxDynamicTableSize(256)
		}
		if i == 200 {
			e.SetMaxDynamicTableSize(0)
		}
		if i == 210 {
			e.SetMaxDynamicTableSize(4096)
		}
		buffer.Reset()
		parts := []string{}
		count := 1 + r.Intn(8)
		for j := 0; j < count; j++ {
			name := names[r.Intn(len(names))]
			value := values[r.Intn(len(values))]
			if r.Intn(5) == 0 {
				value = fmt.Sprintf("v%d-%d", i, r.Intn(1000))
			}
			sensitive := r.Intn(10) == 0
			e.WriteField(hpack.HeaderField{Name: name, Value: value, Sensitive: sensitive})
			parts = append(parts, name+"="+value)
		}
		fmt.Printf("%s\t%s\n", hex.EncodeToString(buffer.Bytes()), hex.EncodeToString([]byte(strings.Join(parts, "|"))))
	}
}
