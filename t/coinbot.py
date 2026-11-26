#!/usr/bin/env python3
"""빗썸 24시간 봇 — Claude가 30분마다 계획(코인·진입가·손절·추적값)을 짜고, 봇이 감시·실행·안전장치를 맡는다.
하루(한국시간 0시 기준) 손실 -6% 또는 거래 25회면 그날은 새 매수만 멈추고 다음 날 다시 시작."""
import base64, hashlib, hmac, json, os, sys, time, uuid, shutil, subprocess, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

API = "https://api.bithumb.com"
BASE = ["BTC", "ETH", "XRP", "SOL"]
TOP_N = 15
STABLE = {"USDT", "USDC", "DAI", "USDS", "USDE"}
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
TTY = sys.stdout.isatty()
SL_MIN, SL_MAX, SL_ATR = 0.01, 0.03, 1.5  # 손절: 1분봉 평균폭×1.5 (최소 1%, 최대 3%)
TRAIL_ON, TRAIL_GAP = 0.013, 0.005  # 기본값(재시작 복구용). 평소엔 계획이 정한 값 사용
MAX_SPREAD = 0.001               # 호가 한 칸이 0.1% 넘으면 제외
BAN_SEC = 30 * 60                # 손절 종목 30분 금지
HOLD_MAX = 40 * 60               # 최대 보유 40분
DAY_STOP = -0.06                 # 하루 -6%면 그날 새 매수 중지
MAX_TRADES = 25                  # 하루 거래 횟수
COOLDOWN = 10
PLAN_SEC = 1800                  # 계획 주기(30분)
MIN_PRICE = 100                  # 100원 미만 코인은 제외
BASEDIR = os.path.dirname(os.path.abspath(__file__))
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


_LAST_TOP = None


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
        global _LAST_TOP
        if top != _LAST_TOP: log("🎯 대상: " + " ".join(top)); _LAST_TOP = top
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


def px_of(c):
    return float(req("GET", f"/v1/ticker?markets=KRW-{c}")[0]["trade_price"])


def equity():
    """원화 + 코인 평가액 (5천원 미만 자투리 코인은 무시), 그리고 보유 코인 목록."""
    accts = req("GET", "/v1/accounts", auth=True)
    krw, held = 0.0, []
    for a in accts:
        cur, bal = a["currency"], float(a["balance"]) + float(a.get("locked") or 0)
        if cur == "KRW":
            krw += bal; continue
        if bal <= 0: continue
        try: p = px_of(cur)
        except Exception: continue
        if bal * p >= 5000:
            held.append((bal * p, cur, float(a.get("avg_buy_price") or 0) or p))
            krw += bal * p
    return krw, sorted(held, reverse=True)


LEAN = "You are a crypto short-term trading planner. Reply with exactly one JSON object and nothing else."


def ask_claude(prompt, timeout=240):
    cmd0 = env.get("CLAUDE_CMD", "claude")
    if not shutil.which(cmd0): raise RuntimeError("claude 명령 없음")
    work = os.path.join(BASEDIR, "work"); os.makedirs(work, exist_ok=True)
    last = ""
    for lean in (True, False):
        cmd = [cmd0, "-p", prompt, "--model", env.get("CLAUDE_MODEL", "sonnet"), "--output-format", "json"]
        if lean: cmd += ["--system-prompt", LEAN, "--no-session-persistence", "--tools", ""]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=work)
        try: d = json.loads(r.stdout)
        except Exception: d = None
        if isinstance(d, dict) and "result" in d:
            try:
                with open(os.path.join(BASEDIR, "claude_usage.jsonl"), "a") as f:
                    f.write(json.dumps({"ts": datetime.now(KST).isoformat(timespec="seconds"), "cost": d.get("total_cost_usd"), "ms": d.get("duration_ms")}) + "\n")
            except Exception: pass
            if r.returncode == 0 and not d.get("is_error"): return str(d["result"])
            last = str(d.get("result"))[:150]; continue
        last = (r.stderr or r.stdout or "")[:150]
    raise RuntimeError(last or "claude 실패")


def snapshot(c):
    cs = candles(c, 60)
    cl = [x["trade_price"] for x in cs]; px = cl[-1]
    ch = lambda n: round((px / cl[-1 - n] - 1) * 100, 2) if len(cl) > n else 0
    atr = sum((x["high_price"] - x["low_price"]) / x["trade_price"] for x in cs[-15:-1]) / 14 * 100
    u = req("GET", f"/v1/orderbook?markets=KRW-{c}")[0]["orderbook_units"][0]
    a, b = float(u["ask_price"]), float(u["bid_price"])
    return {"coin": c, "price": px, "chg5m%": ch(5), "chg30m%": ch(30), "chg60m%": ch(59),
            "high60m": max(x["high_price"] for x in cs), "low60m": min(x["low_price"] for x in cs),
            "atr1m%": round(atr, 3), "spread%": round((a - b) / b * 100, 3)}


