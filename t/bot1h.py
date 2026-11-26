#!/usr/bin/env python3
"""빗썸 1시간 테스트 봇 — 공격형: 거래대금 상위 15종목 급등 후 눌림 매수, 추적 익절."""
import base64, hashlib, hmac, json, os, sys, time, uuid, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

API = "https://api.bithumb.com"
BASE = ["BTC", "ETH", "XRP", "SOL"]
TOP_N = 15
STABLE = {"USDT", "USDC", "DAI", "USDS", "USDE"}
RUN_MIN = float(os.environ.get("RUN_MIN", 60))
SL_MIN, SL_MAX, SL_ATR = 0.01, 0.03, 1.5  # 손절: 1분봉 평균폭×1.5 (최소 1%, 최대 3%)
TRAIL_ON, TRAIL_GAP = 0.01, 0.007  # +1% 넘으면 고점 대비 -0.7% 추적 (고정 익절 없음)
MAX_SPREAD = 0.001               # 호가 한 칸이 0.1% 넘으면 제외
BAN_SEC = 30 * 60                # 손절 종목 30분 금지
HOLD_MAX = 40 * 60               # 최대 보유 40분
DAY_STOP = -0.06                 # 누적 -6%면 그 자리에서 종료
MAX_TRADES = 25
COOLDOWN = 10
USE = 0.995                      # 원화의 99.5%로 매수
DRY = os.environ.get("DRY") == "1"
KST = timezone(timedelta(hours=9))

env = {}
for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")):
    if "=" in l:
        k, v = l.rstrip("\n").split("=", 1); env[k] = v
AK, SK = env["BITHUMB_ACCESS_KEY"], env["BITHUMB_SECRET_KEY"]
KEY = SK.encode() if env.get("BITHUMB_SECRET_MODE", "raw") == "raw" else base64.b64decode(SK)


def log(msg):
    print(f"\r\x1b[2K{datetime.now(KST):%H:%M:%S} {msg}", flush=True)


def _b(d): return base64.urlsafe_b64encode(d).rstrip(b"=")


def token(query=None):
    p = {"access_key": AK, "nonce": str(uuid.uuid4()), "timestamp": int(time.time() * 1000)}
    if query:
        p["query_hash"] = hashlib.sha512(query.encode()).hexdigest(); p["query_hash_alg"] = "SHA512"
    h = _b(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()); pl = _b(json.dumps(p).encode())
    return (h + b"." + pl + b"." + _b(hmac.new(KEY, h + b"." + pl, hashlib.sha256).digest())).decode()


def req(method, path, body=None, auth=False):
    headers = {}
    data = None
    if auth:
        q = "&".join(f"{k}={v}" for k, v in body.items()) if body else None
        headers["Authorization"] = "Bearer " + token(q)
    if body is not None:
        data = json.dumps(body).encode(); headers["Content-Type"] = "application/json"
    for i in range(3):
        try:
            r = urllib.request.urlopen(urllib.request.Request(API + path, data=data, headers=headers, method=method), timeout=10)
            return json.load(r)
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:200]
            if e.code == 429 or e.code >= 500:
                time.sleep(1 + i); continue
            raise RuntimeError(f"{e.code} {msg}")
        except (urllib.error.URLError, TimeoutError) as e:
            time.sleep(1 + i); last = e
    raise RuntimeError(f"네트워크 오류 {path}")


def balances():
    accts = req("GET", "/v1/accounts", auth=True)
    return {a["currency"]: float(a["balance"]) for a in accts}, {a["currency"]: a["balance"] for a in accts}


def candles(c, n=25):
    return req("GET", f"/v1/candles/minutes/1?market=KRW-{c}&count={n}")[::-1]  # 오래된→최신


def top_coins():
    """원화마켓 24시간 거래대금 상위 TOP_N (스테이블코인 제외). 실패하면 기본 4종."""
    try:
        mk = [m["market"] for m in req("GET", "/v1/market/all?isDetails=false") if m["market"].startswith("KRW-")]
        tk = []
        for i in range(0, len(mk), 100):
            tk += req("GET", "/v1/ticker?markets=" + ",".join(mk[i:i + 100]))
        tk = [t for t in tk if t["market"][4:] not in STABLE]
        tk.sort(key=lambda t: float(t.get("acc_trade_price_24h") or 0), reverse=True)
        top = [t["market"][4:] for t in tk[:TOP_N]]
        log("🎯 대상: " + " ".join(top))
        return top or BASE
    except Exception as e:
        log(f"⚠️ 상위 코인 조회 실패({e}) — 기본 4종 사용"); return BASE


def ema(xs, n):
    k, e = 2 / (n + 1), xs[0]
    for x in xs[1:]: e = x * k + e * (1 - k)
    return e


def signal(cs):
    """급등 후 눌림 반등. (점수, 손절폭) — 점수 0이면 진입 안 함.
    5분 +1~8% 급등 → 최근 고점에서 0.3~2% 눌림 → 직전봉 양봉 + 현재가가 직전 종가 위 + EMA20 위."""
    if len(cs) < 22: return 0, 0
    close = [x["trade_price"] for x in cs]
    px, last = close[-1], cs[-2]
    r5 = max(x["high_price"] for x in cs[-7:]) / close[-8] - 1
    if r5 < 0.01 or r5 > 0.08: return 0, 0
    hi = max(x["high_price"] for x in cs[-6:])
    pull = 1 - px / hi
    if pull < 0.003 or pull > 0.02: return 0, 0
    if last["trade_price"] <= last["opening_price"] or px <= last["trade_price"]: return 0, 0
    if px <= ema(close[:-1], 20): return 0, 0
    atr = sum((x["high_price"] - x["low_price"]) / x["trade_price"] for x in cs[-15:-1]) / 14
    return r5, min(SL_MAX, max(SL_MIN, atr * SL_ATR))


