/* Typed entry points for value-taking Lua 5.4 macros. Native Lua contracts apply. */
static inline void dyn_helper_lua_pop(lua_State *L, int n) { lua_pop(L,n); }
static inline void dyn_helper_lua_newtable(lua_State *L) { lua_newtable(L); }
static inline void *dyn_helper_lua_newuserdata(lua_State *L, size_t n) { return lua_newuserdata(L,n); }
static inline lua_Integer dyn_helper_lua_tointeger(lua_State *L, int i) { return lua_tointeger(L,i); }
static inline lua_Number dyn_helper_lua_tonumber(lua_State *L, int i) { return lua_tonumber(L,i); }
static inline const char *dyn_helper_lua_tostring(lua_State *L, int i) { return lua_tostring(L,i); }
static inline int dyn_helper_lua_pcall(lua_State *L, int n, int r, int f) { return lua_pcall(L,n,r,f); }
static inline void dyn_helper_lua_call(lua_State *L, int n, int r) { lua_call(L,n,r); }
static inline void dyn_helper_lua_insert(lua_State *L, int i) { lua_insert(L,i); }
static inline void dyn_helper_lua_remove(lua_State *L, int i) { lua_remove(L,i); }
static inline void dyn_helper_lua_replace(lua_State *L, int i) { lua_replace(L,i); }
static inline void dyn_helper_lua_pushcfunction(lua_State *L, lua_CFunction f) { lua_pushcfunction(L,f); }
static inline void dyn_helper_lua_pushglobaltable(lua_State *L) { lua_pushglobaltable(L); }
static inline int dyn_helper_lua_upvalueindex(int i) { return lua_upvalueindex(i); }
static inline void *dyn_helper_lua_getextraspace(lua_State *L) { return lua_getextraspace(L); }
static inline int dyn_helper_lua_getuservalue(lua_State *L, int i) { return lua_getuservalue(L,i); }
static inline void dyn_helper_lua_setuservalue(lua_State *L, int i) { lua_setuservalue(L,i); }
static inline int dyn_helper_luaL_loadbuffer(lua_State *L, const char *s, size_t n, const char *name) { return luaL_loadbuffer(L,s,n,name); }
static inline int dyn_helper_luaL_loadfile(lua_State *L, const char *name) { return luaL_loadfile(L,name); }
static inline void dyn_helper_luaL_checkversion(lua_State *L) { luaL_checkversion(L); }
static inline const char *dyn_helper_luaL_checkstring(lua_State *L, int i) { return luaL_checkstring(L,i); }
static inline const char *dyn_helper_luaL_optstring(lua_State *L, int i, const char *s) { return luaL_optstring(L,i,s); }
static inline int dyn_helper_luaL_getmetatable(lua_State *L, const char *name) { return luaL_getmetatable(L,name); }
static inline int dyn_helper_lua_isfunction(lua_State *L, int i) { return lua_isfunction(L,i); }
static inline int dyn_helper_lua_istable(lua_State *L, int i) { return lua_istable(L,i); }
static inline int dyn_helper_lua_islightuserdata(lua_State *L, int i) { return lua_islightuserdata(L,i); }
static inline int dyn_helper_lua_isnil(lua_State *L, int i) { return lua_isnil(L,i); }
static inline int dyn_helper_lua_isboolean(lua_State *L, int i) { return lua_isboolean(L,i); }
static inline int dyn_helper_lua_isthread(lua_State *L, int i) { return lua_isthread(L,i); }
static inline int dyn_helper_lua_isnone(lua_State *L, int i) { return lua_isnone(L,i); }
static inline int dyn_helper_lua_isnoneornil(lua_State *L, int i) { return lua_isnoneornil(L,i); }
