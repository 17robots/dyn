# One result shape

Results at the edges use the same field names everywhere:

```dyn
opened := fs.open(path, fs.Read)
if !opened.ok {
  report(opened.kind) // portable category; opened.error is the native code
}
file := opened.value // was opened.file
```

Renamed payload fields, all now `value`: `FileResult.file`,
`OffsetResult.offset`, `ReadAllResult.data`, `PathResult.path`,
`DirectoryResult.directory`, `AtomicResult.transaction`,
`ConnectionResult.connection`, `ListenerResult.listener`,
`AcceptResult.connection`, `SpawnResult.child`, `ArgumentsResult.values`,
`TemporaryResult.directory`, `watch.OpenResult.watcher`, zip `entry`, `data`
and `reader`, `dns.Result.count`, `xml.Result.event`, `ini.Result.entry`,
`semver.ParseResult.version`, `template.ParseResult.template`,
`der.Result.element`, `certificate.Result.certificate`.

Parser errors are `kind` and positions `offset`: JSON and Mdesk
`ParseResult.error` and `error_offset`, template and DER results, and
`url.ParseResult.error_offset`. INI `ParseResult` is `{value, kind, line, ok}`.
Network, watch and temporary-directory results gain `kind`.

Renaming is mechanical: the compiler names the type and the old field in
each error (`FileResult has no field 'file'`).
