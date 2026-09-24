// Minimal command runner: no directories or environment variables are granted.
import {readFile} from 'node:fs/promises';
import {WASI} from 'node:wasi';
if (process.argv.length < 3) { console.error('usage: node tools/run-wasi.mjs PROGRAM.wasm [ARGS...]'); process.exit(2); }
const wasi = new WASI({version:'preview1', args:process.argv.slice(2), preopens:{}, env:{}, returnOnExit:true});
const {instance} = await WebAssembly.instantiate(await readFile(process.argv[2]), {wasi_snapshot_preview1:wasi.wasiImport});
process.exitCode = wasi.start(instance);
