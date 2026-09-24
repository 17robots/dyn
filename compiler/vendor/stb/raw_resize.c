/* Raw upstream API uses the upstream C allocation contract. The arena-backed
   Dyn wrapper has a private implementation in bridge.c so the two allocators
   cannot interpose on each other when both modules are loaded. */
#include <string.h>
#define STB_IMAGE_RESIZE_IMPLEMENTATION
#include <stb_image_resize2.h>