def validate_plan(d, snaps):
    byc = {s_["coin"]: s_ for s_ in snaps}
    mode = "trade" if d.get("mode") == "trade" else "rest"
    picks = []
    for p in (d.get("picks") or [])[:3]:
        try:
            c = str(p["coin"]).upper().replace("KRW-", "")
            sn = byc.get(c)
            if not sn or sn["price"] < MIN_PRICE or sn["spread%"] > MAX_SPREAD * 100: continue
            ent = p["entry"]; lv = float(p["level"])
            if ent not in ("dip", "break") or abs(lv / sn["price"] - 1) > 0.03: continue
            clamp = lambda x, lo, hi: min(hi, max(lo, float(x)))
            picks.append({"c": c, "entry": ent, "level": lv, "sl": clamp(p.get("sl", 0.012), SL_MIN, SL_MAX),
                          "ton": clamp(p.get("trail_on", 0.015), 0.012, 0.03), "tgap": clamp(p.get("trail_gap", 0.006), 0.004, 0.012)})
        except Exception:
            continue
    if mode == "trade" and not picks: mode = "rest"
    return {"mode": mode, "picks": picks, "note": str(d.get("note", ""))[:80]}


def make_plan(coins, st):
    snaps = []
    for c in coins:
        try:
            sn = snapshot(c)
            if sn["price"] >= MIN_PRICE: snaps.append(sn)
        except Exception: pass
    e, _ = equity()
    prompt = (
        "빗썸 원화마켓 단타 봇의 다음 30분 계획을 짜라. 아래는 거래대금 상위 코인의 현재 상태다.\n"
        + json.dumps(snaps, ensure_ascii=False) + "\n"
        f"오늘 손익 {e - st['eq0']:+,.0f}원 (시작 {st['eq0']:,.0f}원), 오늘 거래 {st.get('trades', 0)}회, 최근 결과: {st.get('hist', [])[-6:]}\n"
        "조건: 왕복 비용(수수료+체결 미끄러짐)이 약 0.6%라서 +1% 이상 먹을 자리만 노려라. 이미 5분에 +5% 넘게 급등한 코인은 꼭지일 확률이 높으니 피하라. "
        "진입 횟수는 적을수록 좋고, 확신이 없으면 쉬는 것이 정답이다. 코인은 최대 3개.\n"
        'JSON 형식: {"mode":"trade" 또는 "rest","note":"한 줄 이유","picks":[{"coin":"XRP","entry":"dip"(현재가 이하 level까지 내려오면 매수) 또는 "break"(level 위로 오르면 매수),'
        '"level":가격(현재가 ±3% 이내),"sl":손절비율 0.01~0.03,"trail_on":추적시작 수익률 0.012~0.03,"trail_gap":고점 대비 추적폭 0.004~0.012}]}')
    raw = ask_claude(prompt)
    i, j = raw.find("{"), raw.rfind("}")
    return validate_plan(json.loads(raw[i:j + 1]), snaps)


def load_state():
    try: return json.load(open(STATE))
    except Exception: return {}


def save_state(st):
    tmp = STATE + ".tmp"; json.dump(st, open(tmp, "w"), ensure_ascii=False); os.replace(tmp, STATE)


def status(msg):
    if TTY:
        sys.stdout.write("\r  " + msg + "   "); sys.stdout.flush()


