# TLS

`std/net/tls` provides client and server TLS through OpenSSL 3 on Linux.
The binding uses `SSL_get1_peer_certificate`; OpenSSL 1.1.1 is not supported.

- `client_config_create` loads provider-default trust roots and enables peer verification.
- `server_config_create` accepts an arena for temporary PEM path strings;
  `server_config_create_into` accepts caller buffers instead.
- `client_connection_create` accepts arena scratch for hostname verification and SNI;
  `client_connection_create_into` accepts caller storage. Neither retains scratch.
- `server_connection_create` attaches an existing descriptor to a server configuration.
- Successful configurations require `config_destroy`; connections require
  `connection_destroy`. Failed constructors release partially created handles.
- Provider allocations are owned by OpenSSL, outside the Dyn arena. Sockets remain
  caller-owned. Destroy connections before their configuration; close sockets separately.
- `peer_certificate_owned` returns a provider reference requiring `certificate_free_owned`.
- ALPN input is validated length-prefixed wire format. Selected ALPN bytes borrow the
  connection until renegotiation or destruction. Certificate subject/error text uses caller buffers.
- Arena constructors rewind scratch on every return. Output slices and adapters never own it.

`handshake`, `server_handshake`, `read`, and `write` expose `WantRead`/`WantWrite` for
nonblocking operations. Retry after the corresponding readiness event, preserving operation
arguments as required by OpenSSL. `provider_status` records the SSL error classification.
A clean `close_notify` read succeeds with zero bytes; a truncated connection fails.

The `reader`/`writer` adapters target blocking sockets. They borrow both the live connection
and the caller's `Connection` slot; neither may be destroyed while an adapter is used.
Use the native TLS results for nonblocking retry handling.

`vendor/openssl/tls` declares `ssl` and `crypto` libraries. The compiler finds them through
platform directories or `DYN_LIBRARY_PATH`; explicit `--link` paths also work.
Dynamic TLS providers on macOS and Windows are not implemented.

Provider contracts: [SSL_get_error](https://docs.openssl.org/3.0/man3/SSL_get_error/),
[SSL_read](https://docs.openssl.org/3.0/man3/SSL_read/).
