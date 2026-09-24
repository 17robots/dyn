/* Value-taking OpenSSL macros. No new allocation or ownership policy. */
static inline int dyn_helper_SSL_CTX_set_min_proto_version(SSL_CTX *s, int version) { return SSL_CTX_set_min_proto_version(s,version); }
static inline int dyn_helper_SSL_CTX_get_min_proto_version(SSL_CTX *s) { return SSL_CTX_get_min_proto_version(s); }
static inline int dyn_helper_SSL_CTX_set_max_proto_version(SSL_CTX *s, int version) { return SSL_CTX_set_max_proto_version(s,version); }
static inline int dyn_helper_SSL_CTX_get_max_proto_version(SSL_CTX *s) { return SSL_CTX_get_max_proto_version(s); }
static inline int dyn_helper_SSL_set_min_proto_version(SSL *s, int version) { return SSL_set_min_proto_version(s,version); }
static inline int dyn_helper_SSL_get_min_proto_version(SSL *s) { return SSL_get_min_proto_version(s); }
static inline int dyn_helper_SSL_set_max_proto_version(SSL *s, int version) { return SSL_set_max_proto_version(s,version); }
static inline int dyn_helper_SSL_get_max_proto_version(SSL *s) { return SSL_get_max_proto_version(s); }
static inline long dyn_helper_SSL_set_tlsext_host_name(SSL *s, const char *name) { return SSL_set_tlsext_host_name(s,name); }
static inline long dyn_helper_BIO_pending(BIO *b) { return BIO_pending(b); }
static inline long dyn_helper_BIO_wpending(BIO *b) { return BIO_wpending(b); }
static inline long dyn_helper_BIO_flush(BIO *b) { return BIO_flush(b); }
static inline long dyn_helper_BIO_reset(BIO *b) { return BIO_reset(b); }
static inline long dyn_helper_BIO_eof(BIO *b) { return BIO_eof(b); }
