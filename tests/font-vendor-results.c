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
static void shape(hb_font_t *font, const char *text, const char *path, int explicit_run) {
  hb_buffer_t *buffer = hb_buffer_create();
  hb_buffer_add_utf8(buffer, text, -1, explicit_run == 2 ? 2 : 0, explicit_run == 2 ? 2 : -1);
  if (explicit_run) {
    hb_buffer_set_direction(buffer, HB_DIRECTION_RTL);
    hb_buffer_set_script(buffer, HB_SCRIPT_ARABIC);
    hb_buffer_set_language(buffer, hb_language_from_string("ar", -1));
    hb_buffer_set_cluster_level(buffer, HB_BUFFER_CLUSTER_LEVEL_MONOTONE_CHARACTERS);
    hb_buffer_set_flags(buffer, explicit_run == 1 ? HB_BUFFER_FLAG_BOT | HB_BUFFER_FLAG_EOT : 0);
  }
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
  file = fopen("metrics-reference.bin", "wb");
  assert(file);
  word(file, face->units_per_EM);
  word(file, (uint32_t)(int32_t)face->ascender);
  word(file, (uint32_t)(int32_t)face->descender);
  word(file, (uint32_t)(int32_t)face->height);
  word(file, (uint32_t)face->num_glyphs);
  word(file, (uint32_t)face->num_faces);
  word(file, (uint32_t)face->face_index);
  fclose(file);
  FT_Done_Face(face);
  FT_Done_FreeType(library);
  hb_blob_t *blob = hb_blob_create_from_file_or_fail("font.ttf");
  assert(blob);
  hb_face_t *hbface = hb_face_create(blob, 0);
  hb_font_t *font = hb_font_create(hbface);
  hb_ot_font_set_funcs(font);
  hb_font_set_scale(font, 2048, 2048);
  shape(font, "office AV", "latin-reference.bin", 0);
  shape(font, "السلام", "arabic-reference.bin", 0);
  shape(font, "السَلام", "run-reference.bin", 1);
  shape(font, "بجح", "context-reference.bin", 2);
  hb_font_destroy(font);
  hb_face_destroy(hbface);
  hb_blob_destroy(blob);
  return 0;
}