def main():
    st = load_state()
    eq, held = equity()
    pos = None
    if held:                                  # 재시작: 들고 있던 코인을 이어서 관리
        _, c, avg = held[0]
        p = st.get("pos") if (st.get("pos") or {}).get("c") == c else None
        pos = p or {"c": c, "entry": avg, "peak": max(avg, px_of(c)), "t": time.time(), "sl": SL_MIN, "ton": TRAIL_ON, "tgap": TRAIL_GAP}
        log(f"♻️ 보유 중인 {c} 이어서 관리 (평단 {pos['entry']:,.6g}원)")
    log(f"🚀 24시간 봇 시작 — 평가액 {eq:,.0f}원{' (DRY)' if DRY else ''}")
    last_exit, coins, coins_at, beat = 0, BASE, 0, 0
    plan, next_plan = None, 0
    while True:
        now = time.time()
        today = datetime.now(KST).strftime("%Y-%m-%d")
        try:
            if st.get("day") != today:        # 0시: 하루 기록 리셋
                if st.get("day"):
                    e, _ = equity()
                    log(f"📅 {st['day']} 마감 — {st['eq0']:,.0f} → {e:,.0f}원 ({e-st['eq0']:+,.0f}원), 거래 {st.get('trades', 0)}회")
                e, _ = equity()
                st = {"day": today, "eq0": e, "trades": 0, "stop": False, "ban": {}, "pos": pos, "hist": st.get("hist", [])}
                save_state(st)
            if pos:
                c = pos["c"]; px = px_of(c)
                pnl = px / pos["entry"] - 1
                pos["peak"] = max(pos["peak"], px)
                reason = None
                if pnl <= -pos["sl"]: reason = "손절"
                elif pos["peak"] / pos["entry"] - 1 >= pos.get("ton", TRAIL_ON) and px <= pos["peak"] * (1 - pos.get("tgap", TRAIL_GAP)): reason = "추적익절"
                elif now - pos["t"] >= HOLD_MAX: reason = "시간청산"
                if reason:
                    b, raw = balances()
                    sell(c, raw.get(c, "0"))
                    b, _ = wait_coin(c, False)
                    e, _ = equity()
                    log(f"🔴 {reason} {c} {px:,.6g}원 ({pnl*100:+.2f}%) → 평가액 {e:,.0f}원 / 오늘 {e-st['eq0']:+,.0f}원")
                    st.setdefault("hist", []).append(f"{c} {reason} {pnl*100:+.2f}%"); st["hist"] = st["hist"][-8:]
                    if reason == "손절": st["ban"][c] = now + BAN_SEC
                    pos = None; last_exit = time.time(); st["trades"] += 1
                    if e / st["eq0"] - 1 <= DAY_STOP and not st["stop"]:
                        st["stop"] = True; log(f"⛔ 오늘 손실 한도({DAY_STOP*100:.0f}%) — 내일 0시까지 새 매수 중지")
                    if st["trades"] >= MAX_TRADES and not st["stop"]:
                        st["stop"] = True; log("⛔ 오늘 거래 횟수 한도 — 내일 0시까지 새 매수 중지")
                else:
                    status(f"보유 {c} {px:,.6g}원 {pnl*100:+.2f}% (고점 {pos['peak']:,.6g})")
                st["pos"] = pos; save_state(st)
                time.sleep(3); continue
            if now - beat >= 1800:
                beat = now; e, _ = equity()
                log(f"💤 관망 중 — 평가액 {e:,.0f}원, 오늘 {e-st['eq0']:+,.0f}원, 거래 {st['trades']}회{' (오늘 매수 중지)' if st['stop'] else ''}")
            if st["stop"] or now - last_exit < COOLDOWN:
                time.sleep(15); continue
            if plan is None or now >= next_plan:
                coins = top_coins()
                try:
                    plan = make_plan(coins, st); plan["at"] = now; next_plan = now + PLAN_SEC
                    log(f"🧠 계획: {plan['mode']} — {plan['note']} / " + (", ".join(f"{p['c']} {p['entry']}@{p['level']:,.6g} 손절-{p['sl']*100:.1f}%" for p in plan["picks"]) or "대상 없음"))
                except Exception as e:
                    plan = {"mode": "rest", "picks": [], "at": now, "note": ""}; next_plan = now + 300
                    log(f"⚠️ 계획 실패({str(e)[:90]}) — 5분 쉬고 다시 시도")
            best = None
            if plan["mode"] == "trade" and now - plan["at"] < PLAN_SEC + 300:
                for p in plan["picks"]:
                    if st["ban"].get(p["c"], 0) >= now: continue
                    px = px_of(p["c"])
                    ok = (p["entry"] == "dip" and p["level"] * 0.985 <= px <= p["level"]) or (p["entry"] == "break" and p["level"] <= px <= p["level"] * 1.015)
                    if ok and spread_ok(p["c"]): best = p; break
            if best:
                c, sl = best["c"], best["sl"]
                plan["picks"].remove(best)
                b, _ = balances(); krw = b.get("KRW", 0)
                if krw < 6000:
                    log("원화 부족 — 10분 뒤 다시 확인"); time.sleep(600); continue
                buy(c, krw * USE)
                b, raw = wait_coin(c, True)
                if DRY:
                    entry = px_of(c)
                else:
                    acct = [a for a in req("GET", "/v1/accounts", auth=True) if a["currency"] == c]
                    if not acct or float(acct[0]["balance"]) <= 0:
                        log(f"⚠️ {c} 매수 체결 확인 안 됨 — 5분 쉬고 잔고로 다시 확인"); time.sleep(300)
                        _, held = equity()
                        if held:
                            _, c2, avg = held[0]
                            pos = {"c": c2, "entry": avg, "peak": avg, "t": time.time(), "sl": sl}
                        continue
                    entry = float(acct[0]["avg_buy_price"]) or px_of(c)
                pos = {"c": c, "entry": entry, "peak": entry, "t": time.time(), "sl": sl, "ton": best["ton"], "tgap": best["tgap"]}
                st["pos"] = pos; save_state(st)
                log(f"🟢 매수 {c} {entry:,.6g}원 ({best["entry"]}@{best["level"]:,.6g}, 손절 -{sl*100:.1f}%, 추적 +{best["ton"]*100:.1f}%/-{best["tgap"]*100:.1f}%)")
            else:
                status(f"관망 중… 오늘 거래 {st['trades']}회")
            time.sleep(10)
        except Exception as e:
            log(f"⚠️ 오류: {e}"); time.sleep(10)


if __name__ == "__main__":
    main()
