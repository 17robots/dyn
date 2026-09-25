const status = document.querySelector('#status');
const convert = document.querySelector('#convert'), cancel = document.querySelector('#cancel');
const download = document.querySelector('#download'), video = document.querySelector('video');
let worker, url, timer;
function stop() { clearTimeout(timer); worker?.terminate(); worker = null; convert.disabled = false; cancel.disabled = true; }
cancel.onclick = () => { stop(); status.textContent = 'Cancelled.'; };
convert.onclick = async () => {
  const file = document.querySelector('#file').files[0];
  if (!file || !file.size || file.size > 16 * 1024 * 1024) { status.textContent = 'Choose a nonempty video up to 16 MiB.'; return; }
  convert.disabled = true; cancel.disabled = false;
  const active = worker = new Worker('./worker.js');
  timer = setTimeout(() => { stop(); status.textContent = 'Processing timed out.'; }, 60000);
  active.onerror = event => { if (worker !== active) return; stop(); status.textContent = event.message; };
  active.onmessage = ({data}) => {
    if (worker !== active) return;
    if (data.type === 'progress') status.textContent = data.text;
    else if (data.type === 'error') { stop(); status.textContent = data.text; }
    else if (data.type === 'result') {
      stop(); if (url) URL.revokeObjectURL(url);
      url = URL.createObjectURL(new Blob([data.bytes], {type:'video/webm'}));
      video.src = download.href = url; download.hidden = false;
      status.textContent = 'Finished. Play or download your clip.';
    }
  };
  try { const bytes = await file.arrayBuffer(); if (worker === active) active.postMessage(bytes,[bytes]); }
  catch (error) { if (worker === active) { stop(); status.textContent = String(error); } }
};
addEventListener('pagehide',()=>{stop();if(url)URL.revokeObjectURL(url)});
