/* AppKit key-event strings use UTF-16. Keep conversion independent of AppKit
 * so malformed and supplementary-plane event data can be checked portably. */
#ifndef DYN_COCOA_KEY_H
#define DYN_COCOA_KEY_H
#include <stddef.h>
#include <stdint.h>
static inline uint32_t cocoa_key_scalar(const uint16_t *units, size_t count) {
  if (!units || !count || count > 2) return 0;
  uint32_t value = units[0];
  if (value >= 0xd800 && value <= 0xdbff) {
    if (count != 2 || units[1] < 0xdc00 || units[1] > 0xdfff) return 0;
    value = 0x10000 + ((value - 0xd800) << 10) + units[1] - 0xdc00;
  } else if (count != 1 || (value >= 0xdc00 && value <= 0xdfff)) return 0;
  /* AppKit encodes function keys in this private-use range. They and control
   * characters belong to the logical key field, never printable snapshots. */
  if (value < 0x20 || (value >= 0x7f && value <= 0x9f) ||
      (value >= 0xf700 && value <= 0xf8ff)) return 0;
  return value;
}
#endif
