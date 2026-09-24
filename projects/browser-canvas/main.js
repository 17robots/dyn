const status = document.querySelector('#status');
const button = document.querySelector('button');
try {
  const response = await fetch('./canvas.wasm');
  if (!response.ok) throw new Error(`Module request failed: ${response.status}`);
  const { instance } = await WebAssembly.instantiate(await response.arrayBuffer(), {
    env: { pixels_changed(count) { status.textContent = `Dyn processed ${count} pixels.`; } },
  });
  const dyn = instance.exports;
  dyn.dyn_initialize();
  const count = 128 * 128;
  const address = dyn.allocate(count * 4) >>> 0;
  if (!address) throw new Error('Arena exhausted');
  const pixels = new Uint8ClampedArray(dyn.memory.buffer, address, count * 4);
  for (let i = 0; i < count; ++i) {
    pixels.set([(i % 128) * 2, Math.floor(i / 128) * 2, 160, 255], i * 4);
  }
  const context = document.querySelector('canvas').getContext('2d');
  const render = () => context.putImageData(new ImageData(pixels, 128, 128), 0, 0);
  render();
  button.disabled = false;
  status.textContent = 'Pixels live in a buffer-backed Dyn arena.';
  button.onclick = () => {
    try { dyn.grayscale(address, count); render(); }
    catch (error) { button.disabled = true; status.textContent = String(error); }
  };
  // reset() would invalidate address. Keep this arena alive while displaying it.
} catch (error) { status.textContent = String(error); }
