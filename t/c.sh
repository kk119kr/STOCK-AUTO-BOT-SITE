#!/bin/bash
cd ~/coinbot && clear
python3 - <<'PY'
import os,json,time,uuid,hmac,hashlib,base64,urllib.request
env=dict(l.rstrip('\n').split('=',1) for l in open('.env') if '=' in l)
ak,sk,mode=env['BITHUMB_ACCESS_KEY'],env['BITHUMB_SECRET_KEY'],env.get('BITHUMB_SECRET_MODE','raw')
key=sk.encode() if mode=='raw' else base64.b64decode(sk)
b=lambda d:base64.urlsafe_b64encode(d).rstrip(b'=')
def get(path):
    h=b(json.dumps({"alg":"HS256","typ":"JWT"}).encode()); p=b(json.dumps({"access_key":ak,"nonce":str(uuid.uuid4()),"timestamp":int(time.time()*1000)}).encode())
    t=(h+b'.'+p+b'.'+b(hmac.new(key,h+b'.'+p,hashlib.sha256).digest())).decode()
    try:
        r=urllib.request.urlopen(urllib.request.Request('https://api.bithumb.com'+path,headers={'Authorization':'Bearer '+t}),timeout=10)
        return r.status, r.read().decode()[:1500]
    except urllib.error.HTTPError as e: return e.code, e.read().decode()[:300]
print('mode',mode)
print('accounts:',*get('/v1/accounts'))
print('api_keys:',*get('/v1/api_keys'))
PY
