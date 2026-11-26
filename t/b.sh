#!/bin/bash
cd ~/coinbot && clear && history -c
python3 - <<'PY'
import re,os,json,time,uuid,hmac,hashlib,base64,urllib.request
env={}
for l in open('.env',encoding='utf-8',errors='ignore'):
    if '=' in l:
        k,v=l.split('=',1); env[k.strip()]=v
def clean(v): return re.sub(r'\x1b\[20[01]~','',v).strip()
ak,sk=clean(env.get('BITHUMB_ACCESS_KEY','')),clean(env.get('BITHUMB_SECRET_KEY',''))
open('.env','w').write(f"BITHUMB_ACCESS_KEY={ak}\nBITHUMB_SECRET_KEY={sk}\n"); os.chmod('.env',0o600)
print('Access Key 길이',len(ak),'/ Secret Key 길이',len(sk))
b=lambda d:base64.urlsafe_b64encode(d).rstrip(b'=')
h=b(json.dumps({"alg":"HS256","typ":"JWT"}).encode()); p=b(json.dumps({"access_key":ak,"nonce":str(uuid.uuid4()),"timestamp":int(time.time()*1000)}).encode())
t=(h+b'.'+p+b'.'+b(hmac.new(sk.encode(),h+b'.'+p,hashlib.sha256).digest())).decode()
r=urllib.request.Request('https://api.bithumb.com/v1/accounts',headers={'Authorization':'Bearer '+t})
try:
    d=json.load(urllib.request.urlopen(r,timeout=10))
    print('연결 성공 ✅  보유 자산:')
    for a in d: print(' ',a.get('currency'),a.get('balance'))
except urllib.error.HTTPError as e: print('실패 ❌',e.code,e.read().decode()[:200])
PY
