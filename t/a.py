import sys,os; sys.path.insert(0,os.path.expanduser('~/coinbot'))
import bot1h as b
b.log=lambda m:None
cs_all={}
print(f"{'코인':10}{'5분급등%':>9}{'눌림%':>7} 양봉 EMA위 호가OK  → 판정")
for c in b.top_coins():
    cs=b.candles(c); close=[x['trade_price'] for x in cs]; px=close[-1]; last=cs[-2]
    r5=max(x['high_price'] for x in cs[-7:])/close[-8]-1
    hi=max(x['high_price'] for x in cs[-6:]); pull=1-px/hi
    green=last['trade_price']>last['opening_price'] and px>last['trade_price']
    above=px>b.ema(close[:-1],20); sp=b.spread_ok(c)
    why=[]
    if not(0.01<=r5<=0.08): why.append('급등부족' if r5<0.01 else '과열')
    if not(0.003<=pull<=0.02): why.append('눌림없음' if pull<0.003 else '너무빠짐')
    if not green: why.append('반등X')
    if not above: why.append('EMA아래')
    if not sp: why.append('저가코인')
    print(f"{c:10}{r5*100:9.2f}{pull*100:7.2f}  {'O' if green else 'X'}   {'O' if above else 'X'}    {'O' if sp else 'X'}   → {'진입!' if not why else ','.join(why)}")
