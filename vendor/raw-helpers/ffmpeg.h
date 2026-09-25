/* Value-taking error macros; retain FFmpeg's native integer preconditions. */
static inline int dyn_helper_AVERROR(int error) { return AVERROR(error); }
static inline int dyn_helper_AVUNERROR(int error) { return AVUNERROR(error); }
