// Classic worker for the pinned upstream UMD core; no shared-memory requirement.
importScripts('./ffmpeg-core.js');
let busy = false;
onmessage = async ({data}) => {
  if (busy) return;
  busy = true;
  try {
    postMessage({type:'progress', text:'Loading FFmpeg and Dyn…'});
    const core = await createFFmpegCore({ locateFile: name => new URL(name, self.location.href).href });
    core.setLogger(() => {});
    const response = await fetch('./filter.wasm');
    if (!response.ok) throw new Error(`Dyn module request failed: ${response.status}`);
    const {instance} = await WebAssembly.instantiate(await response.arrayBuffer());
    const dyn = instance.exports;
    dyn.dyn_initialize();
    const {processVideo} = await import('./pipeline.mjs');
    const result = processVideo(core, dyn, new Uint8Array(data), text => postMessage({type:'progress',text}));
    postMessage({type:'result', bytes:result.buffer}, [result.buffer]);
  } catch (error) {
    postMessage({type:'error', text:String(error)});
  } finally { close(); }
};
