#ifndef DYN_LSP_JSON_H
#define DYN_LSP_JSON_H

#include <ctype.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

/* Small bounded JSON traversal. Callers retain the original message storage. */
static inline const char *lsp_json_space(const char *p) {
  while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n')
    ++p;
  return p;
}
static inline const char *lsp_json_end(const char *p, unsigned depth) {
  p = lsp_json_space(p);
  if (depth > 128)
    return NULL;
  if (*p == '"') {
    for (++p; *p && *p != '"'; ++p) {
      if ((unsigned char)*p < 32)
        return NULL;
      unsigned char lead = (unsigned char)*p;
      if (lead >= 0x80) {
        unsigned width = lead >= 0xc2 && lead <= 0xdf   ? 2
                         : lead >= 0xe0 && lead <= 0xef ? 3
                         : lead >= 0xf0 && lead <= 0xf4 ? 4
                                                        : 0;
        if (!width)
          return NULL;
        for (unsigned i = 1; i < width; ++i)
          if (!p[i] || ((unsigned char)p[i] & 0xc0) != 0x80)
            return NULL;
        unsigned char second = (unsigned char)p[1];
        if ((lead == 0xe0 && second < 0xa0) ||
            (lead == 0xed && second >= 0xa0) ||
            (lead == 0xf0 && second < 0x90) || (lead == 0xf4 && second >= 0x90))
          return NULL;
        p += width - 1;
        continue;
      }
      if (*p == '\\') {
        ++p;
        if (!*p)
          return NULL;
        if (*p == 'u') {
          for (unsigned i = 0; i < 4; ++i)
            if (!isxdigit((unsigned char)*++p))
              return NULL;
        } else if (!strchr("\"\\/bfnrt", *p))
          return NULL;
      }
    }
    return *p == '"' ? p + 1 : NULL;
  }
  if (*p == '{' || *p == '[') {
    bool object = *p == '{';
    char close = object ? '}' : ']';
    p = lsp_json_space(p + 1);
    if (*p == close)
      return p + 1;
    for (;;) {
      if (object) {
        if (*p != '"' || !(p = lsp_json_end(p, depth + 1)))
          return NULL;
        p = lsp_json_space(p);
        if (*p++ != ':')
          return NULL;
      }
      if (!(p = lsp_json_end(p, depth + 1)))
        return NULL;
      p = lsp_json_space(p);
      if (*p == close)
        return p + 1;
      if (*p++ != ',')
        return NULL;
      p = lsp_json_space(p);
    }
  }
  if (!strncmp(p, "true", 4))
    return p + 4;
  if (!strncmp(p, "false", 5))
    return p + 5;
  if (!strncmp(p, "null", 4))
    return p + 4;
  if (*p == '-')
    ++p;
  if (*p == '0')
    ++p;
  else {
    if (*p < '1' || *p > '9')
      return NULL;
    do {
      ++p;
    } while (isdigit((unsigned char)*p));
  }
  if (*p == '.') {
    ++p;
    if (!isdigit((unsigned char)*p))
      return NULL;
    do {
      ++p;
    } while (isdigit((unsigned char)*p));
  }
  if (*p == 'e' || *p == 'E') {
    ++p;
    if (*p == '+' || *p == '-')
      ++p;
    if (!isdigit((unsigned char)*p))
      return NULL;
    do {
      ++p;
    } while (isdigit((unsigned char)*p));
  }
  return p;
}
static inline bool lsp_json_valid(const char *p) {
  const char *end = lsp_json_end(p, 0);
  return end && !*lsp_json_space(end);
}
static inline bool lsp_json_key_equal(const char *start, const char *end,
                                      const char *key) {
  ++start;
  ++key;
  while (start < end - 1 && *key != '"') {
    unsigned value = (unsigned char)*start++;
    if (value == '\\') {
      value = (unsigned char)*start++;
      if (value == 'u') {
        value = 0;
        for (unsigned i = 0; i < 4; ++i) {
          unsigned char c = (unsigned char)*start++;
          unsigned digit = c <= '9'   ? c - '0'
                           : c <= 'F' ? c - 'A' + 10
                                      : c - 'a' + 10;
          value = value * 16 + digit;
        }
      }
    }
    if (value != (unsigned char)*key++)
      return false;
  }
  return start == end - 1 && *key == '"';
}
static inline const char *lsp_json_member(const char *p, const char *key) {
  p = lsp_json_space(p);
  if (*p++ != '{')
    return NULL;
  p = lsp_json_space(p);
  while (*p == '"') {
    const char *end = lsp_json_end(p, 0);
    if (!end)
      return NULL;
    bool match = lsp_json_key_equal(p, end, key);
    p = lsp_json_space(end);
    if (*p++ != ':')
      return NULL;
    p = lsp_json_space(p);
    if (match)
      return p;
    p = lsp_json_end(p, 0);
    if (!p)
      return NULL;
    p = lsp_json_space(p);
    if (*p++ != ',')
      return NULL;
    p = lsp_json_space(p);
  }
  return NULL;
}
/* Find a field recursively, skipping string contents and respecting containers.
 */
static inline const char *lsp_json_find(const char *p, const char *key) {
  p = lsp_json_space(p);
  const char *direct = lsp_json_member(p, key);
  if (direct)
    return direct;
  bool object = *p == '{';
  if (!object && *p != '[')
    return NULL;
  p = lsp_json_space(p + 1);
  while (*p && *p != '}' && *p != ']') {
    if (object) {
      p = lsp_json_end(p, 0);
      if (!p)
        return NULL;
      p = lsp_json_space(p);
      if (*p++ != ':')
        return NULL;
    }
    const char *found = lsp_json_find(p, key);
    if (found)
      return found;
    p = lsp_json_end(p, 0);
    if (!p)
      return NULL;
    p = lsp_json_space(p);
    if (*p++ != ',')
      return NULL;
    p = lsp_json_space(p);
  }
  return NULL;
}
static inline bool lsp_json_size(const char *p, size_t *value) {
  if (!p || !isdigit((unsigned char)*p))
    return false;
  errno = 0;
  char *end;
  unsigned long long number = strtoull(p, &end, 10);
  if (errno || number > SIZE_MAX || (*end && !strchr(" ,}\r\n\t]", *end)))
    return false;
  *value = (size_t)number;
  return true;
}
#endif
