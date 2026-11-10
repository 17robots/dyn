# One result shape

If the world can make a function fail, it returns `{ value, failure }`. With
nothing to return, it returns the failure alone. `.value` is always safe to
read, and a zero failure means success.

```dyn
opened := fs.open(path, fs.Read)
if opened.failure.kind != io.Kind.Ok {
  report(opened.failure.kind) // opened.failure.native is the native code
}
file := opened.value
```

`std/errors` is gone. Its contents live in `std/io`:

- Effects report `io.Failure { kind, native }`.
- Parsers and decoders report `parse.Failure { kind, offset, message }`.
- Decoders over a stream report `parse.StreamFailure { kind, parse, io }`, with
  `parse.StreamKind { Ok, Parse, Io }` naming the source.

| Before | After |
|---|---|
| `r.ok` | `r.failure.kind == io.Kind.Ok` or `parse.Kind.Ok` |
| `r.kind` | `r.failure.kind` |
| `r.error` | `r.failure.native` |
| `r.detail` | `r.failure.kind`, plus `r.failure.message` for text |
| `errors.Kind.InvalidInput` from a parser | `parse.Kind.Syntax` |

Module `ErrorKind` enums are gone from parsers. For example, JSON `TrailingData`
is `Syntax` with the message `"trailing data"`, and an unterminated string in
Mdesk is `Truncated`.

Scanners and iterators report `found`. `found` false with no failure is the end
of input: `csv.Field`, `ini.Result`, `xml.Result`, `xml.Attribute`, `tar.Result`,
`tar.StreamEntry`, `zip.EntryResult`, `http.HttpHeader`, `regex.Match`,
`signal.Next`, `fs.DirectoryEntry`, and the CBOR, MessagePack, Protobuf and DER
readers. `tar.Status` and `zip.ErrorKind.End` are gone.

Pure results that cannot fail by the world say what they mean: `valid` for
checked values (`utf8.Decode`, `path.Result`, `time.Parsed`, matrix results) and
`found` for scans (`bytes.Piece`, `path.Component`, `ring.Popped`).

`aead.OpenResult` adds `valid`, and `x509.Validation` keeps it: check `valid`
before using plaintext or trusting a certificate.

A zero result now reads as success. Code that used a zero result to mean
failure must keep its own state. `deflate.Result` keeps `done`, because `resume`
can stop for more input without failing.

`std/os` and `std/mem` keep `ok` and `error`. They sit below `std/io`, and
`std/os` is the raw system layer.

`close` returns nothing and can be called twice: `fs.close`, `net.close`,
`net.connection_close`, `net.listener_close`, `http.close`, `watch.close`,
`event.close`, `signal.close`, `fs.close_directory` and `process.close_pipe`.
Call `sync` first when a write must be durable. `dynlib.close` still returns a
failure, because `dlclose` can leave a library loaded.

The compiler names the type and the old field in each error
(`Result has no field 'ok'`).
