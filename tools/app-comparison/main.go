package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"math"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

type Summary struct {
	Records  uint64        `json:"records"`
	Bytes    uint64        `json:"bytes"`
	Latency  uint64        `json:"latency_us"`
	Errors   uint64        `json:"errors"`
	Services [16][4]uint64 `json:"services"`
}

func integer(v any, max float64) (uint64, error) {
	n, ok := v.(float64)
	if !ok || n < 0 || n > max || math.Trunc(n) != n {
		return 0, fmt.Errorf("invalid integer")
	}
	return uint64(n), nil
}
func (s *Summary) add(v any) error {
	obj, ok := v.(map[string]any)
	if !ok {
		return fmt.Errorf("record is not object")
	}
	service, ok := obj["service"].(string)
	if !ok || len(service) != 5 || service[:3] != "svc" || service[3] < '0' || service[3] > '1' || service[4] < '0' || service[4] > '9' {
		return fmt.Errorf("invalid service")
	}
	idx := int(service[3]-'0')*10 + int(service[4]-'0')
	if idx >= 16 {
		return fmt.Errorf("invalid service")
	}
	status, e := integer(obj["status"], 599)
	if e != nil {
		return e
	}
	b, e := integer(obj["bytes"], 9007199254740991)
	if e != nil {
		return e
	}
	latency, e := integer(obj["latency_us"], 9007199254740991)
	if e != nil {
		return e
	}
	var failed uint64
	if status >= 500 {
		failed = 1
	}
	if s.Records >= 9007199254740991 || s.Bytes > 9007199254740991-b || s.Latency > 9007199254740991-latency || s.Errors > 9007199254740991-failed {
		return fmt.Errorf("aggregate overflow")
	}
	s.Records++
	s.Bytes += b
	s.Latency += latency
	s.Errors += failed
	row := &s.Services[idx]
	row[0]++
	row[1] += b
	row[2] += latency
	row[3] += failed
	return nil
}
func report(path string) (Summary, error) {
	var s Summary
	data, e := os.ReadFile(path)
	if e != nil {
		return s, e
	}
	for _, line := range bytes.Split(data, []byte{'\n'}) {
		if len(line) == 0 {
			continue
		}
		var v any
		if e = json.Unmarshal(line, &v); e != nil {
			return s, e
		}
		if e = s.add(v); e != nil {
			return s, e
		}
	}
	return s, nil
}
func summarize(data []byte) (Summary, error) {
	var s Summary
	var v any
	if e := json.Unmarshal(data, &v); e != nil {
		return s, e
	}
	rows, ok := v.([]any)
	if !ok {
		return s, fmt.Errorf("expected array")
	}
	for _, row := range rows {
		if e := s.add(row); e != nil {
			return s, e
		}
	}
	return s, nil
}
func search(root string) (map[string]uint64, error) {
	out := map[string]uint64{"files": 0, "bytes": 0, "lines": 0, "matching_lines": 0, "matching_files": 0}
	e := filepath.WalkDir(root, func(path string, d fs.DirEntry, e error) error {
		if e != nil {
			return e
		}
		if !d.Type().IsRegular() || !strings.HasSuffix(d.Name(), ".txt") {
			return nil
		}
		data, e := os.ReadFile(path)
		if e != nil {
			return e
		}
		out["files"]++
		out["bytes"] += uint64(len(data))
		if len(data) == 0 {
			return nil
		}
		lines := bytes.Split(data, []byte{'\n'})
		if data[len(data)-1] == '\n' {
			lines = lines[:len(lines)-1]
		}
		out["lines"] += uint64(len(lines))
		var matches uint64
		for _, line := range lines {
			if bytes.Contains(line, []byte("ERROR")) {
				matches++
			}
		}
		out["matching_lines"] += matches
		if matches > 0 {
			out["matching_files"]++
		}
		return nil
	})
	return out, e
}
func serve() error {
	listener, e := net.Listen("tcp", "127.0.0.1:0")
	if e != nil {
		return e
	}
	server := &http.Server{}
	done := make(chan struct{})
	var finish sync.Once
	server.Handler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == "GET" && r.URL.Path == "/health":
			w.Write([]byte("ok\n"))
		case r.Method == "POST" && r.URL.Path == "/summarize":
			data, e := io.ReadAll(http.MaxBytesReader(w, r.Body, 1<<20))
			if e != nil {
				http.Error(w, "invalid body", 400)
				return
			}
			s, e := summarize(data)
			if e != nil {
				http.Error(w, "invalid JSON or schema", 400)
				return
			}
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(s)
		case r.Method == "POST" && r.URL.Path == "/quit":
			w.Write([]byte("ok\n"))
			if f, ok := w.(http.Flusher); ok {
				f.Flush()
			}
			go func() {
				server.Shutdown(context.Background())
				finish.Do(func() { close(done) })
			}()
		default:
			http.NotFound(w, r)
		}
	})
	fmt.Printf("port %d\n", listener.Addr().(*net.TCPAddr).Port)
	e = server.Serve(listener)
	if e == http.ErrServerClosed {
		<-done
		return nil
	}
	return e
}
func main() {
	var out any
	var e error
	if len(os.Args) == 2 && os.Args[1] == "serve" {
		e = serve()
	} else if len(os.Args) == 3 {
		switch os.Args[1] {
		case "report":
			out, e = report(os.Args[2])
		case "search":
			out, e = search(os.Args[2])
		default:
			e = fmt.Errorf("unknown mode")
		}
	} else {
		e = fmt.Errorf("usage: app report FILE | search DIRECTORY | serve")
	}
	if e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
	if out != nil {
		if e = json.NewEncoder(os.Stdout).Encode(out); e != nil {
			fmt.Fprintln(os.Stderr, e)
			os.Exit(1)
		}
	}
}