def spread_ok(c):
    try:
        u = req("GET", f"/v1/orderbook?markets=KRW-{c}")[0]["orderbook_units"][0]
        a, b = float(u["ask_price"]), float(u["bid_price"])
        return (a - b) / b <= MAX_SPREAD
    except Exception:
        return float(req("GET", f"/v1/ticker?markets=KRW-{c}")[0]["trade_price"]) >= 1000


def buy(c, krw):
    body = {"market": f"KRW-{c}", "side": "bid", "order_type": "price", "price": str(int(krw))}
    if DRY: log(f"[DRY] 매수 {body}"); return
    req("POST", "/v2/orders", body, auth=True)


def sell(c, vol_str):
    body = {"market": f"KRW-{c}", "side": "ask", "order_type": "market", "volume": vol_str}
    if DRY: log(f"[DRY] 매도 {body}"); return
    req("POST", "/v2/orders", body, auth=True)


def wait_coin(c, want_pos, sec=15):
    for _ in range(sec):
        b, raw = balances()
        px = float(req("GET", f"/v1/ticker?markets=KRW-{c}")[0]["trade_price"])
        if (b.get(c, 0) * px >= 1000) == want_pos: return b, raw
        time.sleep(1)
    return b, raw


def main():
    start = time.time(); end = start + RUN_MIN * 60
    b, raw = balances()
    krw0 = b.get("KRW", 0)
    log(f"🚀 시작 — 원화 {krw0:,.0f}원, {RUN_MIN:.0f}분 운용{' (DRY)' if DRY else ''}")
    if krw0 < 6000 and not DRY:
        log("원화가 6,000원 미만이라 종료"); return
    pos = None; trades = 0; last_exit = 0; coins, coins_at = BASE, 0; ban = {}
    while True:
        now = time.time()
        try:
            if pos:
                c = pos["c"]
                px = float(req("GET", f"/v1/ticker?markets=KRW-{c}")[0]["trade_price"])
                pnl = px / pos["entry"] - 1
                pos["peak"] = max(pos["peak"], px)
                reason = None
                if pnl <= -pos["sl"]: reason = "손절"
                elif pos["peak"] / pos["entry"] - 1 >= TRAIL_ON and px <= pos["peak"] * (1 - TRAIL_GAP): reason = "추적익절"
                elif now - pos["t"] >= HOLD_MAX: reason = "시간청산"
                elif now >= end: reason = "종료청산"
                if reason:
                    b, raw = balances()
                    sell(c, raw.get(c, "0"))
                    b, _ = wait_coin(c, False)
                    krw = b.get("KRW", 0)
                    log(f"🔴 {reason} {c} {px:,.6g}원 ({pnl*100:+.2f}%) → 원화 {krw:,.0f}원 / 누적 {krw-krw0:+,.0f}원")
                    if reason == "손절": ban[c] = time.time() + BAN_SEC
                    pos = None; last_exit = time.time(); trades += 1
                    if (krw / krw0 - 1) <= DAY_STOP: log(f"⛔ 누적 손실 한도({DAY_STOP*100:.0f}%) 도달 — 종료"); break
                else:
                    sys.stdout.write(f"\r  보유 {c} {px:,.6g}원 {pnl*100:+.2f}% (고점 {pos['peak']:,.6g})   "); sys.stdout.flush()
                time.sleep(3); continue
            if now >= end: log("⏰ 1시간 종료"); break
            if trades >= MAX_TRADES: log("거래 횟수 한도 도달 — 종료"); break
            if now - last_exit < COOLDOWN: time.sleep(5); continue
            if now - coins_at > 600: coins, coins_at = top_coins(), now
            cands = sorted(((signal(candles(c)), c) for c in coins if ban.get(c, 0) < now), key=lambda x: -x[0][0])
            best = next((x for x in cands if x[0][0] > 0 and spread_ok(x[1])), None)
            if best:
                (score, sl), c = best
                b, _ = balances(); krw = b.get("KRW", 0)
                if krw < 6000: log("원화 부족 — 종료"); break
                buy(c, krw * USE)
                b, raw = wait_coin(c, True)
                if DRY:
                    entry = float(req("GET", f"/v1/ticker?markets=KRW-{c}")[0]["trade_price"])
                else:
                    acct = [a for a in req("GET", "/v1/accounts", auth=True) if a["currency"] == c]
                    if not acct or float(acct[0]["balance"]) <= 0:
                        log(f"⚠️ {c} 매수 체결 확인 안 됨 — 종료"); break
                    entry = float(acct[0]["avg_buy_price"]) or float(req("GET", f"/v1/ticker?markets=KRW-{c}")[0]["trade_price"])
                pos = {"c": c, "entry": entry, "peak": entry, "t": time.time(), "sl": sl}
                log(f"🟢 매수 {c} {entry:,.4g}원 (5분 급등 {score*100:+.2f}% 후 눌림, 손절 -{sl*100:.1f}%)")
            else:
                left = (end - now) / 60
                sys.stdout.write(f"\r  관망 중… 남은 {left:4.1f}분, 거래 {trades}회   "); sys.stdout.flush()
            time.sleep(15)
        except Exception as e:
            log(f"⚠️ 오류: {e}"); time.sleep(10)
    b, _ = balances()
    krw = b.get("KRW", 0)
    left = {k: v for k, v in b.items() if k != "KRW" and v > 0}
    log(f"🏁 끝 — 원화 {krw0:,.0f} → {krw:,.0f}원 ({krw-krw0:+,.0f}원), 거래 {trades}회{', 남은 코인 '+str(left) if left else ''}")


if __name__ == "__main__":
    main()
