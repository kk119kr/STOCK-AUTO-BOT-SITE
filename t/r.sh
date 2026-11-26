#!/bin/bash
cd ~/coinbot && clear && history -c
echo "==== Secret Key 다시 입력 ===="
read -rsp "Secret Key 한 번만 붙여넣고 엔터: " SK; echo
SK_IN="$SK" python3 - <<'PY'
import re,os,json,time,uuid,hmac,hashlib,base64,urllib.request
env={}
for l in open('.env',encoding='utf-8',errors='ignore'):
    if '=' in l: k,v=l.split('=',1); env[k.strip()]=v
cl=lambda v:re.sub(r'\x1b\[20[01]~','',v).strip()
ak=cl(env.get('BITHUMB_ACCESS_KEY','')); sk=cl(os.environ.get('SK_IN',''))
print('Access Key 길이',len(ak),'/ Secret Key 길이',len(sk))
b=lambda d:base64.urlsafe_b64encode(d).rstrip(b'=')
def call(key):
    h=b(json.dumps({"alg":"HS256","typ":"JWT"}).encode()); p=b(json.dumps({"access_key":ak,"nonce":str(uuid.uuid4()),"timestamp":int(time.time()*1000)}).encode())
    t=(h+b'.'+p+b'.'+b(hmac.new(key,h+b'.'+p,hashlib.sha256).digest())).decode()
    try: return json.load(urllib.request.urlopen(urllib.request.Request('https://api.bithumb.com/v1/accounts',headers={'Authorization':'Bearer '+t}),timeout=10)),None
    except urllib.error.HTTPError as e: return None,f"{e.code} {e.read().decode()[:150]}"
d,err=call(sk.encode()); mode='raw'
if d is None:
    try: d,err2=call(base64.b64decode(sk)); mode='b64'
    except Exception: pass
if d is not None:
    open('.env','w').write(f"BITHUMB_ACCESS_KEY={ak}\nBITHUMB_SECRET_KEY={sk}\nBITHUMB_SECRET_MODE={mode}\n"); os.chmod('.env',0o600)
    print('연결 성공 ✅  보유 자산:')
    for a in d: print(' ',a.get('currency'),a.get('balance'))
else: print('실패 ❌',err)
PY
unset SK
