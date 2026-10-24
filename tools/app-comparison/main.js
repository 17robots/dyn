'use strict';
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
function summary() {
  return {records: 0, bytes: 0, latency_us: 0, errors: 0,
    services: Array.from({length: 16}, () => [0, 0, 0, 0])};
}
function integer(value, max = Number.MAX_SAFE_INTEGER) {
  if (!Number.isInteger(value) || value < 0 || value > max) throw Error('invalid integer');
  return value;
}
function add(out, record) {
  if (record === null || typeof record !== 'object' || Array.isArray(record)) throw Error('expected object');
  if (typeof record.service !== 'string' || !/^svc(?:0[0-9]|1[0-5])$/.test(record.service)) throw Error('invalid service');
  const status = integer(record.status, 599);
  const bytes = integer(record.bytes);
  const latency = integer(record.latency_us);
  const errors = status >= 500 ? 1 : 0;
  if (out.records >= Number.MAX_SAFE_INTEGER || out.bytes > Number.MAX_SAFE_INTEGER - bytes || out.latency_us > Number.MAX_SAFE_INTEGER - latency || out.errors > Number.MAX_SAFE_INTEGER - errors) throw Error('aggregate overflow');
  out.records++; out.bytes += bytes; out.latency_us += latency; out.errors += errors;
  const row = out.services[Number(record.service.slice(3))];
  row[0]++; row[1] += bytes; row[2] += latency; row[3] += errors;
}
function report(file) {
  const out = summary();
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (line.length) add(out, JSON.parse(line));
  }
  return out;
}
function summarize(data) {
  const records = JSON.parse(data);
  if (!Array.isArray(records)) throw Error('expected array');
  const out = summary();
  for (const record of records) add(out, record);
  return out;
}
function search(root) {
  const out = {files: 0, bytes: 0, lines: 0, matching_lines: 0, matching_files: 0};
  function visit(file) {
    const stat = fs.lstatSync(file);
    if (stat.isDirectory()) {
      for (const name of fs.readdirSync(file)) visit(path.join(file, name));
    } else if (stat.isFile() && path.basename(file).endsWith('.txt')) {
      const data = fs.readFileSync(file);
      out.files++; out.bytes += data.length;
      let start = 0, matches = 0;
      while (start < data.length) {
        let end = data.indexOf(10, start);
        if (end < 0) end = data.length;
        out.lines++;
        if (data.subarray(start, end).includes('ERROR')) matches++;
        start = end + 1;
      }
      out.matching_lines += matches;
      if (matches) out.matching_files++;
    }
  }
  visit(root);
  return out;
}
function serve() {
  const server = http.createServer(async (req, res) => {
    const route = req.url.split('?')[0];
    if (req.method === 'GET' && route === '/health') {
      res.writeHead(200); res.end('ok\n');
    } else if (req.method === 'POST' && route === '/quit') {
      res.writeHead(200); res.end('ok\n', () => {
        server.close();
        server.closeIdleConnections();
      });
    } else if (req.method === 'POST' && route === '/summarize') {
      try {
        let length = 0;
        const chunks = [];
        let oversized = false;
        for await (const chunk of req) {
          length += chunk.length;
          if (length > 1048576) oversized = true;
          if (!oversized) chunks.push(chunk);
        }
        if (oversized) { res.writeHead(400, {'Connection': 'close'}); res.end('invalid body\n'); return; }
        const out = summarize(Buffer.concat(chunks).toString('utf8'));
        res.writeHead(200, {'Content-Type': 'application/json'}); res.end(JSON.stringify(out) + '\n');
      } catch (_) {
        if (!res.headersSent) { res.writeHead(400); res.end('invalid JSON or schema\n'); }
      }
    } else { res.writeHead(404); res.end('not found\n'); }
  });
  server.listen(0, '127.0.0.1', () => process.stdout.write(`port ${server.address().port}\n`));
}
function emit(value) {
  const data = Buffer.from(JSON.stringify(value) + '\n');
  let at = 0;
  while (at < data.length) {
    const n = fs.writeSync(1, data, at, data.length - at);
    if (!n) throw Error('stdout write failed');
    at += n;
  }
}
try {
  const [mode, target] = process.argv.slice(2);
  if (mode === 'serve' && process.argv.length === 3) serve();
  else if (mode === 'report' && process.argv.length === 4) emit(report(target));
  else if (mode === 'search' && process.argv.length === 4) emit(search(target));
  else throw Error('usage: app report FILE | search DIRECTORY | serve');
} catch (error) { console.error(error.message); process.exitCode = 1; }
