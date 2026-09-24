#include <stddef.h>
#include <stdint.h>

typedef struct { int live; int fd; const char *host; } FakeSSL;
static int context;
static int mode, contexts, cleared, pending_error;
void dyn_tls_test_mode(int value) { mode = value; cleared = 0; }
int dyn_tls_test_live(void) { return contexts; }

static FakeSSL connection;
int dyn_tls_test_connection_live(void) { return connection.live; }
static int certificate;
static const unsigned char selected_protocol[] = "h2";

void *TLS_client_method(void) { return &context; }
void *TLS_server_method(void) { return mode == 1 ? 0 : &context; }
void *SSL_CTX_new(void *method) { if (!method || mode == 2) return 0; ++contexts; return &context; }
void SSL_CTX_free(void *value) { if (value) --contexts; }
int SSL_CTX_set_default_verify_paths(void *value) { return value != 0 && mode != 3; }
void SSL_CTX_set_verify(void *value, int mode, void *callback) { (void)value; (void)mode; (void)callback; }
void *SSL_new(void *value) { connection.live = value != 0; return connection.live ? &connection : 0; }
void SSL_free(void *value) { ((FakeSSL *)value)->live = 0; }
int SSL_set_fd(void *value, int fd) { ((FakeSSL *)value)->fd = fd; return fd == 7; }
void *SSL_get0_param(void *value) { return value; }
int X509_VERIFY_PARAM_set1_host(void *value, const char *host, size_t length) {
  FakeSSL *ssl = value; ssl->host = host;
  return length == 12 && host[0] == 'e' && host[11] == 't' && host[12] == 0;
}
long SSL_ctrl(void *value, int command, long argument, void *pointer) {
  FakeSSL *ssl = value;
  return command == 55 && argument == 0 && pointer == ssl->host;
}
int SSL_connect(void *value) {
  FakeSSL *ssl = value;
  if (mode == 4) { pending_error = 1; return 0; }
  return ssl->live && ssl->fd == 7;
}
int SSL_accept(void *value) { FakeSSL *ssl = value; return ssl->live && ssl->fd == 7; }
int SSL_CTX_use_certificate_chain_file(void *value, const char *path) { return value && path && path[0] == 'c'; }
int SSL_CTX_use_PrivateKey_file(void *value, const char *path, int kind) { return value && path && path[0] == 'k' && kind == 1; }
int SSL_CTX_check_private_key(void *value) { return value != 0; }
int SSL_set_alpn_protos(void *value, const unsigned char *protocols, unsigned length) {
  return !(value && length == 3 && protocols[0] == 2 && protocols[1] == 'h' && protocols[2] == '2');
}
void SSL_get0_alpn_selected(void *value, const unsigned char **selected, unsigned *length) {
  if (value) { *selected = selected_protocol; *length = 2; } else { *selected = 0; *length = 0; }
}
void *SSL_get_peer_certificate(void *value) { return value ? &certificate : 0; }
void *SSL_get1_peer_certificate(void *value) { return value ? &certificate : 0; }
void X509_free(void *value) { (void)value; }
void *X509_get_subject_name(void *value) { return value; }
char *X509_NAME_oneline(void *value, char *destination, int length) {
  const char text[] = "/CN=example.test"; int i = 0;
  if (!value || length < 2) return 0;
  while (i + 1 < length && text[i]) { destination[i] = text[i]; ++i; }
  destination[i] = 0; return destination;
}
int SSL_read_ex(void *value, void *destination, size_t length, size_t *read) {
  (void)value; if (mode == 5) { pending_error = 1; return 0; } if (length < 3) return 0;
  ((unsigned char *)destination)[0] = 'o'; ((unsigned char *)destination)[1] = 'k'; ((unsigned char *)destination)[2] = '!'; *read = 3; return 1;
}
int SSL_write_ex(void *value, const void *source, size_t length, size_t *written) {
  (void)value; if (length != 5 || ((const char *)source)[0] != 'h') return 0; *written = length; return 1;
}
int SSL_shutdown(void *value) { return value != 0; }
long SSL_get_verify_result(void *value) { if (pending_error) return 999; return value ? 0 : 1; }
int SSL_get_error(void *value, int result) {
  (void)value;
  if (!cleared) return 99;
  pending_error = 0;
  return mode == 4 ? 2 : mode == 5 ? 6 : result;
}
unsigned long ERR_get_error(void) { return 42; }
void ERR_error_string_n(unsigned long code, char *destination, size_t length) {
  const char text[] = "ssl-error!"; size_t i = 0;
  if (!length) return;
  while (i + 1 < length && text[i]) { destination[i] = text[i]; ++i; }
  destination[i] = 0; (void)code;
}

void ERR_clear_error(void) { cleared = 1; pending_error = 0; }
