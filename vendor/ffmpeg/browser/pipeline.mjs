// Two independent Wasm memories. Copy explicitly; never pass pointers between them.
export const WIDTH = 160, HEIGHT = 90, FPS = 8, MAX_FRAMES = 8;
export const MAX_INPUT = 16 * 1024 * 1024;
const FRAME_BYTES = WIDTH * HEIGHT * 4;
export function execute(core, args) {
  core.reset();
  core.setTimeout(15000);
  const status = core.exec(...args);
  if (status !== 0) throw new Error(`FFmpeg failed (${status})`);
}
export function processVideo(core, dyn, input, progress = () => {}) {
  if (!(input instanceof Uint8Array) || !input.length || input.length > MAX_INPUT)
    throw new Error('Choose a nonempty video no larger than 16 MiB.');
  let dynUsable = true;
  const callDyn = (name, ...args) => {
    try { return dyn[name](...args); }
    catch (error) { dynUsable = false; throw error; }
  };
  const files = ['input.bin', 'decoded.rgba', 'edited.rgba', 'output.webm'];
  try {
    progress('Decoding up to one second…');
    core.FS.writeFile(files[0], input);
    execute(core, ['-i', files[0], '-an', '-vf', `fps=${FPS},scale=${WIDTH}:${HEIGHT}`, '-frames:v', String(MAX_FRAMES), '-pix_fmt', 'rgba', '-f', 'rawvideo', files[1]]);
    const decoded = core.FS.readFile(files[1]);
    if (!decoded.length || decoded.length % FRAME_BYTES || decoded.length > FRAME_BYTES * MAX_FRAMES)
      throw new Error('Unexpected decoded frame size.');
    progress('Applying grayscale in Dyn…');
    const address = callDyn('allocate', decoded.length) >>> 0;
    if (!address) throw new Error('Dyn arena exhausted');
    // allocate may grow linear memory; acquire the JS view afterward.
    new Uint8Array(dyn.memory.buffer, address, decoded.length).set(decoded);
    callDyn('grayscale', address, decoded.length / 4);
    core.FS.writeFile(files[2], new Uint8Array(dyn.memory.buffer, address, decoded.length));
    progress('Encoding WebM…');
    execute(core, ['-f', 'rawvideo', '-pixel_format', 'rgba', '-video_size', `${WIDTH}x${HEIGHT}`, '-framerate', String(FPS), '-i', files[2], '-an', '-c:v', 'libvpx', '-deadline', 'realtime', '-cpu-used', '8', '-pix_fmt', 'yuv420p', files[3]]);
    // Copy before deleting the native file and discarding the worker.
    return core.FS.readFile(files[3]).slice();
  } finally {
    // Do not reenter an instance after a trap; its worker will be discarded.
    if (dynUsable) dyn.release();
    for (const name of files) { if (core.FS.analyzePath(name).exists) core.FS.unlink(name); }
  }
}
