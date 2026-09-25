#include <stddef.h>
#include <tree_sitter/api.h>
#include <SDL3/SDL.h>
#include <SDL3_ttf/SDL_ttf.h>
#include <lua5.4/lua.h>
#include <curl/curl.h>
#define PCRE2_CODE_UNIT_WIDTH 8
#include <pcre2.h>
_Static_assert(sizeof(lua_Integer)==8 && sizeof(lua_Number)==8, "Lua default ABI required");
_Static_assert(LUA_VERSION_NUM==504, "Lua 5.4 required");
_Static_assert(PCRE2_UTF==524288 && PCRE2_UCP==131072 && PCRE2_CASELESS==8, "PCRE options");
_Static_assert(CURLOPT_URL==10002 && CURLOPT_WRITEFUNCTION==20011 && CURLOPT_WRITEDATA==10001, "curl pointer options");
_Static_assert(CURLOPT_NOSIGNAL==99 && CURLOPT_TIMEOUT_MS==155 && CURLOPT_PROTOCOLS_STR==10318 && CURLINFO_RESPONSE_CODE==2097154, "curl options");
_Static_assert(SDL_GL_CONTEXT_MAJOR_VERSION==17 && SDL_GL_CONTEXT_MINOR_VERSION==18 && SDL_GL_CONTEXT_PROFILE_MASK==20, "GL attributes");
size_t oracle_node_size(void) { return sizeof(TSNode); }
size_t oracle_node_align(void) { return _Alignof(TSNode); }
size_t oracle_edit_size(void) { return sizeof(TSInputEdit); }
size_t oracle_color_size(void) { return sizeof(SDL_Color); }
int oracle_surface(SDL_Surface *surface) { return surface && surface->w>0 && surface->h>0; }
