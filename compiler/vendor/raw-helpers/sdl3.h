/* C macro spelling retained; arguments are evaluated once at this call seam. */
static inline bool dyn_helper_SDL_MUSTLOCK(SDL_Surface *s) { return SDL_MUSTLOCK(s); }
/* Defined for the native SDL button range, 1..32. */
static inline Uint32 dyn_helper_SDL_BUTTON_MASK(Uint32 button) { return SDL_BUTTON_MASK(button); }
static inline int dyn_helper_SDL_VERSIONNUM(int major, int minor, int patch) { return SDL_VERSIONNUM(major,minor,patch); }
static inline bool dyn_helper_SDL_VERSION_ATLEAST(int major, int minor, int patch) { return SDL_VERSION_ATLEAST(major,minor,patch); }
