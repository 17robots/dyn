from pathlib import Path
import subprocess,hashlib,json
n=Path(__file__).resolve().parent;w=n.parent/'json-twins-20261024';want=json.loads((w/'corpus-verification.json').read_text())['normalized_sha256'];results={}
for mode in (0,1):
 path=n/f'corpus-after-{mode}.jsonl'
 with path.open('wb') as f:subprocess.run([str(w/'driver'),str(n/'dyn-after.so'),'batch',str(mode),str(w/'corpus.bin')],stdout=f,check=True,timeout=120)
 h=hashlib.sha256(path.read_bytes()).hexdigest();assert h==want,(mode,h,want);results[str(mode)]=h;path.unlink()
(n/'corpus-proof.json').write_text(json.dumps({'records':60000,'nodes_per_record':25,'sha256_by_mode':results},indent=2));print('PASS 60000 exact documents and traces in both modes')
