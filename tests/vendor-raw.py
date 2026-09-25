#!/usr/bin/env python3
"""Exercise generated vendor APIs through real SDK imports and native calls."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--sdk', type=Path, default=ROOT / 'build/raw-sdk')
a = p.parse_args()
sdk = a.sdk.resolve()
manifest = json.loads((ROOT / 'compiler/vendor/raw-bindings.json').read_text())
paths = str(sdk / 'lib') + ':' + str(ROOT / 'build/vendor-deps/install/lib')
env = dict(os.environ, DYN_SDK=str(sdk), DYN_LIBRARY_PATH=paths, LD_LIBRARY_PATH=paths)
dyn = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
cases = {
    'sdl3': 'if raw.SDL_GetVersion() < 3000000 { #panic("version") }',
    'image': 'if raw.IMG_Version() < 3000000 { #panic("version") }',
    'ttf': 'if raw.TTF_Version() < 3000000 { #panic("version") }',
    'mixer': 'if raw.MIX_Version() < 3000000 { #panic("version") }',
    'sqlite': 'if raw.sqlite3_libversion_number() < 3000000 { #panic("version") }',
    'zstd': 'if raw.ZSTD_versionNumber() == 0 { #panic("version") }',
    'archive': 'if raw.archive_version_number() == 0 { #panic("version") }',
    'lz4': 'if raw.LZ4_versionNumber() == 0 { #panic("version") }',
    'openssl': 'if raw.OpenSSL_version_num() == 0 { #panic("version") }',
    'pcre2': 'version: [64]u8 = [] if raw.pcre2_config_8(#cast(u32) raw.PCRE2_CONFIG_VERSION, #cast(rawptr) &version[0]) <= 0 { #panic("config") }',
    'curl': 'version := raw.curl_version_info(raw.CURLVERSION_FIRST) if version == nil || version.version_num == 0 { #panic("version") }',
    'lua': 'state := raw.luaL_newstate() if state == nil { #panic("state") } raw.lua_pushinteger(state, 37) if raw.lua_tointegerx(state, -1, nil) != 37 { #panic("stack") } raw.lua_close(state)',
    'tree_sitter': 'parser := raw.ts_parser_new() if parser == nil { #panic("parser") } raw.ts_parser_delete(parser)',
    'box2d': 'version := raw.b2GetVersion() if version.major != 3 { #panic("aggregate return") }',
    'microui': 'v := raw.mu_vec2(3, 4) if v.x != 3 || v.y != 4 || raw.MU_COMMAND_RECT != 3 { #panic("aggregate return / enum") }',
    'enet': 'if raw.enet_initialize() != 0 { #panic("init") } raw.enet_deinitialize()',
    'miniaudio': 'major: u32 = 0 minor: u32 = 0 revision: u32 = 0 raw.ma_version(&major, &minor, &revision) if minor != 11 { #panic("version") }',
    'cgltf': '''options := raw.cgltf_options{} data: *raw.cgltf_data = nil
      document: []const u8 = "{\\"asset\\":{\\"version\\":\\"2.0\\"}}"
      if raw.cgltf_parse(&options, #cast(rawptr) &document[0], #len(document), &data) != raw.cgltf_result_success { #panic("parse") }
      if raw.cgltf_write(&options, nil, 0, data) == 0 { #panic("writer") } raw.cgltf_free(data)''',
    'stb_rect_pack': '''context := raw.stbrp_context{} nodes: [8]raw.stbrp_node = []
      rect := raw.stbrp_rect{ id: 0, w: 2, h: 2 }
      raw.stbrp_init_target(&context, 8, 8, &nodes[0], 8)
      if raw.stbrp_pack_rects(&context, &rect, 1) != 1 || rect.was_packed == 0 { #panic("pack") }''',
    'stb_image_resize': '''input: [4]u8 = [33, 33, 33, 33] output: [16]u8 = []
      if raw.stbir_resize_uint8_linear(&input[0], 2, 2, 0, &output[0], 4, 4, 0, raw.STBIR_1CHANNEL) == nil { #panic("resize") }
      if output[0] != 33 || output[15] != 33 { #panic("pixels") }
      storage: [131072]u8 = [] arena := mem.arena_from_buffer(storage[..])
      if !image.resize(&arena, input[..], 2, 2, output[..], 4, 4, 1, false) || mem.arena_mark(&arena) != 0 { #panic("arena wrapper coexistence") }
      if output[0] != 33 || output[15] != 33 { #panic("arena pixels") }
      tiny: [1]u8 = [] exhausted := mem.arena_from_buffer(tiny[..])
      if image.resize(&exhausted, input[..], 2, 2, output[..], 4, 4, 1, false) { #panic("arena allocator replaced") }''',
    'vulkan': '''library := dynlib.open("libvulkan.so.1", dynlib.Now) if !library.ok { #panic("loader") }
      symbol := dynlib.symbol(library.value, "vkEnumerateInstanceVersion") if !symbol.ok { #panic("procedure") }
      version: u32 = 0
      if raw.vkEnumerateInstanceVersion(#cast(raw.Procedure_vkEnumerateInstanceVersion) symbol.value, &version) != raw.VK_SUCCESS || version == 0 { #panic("dispatch") }
      _ = dynlib.close(library.value)''',
    'opengl': '''library := dynlib.open("libGL.so.1", dynlib.Now) if !library.ok { #panic("loader") }
      symbol := dynlib.symbol(library.value, "glGetError") if !symbol.ok { #panic("procedure") }
      raw.glClear(&record_clear, #cast(u32) raw.GL_COLOR_BUFFER_BIT)
      if recorded_mask != #cast(u32) raw.GL_COLOR_BUFFER_BIT { #panic("dispatch") }
      _ = dynlib.close(library.value)''',
}
cases['lua'] = r'''state := raw.luaL_newstate() if state == nil { #panic("state") }
  defer raw.lua_close(state)
  raw.lua_newtable(state) if raw.lua_istable(state, -1) == 0 { #panic("table macro") } raw.lua_pop(state, 1)
  raw.lua_pushinteger(state, 37)
  name: [2]u8 = ['t', 0]
  good: []const u8 = "return 6 * 7"
  if raw.luaL_loadbuffer(state, #cast(*const c.char) &good[0], #len(good), #cast(*const c.char) &name[0]) != 0 || raw.lua_pcall(state, 0, 1, 0) != 0 || raw.lua_tointeger(state, -1) != 42 { #panic("protected script") }
  raw.lua_pop(state, 1)
  bad: []const u8 = "return 1 + nil"
  if raw.luaL_loadbuffer(state, #cast(*const c.char) &bad[0], #len(bad), #cast(*const c.char) &name[0]) != 0 { #panic("load runtime error") }
  if raw.lua_pcall(state, 0, 1, 0) == 0 || raw.lua_tostring(state, -1) == nil { #panic("protected runtime error") }
  raw.lua_pop(state, 1)
  malformed: []const u8 = "return ("
  if raw.luaL_loadbuffer(state, #cast(*const c.char) &malformed[0], #len(malformed), #cast(*const c.char) &name[0]) == 0 { #panic("malformed script") }
  raw.lua_pop(state, 1)
  if raw.lua_gettop(state) != 1 || raw.lua_tointeger(state, -1) != 37 { #panic("preserved stack prefix") }
  raw.lua_pop(state, 1)
  if raw.lua_gettop(state) != 0 { #panic("balanced Lua stack") }'''
cases['openssl'] = r'''context := raw.SSL_CTX_new(raw.TLS_method()) if context == nil { #panic("TLS context") }
  defer raw.SSL_CTX_free(context)
  if raw.SSL_CTX_set_min_proto_version(context, raw.TLS1_2_VERSION) != 1 || raw.SSL_CTX_get_min_proto_version(context) != raw.TLS1_2_VERSION { #panic("protocol minimum macro") }
  if raw.SSL_CTX_set_max_proto_version(context, raw.TLS1_3_VERSION) != 1 || raw.SSL_CTX_get_max_proto_version(context) != raw.TLS1_3_VERSION { #panic("protocol maximum macro") }
  bio := raw.BIO_new(raw.BIO_s_mem()) if bio == nil { #panic("BIO") }
  defer { _ = raw.BIO_free(bio) }
  input: []const u8 = "payload" output: [7]u8 = []
  if raw.BIO_pending(bio) != 0 || raw.BIO_write(bio, #cast(rawptr) &input[0], 7) != 7 || raw.BIO_pending(bio) != 7 { #panic("BIO pending") }
  if raw.BIO_read(bio, #cast(rawptr) &output[0], 3) != 3 || raw.BIO_pending(bio) != 4 || output[0] != 'p' || output[2] != 'y' { #panic("BIO partial read") }
  if raw.BIO_flush(bio) != 1 || raw.BIO_reset(bio) != 1 || raw.BIO_pending(bio) != 0 || raw.BIO_eof(bio) != 1 { #panic("BIO reset") }'''
cases['sdl3'] += r'''
  if raw.SDL_VERSIONNUM(3, 2, 1) != 3002001 || !raw.SDL_VERSION_ATLEAST(3, 0, 0) || raw.SDL_BUTTON_MASK(1) != 1 || raw.SDL_BUTTON_MASK(32) != 2147483648 { #panic("SDL macros") }
  surface := raw.SDL_CreateSurface(3, 2, raw.SDL_PIXELFORMAT_RGBA32) if surface == nil { #panic("surface") }
  defer raw.SDL_DestroySurface(surface)
  if raw.SDL_MUSTLOCK(surface) { #panic("uncompressed surface lock") }'''
cases['sqlite'] = r'''path: [9]u8 = [':','m','e','m','o','r','y',':',0]
  database: rawptr = nil
  if raw.sqlite3_open(#cast(*const c.char) &path[0], &database) != raw.SQLITE_OK { #panic("open") }
  defer { _ = raw.sqlite3_close(database) }
  query: []const u8 = "SELECT ?1"
  statement: rawptr = nil
  if raw.sqlite3_prepare_v2(database, #cast(*const c.char) &query[0], #cast(i32) #len(query), &statement, nil) != raw.SQLITE_OK { #panic("prepare") }
  defer { _ = raw.sqlite3_finalize(statement) }
  payload: [3]u8 = [4,5,6]
  if raw.sqlite3_bind_blob(statement, 1, #cast(rawptr) &payload[0], 3, #cast(raw.sqlite3_destructor_type) raw.SQLITE_TRANSIENT()) != raw.SQLITE_OK { #panic("bind") }
  payload[0] = 99
  if raw.sqlite3_step(statement) != raw.SQLITE_ROW || raw.sqlite3_column_bytes(statement, 0) != 3 { #panic("row") }
  borrowed := #cast(*const u8) raw.sqlite3_column_blob(statement, 0)
  if borrowed == nil || borrowed.* != 4 { #panic("transient binding must copy") }
  // Borrow ends before reset/finalize. Never access borrowed after this point.
  if raw.sqlite3_reset(statement) != raw.SQLITE_OK { #panic("reset") }
  invalid: []const u8 = "SELECT ("
  rejected: rawptr = nil
  if raw.sqlite3_prepare_v2(database, #cast(*const c.char) &invalid[0], #cast(i32) #len(invalid), &rejected, nil) == raw.SQLITE_OK || rejected != nil { #panic("syntax failure") }'''
cases['lz4'] = r'''input: [64]u8 = [] encoded: [256]u8 = [] decoded: [64]u8 = []
  i: usize = 0 for i < #len(input) { input[i] = #cast(u8) i i += 1 }
  n := raw.LZ4_compress_default(#cast(*const c.char) &input[0], #cast(*c.char) &encoded[0], 64, 256)
  if n <= 0 || raw.LZ4_decompress_safe(#cast(*const c.char) &encoded[0], #cast(*c.char) &decoded[0], n, 64) != 64 { #panic("LZ4 roundtrip") }
  i = 0 for i < #len(input) { if input[i] != decoded[i] { #panic("LZ4 bytes") } i += 1 }
  if raw.LZ4_decompress_safe(#cast(*const c.char) &encoded[0], #cast(*c.char) &decoded[0], n, 1) >= 0 { #panic("short output") }
  malformed: [2]u8 = [255,255]
  if raw.LZ4_decompress_safe(#cast(*const c.char) &malformed[0], #cast(*c.char) &decoded[0], 2, 64) >= 0 { #panic("malformed LZ4") }'''
cases['zstd'] = r'''input: [64]u8 = [] encoded: [256]u8 = [] decoded: [64]u8 = []
  i: usize = 0 for i < #len(input) { input[i] = #cast(u8) i i += 1 }
  n := raw.ZSTD_compress(#cast(rawptr) &encoded[0], 256, #cast(rawptr) &input[0], 64, 3)
  if raw.ZSTD_isError(n) != 0 || raw.ZSTD_decompress(#cast(rawptr) &decoded[0], 64, #cast(rawptr) &encoded[0], n) != 64 { #panic("zstd roundtrip") }
  i = 0 for i < #len(input) { if input[i] != decoded[i] { #panic("zstd bytes") } i += 1 }
  if raw.ZSTD_isError(raw.ZSTD_decompress(#cast(rawptr) &decoded[0], 1, #cast(rawptr) &encoded[0], n)) == 0 { #panic("short output") }
  if raw.ZSTD_isError(raw.ZSTD_decompress(#cast(rawptr) &decoded[0], 64, #cast(rawptr) &encoded[0], n - 1)) == 0 { #panic("truncated frame") }'''
cases['sdl3'] = 'if !raw.SDL_Init(raw.SDL_INIT_EVENTS) { #panic("SDL events") } defer raw.SDL_Quit()\n' + cases['sdl3'] + r'''
  marker: u8 = 17
  raw.SDL_SetEventFilter(&event_filter, #cast(rawptr) &marker)
  returned_filter: raw.SDL_EventFilter = nil returned_data: rawptr = nil
  if !raw.SDL_GetEventFilter(&returned_filter, &returned_data) || returned_filter == nil || returned_data != #cast(rawptr) &marker { #panic("callback output") }
  if !returned_filter(returned_data, nil) { #panic("returned callback") }
  raw.SDL_SetEventFilter(nil, nil)'''
cases['ffmpeg'] = r'''if raw.AVERROR(11) != -11 || raw.AVUNERROR(-11) != 11 { #panic("error helpers") }
  if raw.avcodec_version() == 0 || raw.avformat_version() == 0 || raw.avutil_version() == 0 || raw.swscale_version() == 0 || raw.swresample_version() == 0 || raw.avfilter_version() == 0 || raw.avdevice_version() == 0 { #panic("FFmpeg versions") }
  format: *raw.AVFormatContext = nil
  name: []const u8 = "input.wav\0"
  if raw.avformat_open_input(&format, #cast(*const c.char) &name[0], nil, nil) < 0 { #panic("open WAV") }
  defer raw.avformat_close_input(&format)
  if raw.avformat_find_stream_info(format, nil) < 0 || format.nb_streams != 1 { #panic("WAV streams") }
  streams := format.streams[..format.nb_streams]
  if streams[0].codecpar.codec_id != raw.AV_CODEC_ID_PCM_S16LE || streams[0].codecpar.sample_rate != 8000 { #panic("WAV metadata") }
  packet := raw.av_packet_alloc() if packet == nil { #panic("packet") }
  defer raw.av_packet_free(&packet)
  if raw.av_read_frame(format, packet) < 0 || packet.size != 8 { #panic("WAV packet") }
  data := packet.data[..#cast(usize) packet.size]
  if data[0] != 1 || data[6] != 4 { #panic("WAV bytes") }
  raw.av_packet_unref(packet)
  if raw.av_read_frame(format, packet) != raw.AVERROR_EOF { #panic("WAV EOF") }
  missing: []const u8 = "missing-input.wav\0"
  rejected: *raw.AVFormatContext = nil
  if raw.avformat_open_input(&rejected, #cast(*const c.char) &missing[0], nil, nil) >= 0 || rejected != nil { #panic("missing input") }'''
assert cases.keys() == manifest.keys()
with tempfile.TemporaryDirectory(prefix='dyn-raw-imports-') as directory:
    work = Path(directory)
    import wave
    with wave.open(str(work/'input.wav'), 'wb') as wav:
        wav.setparams((1, 2, 8000, 4, 'NONE', 'not compressed'))
        wav.writeframes(bytes([1,0,2,0,3,0,4,0]))
    for name, body in cases.items():
        module = manifest[name]['module']
        imports = 'use "vendor/' + module + '" raw\nuse "std/c"\n'
        if name in ('vulkan', 'opengl'):
            imports += 'use "std/dynlib"\n#link("c")\n'
        if name == 'sdl3':
            imports += 'fn event_filter(data: rawptr, event: *raw.SDL_Event) bool { _ = event return data != nil }\n'
        if name == 'opengl':
            imports += 'recorded_mask: u32 = 0\nfn record_clear(mask: u32) { recorded_mask = mask }\n'
        if name == 'stb_image_resize':
            imports += 'use "std/mem"\nuse "vendor/stb/image_resize" image\n'
        (work / 'main.dyn').write_text(imports + 'fn main() { if !raw.verify_layout() { #panic("layout") }\n' + body + '\n}\n')
        for mode in ([], ['--release']):
            result = subprocess.run([dyn, 'build', str(work), '--no-cache', '--max-work', '100000000', '--output', str(work / 'test'), *mode], env=env, text=True, capture_output=True, timeout=180)
            assert result.returncode == 0, (name, result.stdout, result.stderr)
            result = subprocess.run([str(work / 'test')], cwd=work, env=env, text=True, capture_output=True, timeout=30)
            assert result.returncode == 0, (name, result.returncode, result.stdout, result.stderr)
        print('PASS raw native calls: ' + name, flush=True)
        if manifest[name].get('example'):
            for mode in ([], ['--release']):
                subprocess.run([dyn, 'build', str(sdk / 'examples' / name), '--quiet', '--no-cache',
                                '--output', str(work / 'example'), *mode], env=env, check=True, timeout=120)
                result = subprocess.run([str(work / 'example')], env=env, text=True, capture_output=True, timeout=30)
                assert result.returncode == 0 and manifest[name].get('example_output', 'retained result') in result.stdout, result
print('PASS all generated vendor imports in debug and release')
