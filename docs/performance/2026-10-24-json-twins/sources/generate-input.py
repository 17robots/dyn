from pathlib import Path
import json,hashlib
out=Path(__file__).resolve().parent/'events.jsonl'
with out.open('wb') as f:
 for i in range(60000):
  obj={'id':i,'service':f'svc{(i*7)%16:02}','status':503 if i%17==0 else (404 if i%11==0 else 200),'bytes':(i*7919)%65536,'latency_us':(i*131)%250000,'path':f'/api/v1/items/{i%1000}?page={i%17}','message':'request "done"\t café snowman ☃','tags':['edge',f'zone-{i%8}'],'context':{'cached':i%3==0,'attempt':i%4+1}}
  f.write(json.dumps(obj,ensure_ascii=i%3==0,separators=(',',':')).encode())
  if i!=59999:f.write(b'\n')
  if i%997==0:f.write(b'\n')
sha=hashlib.sha256(out.read_bytes()).hexdigest()
assert sha=='55632bc536a41285c2126eb1a0d684fc6778c303b95bdf380e9c3f8b509abfca',sha
print(out,sha)
