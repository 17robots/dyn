#include <ft2build.h>
#include FT_FREETYPE_H
#include <assert.h>
#include <hb-ot.h>
#include <hb.h>
#include <stdio.h>
static void word(FILE *file, uint32_t value) {
  unsigned char bytes[4] = {(unsigned char)value, (unsigned char)(value >> 8),
                            (unsigned char)(value >> 16),
                            (unsigned char)(value >> 24)};
  assert(fwrite(bytes, 1, 4, file) == 4);
}
static void shape(hb_font_t *font, const char *text, const char *path) {
  hb_buffer_t *buffer = hb_buffer_create();
  hb_buffer_add_utf8(buffer, text, -1, 0, -1);
  hb_buffer_guess_segment_properties(buffer);
  hb_shape(font, buffer, NULL, 0);
  unsigned count;
  hb_glyph_info_t *info = hb_buffer_get_glyph_infos(buffer, &count);
  hb_glyph_position_t *position = hb_buffer_get_glyph_positions(buffer, NULL);
  FILE *file = fopen(path, "wb");
  assert(file);
  word(file, count);
  for (unsigned i = 0; i < count; ++i) {
    word(file, info[i].codepoint);
    word(file, info[i].cluster);
    word(file, (uint32_t)position[i].x_advance);
    word(file, (uint32_t)position[i].y_advance);
    word(file, (uint32_t)position[i].x_offset);
    word(file, (uint32_t)position[i].y_offset);
  }
  fclose(file);
  hb_buffer_destroy(buffer);
}
int main(void) {
  FT_Library library;
  FT_Face face;
  assert(!FT_Init_FreeType(&library));
  assert(!FT_New_Face(library, "font.ttf", 0, &face));
  assert(!FT_Set_Pixel_Sizes(face, 0, 32));
  assert(!FT_Load_Char(face, 'A', FT_LOAD_RENDER));
  FT_GlyphSlot slot = face->glyph;
  FILE *file = fopen("ft-reference.bin", "wb");
  assert(file);
  word(file, slot->bitmap.width);
  word(file, slot->bitmap.rows);
  word(file, (uint32_t)slot->bitmap_left);
  word(file, (uint32_t)slot->bitmap_top);
  word(file, (uint32_t)slot->advance.x);
  word(file, (uint32_t)slot->advance.y);
  for (unsigned row = 0; row < slot->bitmap.rows; ++row)
    assert(fwrite(slot->bitmap.buffer + row * slot->bitmap.pitch, 1,
                  slot->bitmap.width, file) == slot->bitmap.width);
  fclose(file);
  FT_Done_Face(face);
  FT_Done_FreeType(library);
  hb_blob_t *blob = hb_blob_create_from_file_or_fail("font.ttf");
  assert(blob);
  hb_face_t *hbface = hb_face_create(blob, 0);
  hb_font_t *font = hb_font_create(hbface);
  hb_ot_font_set_funcs(font);
  hb_font_set_scale(font, 2048, 2048);
  shape(font, "office AV", "latin-reference.bin");
  shape(font, "السلام", "arabic-reference.bin");
  hb_font_destroy(font);
  hb_face_destroy(hbface);
  hb_blob_destroy(blob);
  return 0;
}
