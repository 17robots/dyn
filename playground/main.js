const token = new URLSearchParams(location.hash.slice(1)).get('token') || '';
history.replaceState(null, '', location.pathname);
const button = document.getElementById('run');
button.addEventListener('click', async () => {
  button.disabled = true;
  const status = document.getElementById('status');
  const output = document.getElementById('output');
  status.textContent = 'Compiling…';
  output.textContent = '';
  try {
    const response = await fetch('/run', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Dyn-Token': token}, body: JSON.stringify({source: document.getElementById('source').value})});
    const report = await response.json();
    if (!response.ok) throw new Error(report.error || 'Request failed');
    const result = report.run || report.compile;
    output.textContent = result.stdout + result.stderr;
    status.textContent = result.limit ? `Stopped: ${result.limit}` : `Exited with status ${result.exit_code}`;
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
});
