#ifndef DYN_LSP_INPUT_H
#define DYN_LSP_INPUT_H
#include <poll.h>

/* One bounded framing buffer. Nonblocking lookahead never waits for the rest of
   a partial header/body; ordinary reads block only when no work is pending. */
typedef struct {
  char *data;
  size_t length, capacity;
  bool eof, failed;
} LspInput;
static char *lsp_input_next(LspInput *input, bool wait) {
  const size_t limit = 16u * 1024u * 1024u, header_limit = 8192;
  for (;;) {
    size_t header_end = 0, body_length = 0;
    if (input->length) {
      char *end = strstr(input->data, "\r\n\r\n");
      if (end) header_end = (size_t)(end - input->data) + 4;
      else if ((end = strstr(input->data, "\n\n")))
        header_end = (size_t)(end - input->data) + 2;
      if (header_end) {
        const char *line = input->data, *stop = input->data + header_end;
        bool found = false;
        while (line < stop) {
          if (!strncasecmp(line, "Content-Length:", 15)) {
            const char *number = line + 15;
            while (*number == ' ' || *number == '\t') ++number;
            char *tail;
            errno = 0;
            unsigned long long value = strtoull(number, &tail, 10);
            if (found || !isdigit((unsigned char)*number) || tail == number ||
                errno || !value || value > limit || (*tail != '\r' && *tail != '\n')) {
              input->failed = true; return NULL;
            }
            body_length = (size_t)value; found = true;
          }
          const char *next = memchr(line, '\n', (size_t)(stop - line));
          if (!next) break;
          line = next + 1;
        }
        if (!found || header_end > header_limit) { input->failed = true; return NULL; }
        if (input->length >= header_end + body_length) {
          char *body = malloc(body_length + 1);
          if (!body) { input->failed = true; return NULL; }
          memcpy(body, input->data + header_end, body_length);
          body[body_length] = 0;
          /* Embedded NUL is invalid JSON, retain a syntactically invalid body. */
          if (memchr(body, 0, body_length)) body[0] = 0;
          input->length -= header_end + body_length;
          memmove(input->data, input->data + header_end + body_length, input->length);
          input->data[input->length] = 0;
          return body;
        }
      } else if (input->length >= header_limit) {
        input->failed = true; return NULL;
      }
    }
    if (input->eof || input->failed) {
      if (input->length) input->failed = true;
      return NULL;
    }
    struct pollfd fd = {.fd = STDIN_FILENO, .events = POLLIN};
    int ready;
    do ready = poll(&fd, 1, wait ? -1 : 0); while (ready < 0 && errno == EINTR);
    if (!ready) return NULL;
    if (ready < 0 || (fd.revents & (POLLERR | POLLNVAL))) { input->failed = true; return NULL; }
    if (input->capacity - input->length < 4097) {
      size_t capacity = input->capacity ? input->capacity * 2 : 8192;
      if (capacity > limit + header_limit + 4096) capacity = limit + header_limit + 4096;
      if (capacity <= input->length + 1) { input->failed = true; return NULL; }
      char *data = realloc(input->data, capacity);
      if (!data) { input->failed = true; return NULL; }
      input->data = data; input->capacity = capacity;
    }
    ssize_t got = read(STDIN_FILENO, input->data + input->length,
                       input->capacity - input->length - 1);
    if (got < 0) { if (errno == EINTR) continue; input->failed = true; return NULL; }
    if (!got) input->eof = true;
    else input->length += (size_t)got;
    input->data[input->length] = 0;
  }
}
#endif
