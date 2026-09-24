# collect_data.py  ―  차트프로 미국 관제탑 · ① 데이터 수집
# =========================================================
# 이 파일이 하는 일 = "장보기"
#   여러 가게(야후·FRED·캘린더·뉴스)를 돌면서 재료를 사 와서
#   data_YYYYMMDD.json 이라는 장바구니 하나에 담습니다.
#   해석(요리)은 generate_report.py 가, 상차림은 build_html.py 가 합니다.
#
# 중요 원칙 3가지
#   1) 한 가게가 문을 닫아도(에러) 나머지 장보기는 계속한다  → safe() 로 감쌈
#   2) 못 산 재료는 지어내지 않는다                        → None 으로 남김
#   3) 어느 가게에서 뭘 샀는지 영수증을 남긴다               → _sources 로그
# =========================================================

SCRIPT_VERSION = "v2026.09.24-2"     # ⬅ 배포 버전 확인용 (리포트 하단에 찍힘)

import os, io, csv, json, time, traceback
import datetime as dt
import urllib.request
import pandas as pd
import yfinance as yf

# ── 설정값 (여기만 바꾸면 동작이 바뀝니다) ───────────────
TZ_OFFSET_H   = 9          # 한국시간(UTC+9)
VOL_SURGE     = 1.20       # 레이더: 거래량이 평소의 몇 배 이상이어야 하나
ALERT_DROP    = -3.0       # 경보 레이더: 등락률 몇 % 이하
STRONG_RISE   = 1.5        # 강세 레이더: 등락률 몇 % 이상
NEAR_HIGH     = -10.0      # 52주 고점 대비 몇 % 안쪽이면 보너스
NEAR_BONUS    = 5.0        # 그 보너스 점수
MIN_THEME_AMT = 3.0        # 테마 ETF 최소 평균거래대금(백만 달러) — 너무 작으면 버림
SEC_UA        = "ChartPro US Tower (contact@example.com)"   # ⬅ 본인 이메일로 교체

# ── 영수증(로그) ───────────────────────────────────────
SOURCES = {}
def safe(name, fn, *a, **kw):
    """가게 한 곳 들르기. 실패해도 프로그램을 멈추지 않고 None 을 돌려줍니다."""
    t0 = time.time()
    try:
        r = fn(*a, **kw)
        n = len(r) if hasattr(r, "__len__") else 1
        SOURCES[name] = {"ok": True, "n": n, "sec": round(time.time()-t0, 1)}
        print(f"  ✅ {name:22s} {n:>5}건  {round(time.time()-t0,1)}s")
        return r
    except Exception as e:
        SOURCES[name] = {"ok": False, "err": str(e)[:200], "sec": round(time.time()-t0, 1)}
        print(f"  ❌ {name:22s} 실패: {str(e)[:110]}")
        return None

def get(url, timeout=25, ua=None):
    req = urllib.request.Request(url, headers={"User-Agent": ua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


# ════════════════════════════════════════════════════════
# 0. 수집 대상 목록
# ════════════════════════════════════════════════════════

# ① 지수·매크로 (ARRIVALS BOARD + 1년 자리표)
IDX = {
    "^GSPC":"S&P500", "^IXIC":"나스닥", "^DJI":"다우", "^RUT":"러셀2000",
    "^SOX":"필라델피아반도체", "^VIX":"VIX", "^VIX9D":"VIX 9일", "^VIX3M":"VIX 3개월",
    "^TNX":"미국채10년", "DX-Y.NYB":"달러인덱스", "CL=F":"WTI", "GC=F":"금",
    "KRW=X":"원달러", "EWY":"한국ETF", "BTC-USD":"비트코인",
}

# ② 아시아 선행 시계 (오늘 서울 GATE 7)
ASIA = {"^N225":"니케이225", "^TWII":"대만가권", "^HSI":"항셍", "000001.SS":"상해종합",
        "ES=F":"S&P선물", "NQ=F":"나스닥선물"}

# ③ 한국 ADR 보드 (오늘 서울 GATE 8) — 같은 회사의 '야간 시세'
ADR = {"PKX":("POSCO홀딩스","철강"), "SKM":("SK텔레콤","통신"), "KB":("KB금융","은행"),
       "SHG":("신한지주","은행"), "WF":("우리금융","은행"), "LPL":("LG디스플레이","디스플레이"),
       "KT":("KT","통신")}

# ④ 레이더 스캔 대상 127종목
RADAR = ("NVDA MU AMD AVGO TSM INTC AMAT LRCX KLAC ASML TER ONTO ARM QCOM TXN ADI MCHP NXPI GFS SNPS CDNS "
"AAPL MSFT GOOGL AMZN META TSLA NFLX ORCL CRM ADBE NOW PLTR SNOW UBER ABNB COIN "
"XOM CVX COP SLB OXY PSX VLO MPC HAL BKR JPM BAC GS MS C WFC BLK SCHW AXP V MA "
"UNH LLY JNJ MRK PFE ABBV TMO ABT AMGN GILD VRTX REGN CAT DE HON GE BA LMT RTX UNP UPS FDX ETN PH "
"LIN APD SHW NUE FCX DOW ECL ALB PG KO PEP WMT COST MCD NKE SBUX HD LOW TGT "
"NEE DUK SO D AEP EXC PLD AMT CCI EQIX SPG O PKX LPL KB SKM "
"SMCI DELL HPQ WDC STX ANET CIEN VRT MRVL").split()

# ⑤ 국내 대응처가 있는 종목 → "한국 직결 레이더"에 쓰임
KR_LINK = {
 "MU":"삼성전자·SK하이닉스(메모리)","WDC":"낸드·SSD","STX":"HDD·낸드","TSM":"파운드리·소부장",
 "AMAT":"반도체 장비","LRCX":"반도체 장비","KLAC":"검사장비","ASML":"노광 장비",
 "TER":"테스트 장비","ONTO":"검사장비","AVGO":"HBM·커스텀칩","NVDA":"HBM 수요처",
 "INTC":"파운드리 경쟁","ARM":"팹리스·디자인하우스","QCOM":"모바일 부품","MRVL":"커스텀 실리콘",
 "SMCI":"서버·전력기기","VRT":"데이터센터 전력","ANET":"네트워크 장비",
 "LPL":"LG디스플레이","PKX":"POSCO홀딩스","KB":"KB금융","SKM":"SK텔레콤",
 "TSLA":"2차전지 3사","ALB":"리튬·양극재","FCX":"비철금속","NUE":"철강",
 "VLO":"정유","XOM":"정유·조선","CAT":"건설기계","BA":"항공부품",
}

# ⑥ 테마 ETF = 미국판 '네이버 테마'
#    미국엔 공식 테마 분류가 없고, 테마가 ETF로 상장돼 거래됩니다.
#    즉 ETF 시세 = 그 테마에 실제로 들어간 돈의 온도.
THEME = {
 # 반도체·AI·테크
 "SMH":("반도체","테크"), "XSD":("반도체(동일가중)","테크"), "PSI":("반도체장비","테크"),
 "BOTZ":("AI·로보틱스","테크"), "AIQ":("AI소프트웨어","테크"), "ARKK":("파괴적혁신","테크"),
 "QTUM":("양자컴퓨팅","테크"), "IGV":("소프트웨어","테크"), "SKYY":("클라우드","테크"),
 "WCLD":("클라우드SW","테크"), "ROBO":("로보틱스","테크"),
 # 보안·금융
 "CIBR":("사이버보안","테크"), "HACK":("사이버보안(대안)","테크"),
 "IPAY":("결제","금융"), "ARKF":("핀테크","금융"), "IAI":("증권·거래소","금융"),
 "KBE":("은행","금융"), "KRE":("지역은행","금융"),
 # 크립토
 "BLOK":("블록체인","크립토"), "DAPP":("디지털자산","크립토"),
 # 바이오·헬스
 "XBI":("바이오텍","헬스"), "IBB":("바이오","헬스"), "ARKG":("유전체","헬스"),
 "IHI":("의료기기","헬스"), "PPH":("제약","헬스"),
 # 전기차·배터리·에너지전환
 "LIT":("리튬·배터리","에너지전환"), "IDRV":("전기차","에너지전환"),
 "ICLN":("클린에너지","에너지전환"), "TAN":("태양광","에너지전환"), "FAN":("풍력","에너지전환"),
 "PBW":("클린에너지혁신","에너지전환"), "URA":("우라늄·원전","에너지전환"), "NLR":("원자력","에너지전환"),
 # 항공우주·방산
 "ITA":("방산","방산·우주"), "XAR":("항공우주방산","방산·우주"),
 "UFO":("우주","방산·우주"), "JETS":("항공","방산·우주"),
 # 소비
 "XRT":("소매","소비"), "XHB":("주택건설","소비"), "ITB":("주택","소비"),
 "PEJ":("레저·여행","소비"), "ESPO":("게임·e스포츠","소비"),
 # 금속·소재
 "GDX":("금광","금속·소재"), "GDXJ":("주니어금광","금속·소재"), "SIL":("은광","금속·소재"),
 "COPX":("구리","금속·소재"), "REMX":("희토류","금속·소재"), "XME":("금속·광산","금속·소재"),
 # 농업·운송·인프라
 "MOO":("농업","실물"), "DBA":("농산물","실물"),
 "IYT":("운송","실물"), "XTN":("운송(동일가중)","실물"),
 "PAVE":("인프라","실물"), "IFRA":("인프라(대안)","실물"), "PHO":("물","실물"),
 # 에너지
 "XOP":("석유가스탐사","에너지"), "OIH":("유전서비스","에너지"),
 "AMLP":("파이프라인","에너지"), "XLE":("에너지대형","에너지"),
 # 국가·지역
 "KWEB":("중국인터넷","국가"), "MCHI":("중국","국가"), "EWJ":("일본","국가"),
 "EWT":("대만","국가"), "INDA":("인도","국가"), "EWZ":("브라질","국가"), "EWY":("한국","국가"),
 # 스타일
 "MOAT":("경제적해자","스타일"), "COWZ":("잉여현금흐름","스타일"),
 "SCHD":("배당성장","스타일"), "VNQ":("리츠","스타일"), "QQQ":("나스닥100","벤치마크"),
}

# ⑦ S&P 11섹터
SECTOR = {"XLK":"기술","XLC":"커뮤니케이션","XLY":"경기소비재","XLP":"필수소비재","XLE":"에너지",
          "XLF":"금융","XLV":"헬스케어","XLI":"산업재","XLB":"소재","XLU":"유틸리티","XLRE":"리츠"}

# ⑧ FRED 경제 체온계
FRED_D = {"DGS10":"미국채10년","DGS2":"미국채2년","T10Y2Y":"장단기금리차",
          "T10YIE":"기대인플레10년","BAMLH0A0HYM2":"하이일드스프레드","BAMLC0A0CM":"투자등급스프레드"}
FRED_M = {"UNRATE":"실업률","FEDFUNDS":"기준금리","ICSA":"신규실업수당","PAYEMS":"비농업고용",
          "CPIAUCSL":"소비자물가","CPILFESL":"근원물가"}

# ⑨ 뉴스 RSS
RSS = {
  "CNBC":"https://www.cnbc.com/id/100003114/device/rss/rss.html",
  "MarketWatch":"https://feeds.content.dowjones.io/public/rss/mw_topstories",
  "YahooFinance":"https://finance.yahoo.com/news/rssindex",
  "SeekingAlpha":"https://seekingalpha.com/market_currents.xml",
  "Fed":"https://www.federalreserve.gov/feeds/press_all.xml",
}


# ════════════════════════════════════════════════════════
# 1. 야후에서 시세 한 번에 받기
# ════════════════════════════════════════════════════════
def bulk(tickers, period="1y"):
    """여러 종목 시세를 한 번에 내려받습니다. (하나씩 받으면 너무 느림)"""
    d = yf.download(list(tickers), period=period, interval="1d",
                    auto_adjust=False, progress=False, threads=True)
    return d

def pick(df, field, ticker):
    """다운로드 결과에서 한 종목의 한 칼럼만 꺼냅니다."""
    try:
        s = df[field][ticker] if isinstance(df.columns, pd.MultiIndex) else df[field]
        return s.dropna()
    except Exception:
        return pd.Series(dtype=float)

def row_at(c, d):
    """종가 시리즈에서 기준일(d)의 위치를 찾습니다. 없으면 None."""
    i = [str(x.date()) for x in c.index]
    return i.index(d) if d in i else None


def quotes(tickers_map, df, D):
    """지수·ETF 공통 처리: 종가, 등락률, 1년 자리표까지 계산."""
    out = {}
    for t, meta in tickers_map.items():
        c = pick(df, "Close", t)
        k = row_at(c, D)
        if k is None or k < 1:
            out[t] = None           # ← 못 구한 건 None. 지어내지 않습니다.
            continue
        last, prev = float(c.iloc[k]), float(c.iloc[k-1])
        win = c.iloc[max(0, k-251):k+1]
        lo, hi = float(win.min()), float(win.max())
        out[t] = {
            "name": meta if isinstance(meta, str) else meta[0],
            "group": None if isinstance(meta, str) else meta[1],
            "last": round(last, 2),
            "chg_pct": round((last/prev - 1)*100, 2),
            "y1_low": round(lo, 2), "y1_high": round(hi, 2),
            "y1_pos": round((last-lo)/(hi-lo)*100, 1) if hi > lo else None,
        }
    return out


# ════════════════════════════════════════════════════════
# 2. 레이더 스캔 (강세 / 경보 / 돈의 무게 / 시장의 폭)
# ════════════════════════════════════════════════════════
def quotes_latest(tickers_map, df):
    """아시아 지수는 미국보다 먼저 닫히므로, 기준일을 고정하지 않고
       각 지수의 '가장 최근 거래일'을 씁니다. (니케이 휴장일 대응)"""
    out = {}
    for t, meta in tickers_map.items():
        c = pick(df, "Close", t)
        if len(c) < 2:
            out[t] = None
            continue
        last, prev = float(c.iloc[-1]), float(c.iloc[-2])
        out[t] = {
            "name": meta if isinstance(meta, str) else meta[0],
            "last": round(last, 2),
            "chg_pct": round((last/prev - 1)*100, 2),
            "asof": str(c.index[-1].date()),      # ← 언제 기준인지 반드시 표기
        }
    return out


def scan_radar(df, spx_close, D):
    k_spx = row_at(spx_close, D)
    sp20 = (float(spx_close.iloc[k_spx]) / float(spx_close.iloc[k_spx-20]) - 1) * 100

    rows = []
    for t in RADAR:
        c, v = pick(df, "Close", t), pick(df, "Volume", t)
        k = row_at(c, D)
        if k is None or k < 21 or len(v) <= k:
            continue
        last = float(c.iloc[k])
        v20 = float(v.iloc[k-20:k].mean())
        if not v20:
            continue
        hi52 = float(c.iloc[max(0, k-251):k+1].max())
        rows.append({
            "ticker": t,
            "last": round(last, 2),
            "chg_pct": round((last/float(c.iloc[k-1]) - 1)*100, 2),
            "vol_ratio": round(float(v.iloc[k]) / v20, 2),          # 거래량비
            "from_high": round((last/hi52 - 1)*100, 1),             # 52주 고점 대비
            "amount_musd": round(last * float(v.iloc[k]) / 1e6),    # 거래대금(백만$)
            "rs20": round((last/float(c.iloc[k-20]) - 1)*100 - sp20, 1),  # 20일 상대강도
            "kr_link": KR_LINK.get(t),
        })

    df_r = pd.DataFrame(rows)

    # 강세 레이더: 거래량 터지며 오른 곳
    strong = df_r[(df_r.vol_ratio >= VOL_SURGE) & (df_r.chg_pct >= STRONG_RISE)].copy()
    strong["score"] = ((strong.vol_ratio-1)*10 + strong.chg_pct
                       + (strong.from_high >= NEAR_HIGH) * NEAR_BONUS).round(1)
    # 경보 레이더: 거래량 터지며 빠진 곳
    alert = df_r[(df_r.vol_ratio >= VOL_SURGE) & (df_r.chg_pct <= ALERT_DROP)].copy()
    alert["score"] = ((alert.vol_ratio-1)*10 + alert.chg_pct.abs()).round(1)

    def clean(recs):
        """pandas가 None을 NaN으로 바꿔버리므로 되돌립니다."""
        out = []
        for r in recs:
            r = dict(r)
            if not isinstance(r.get("kr_link"), str):
                r["kr_link"] = None
            out.append(r)
        return out

    return {
        "all": rows,
        "strong": clean(strong.sort_values("score", ascending=False).head(10).to_dict("records")),
        "strong_total": int(len(strong)),
        "alert": clean(alert.sort_values("score", ascending=False).head(10).to_dict("records")),
        "alert_total": int(len(alert)),
        "money": clean(df_r.sort_values("amount_musd", ascending=False).head(10).to_dict("records")),
        "kr_direct": sorted([r for r in rows if r["kr_link"]],
                            key=lambda x: -x["chg_pct"]),
        # 시장의 폭 = 지수가 숨기는 진실
        "breadth": {
            "universe": int(len(df_r)),
            "up": int((df_r.chg_pct > 0).sum()),
            "down": int((df_r.chg_pct < 0).sum()),
            "near_high": int((df_r.from_high >= -2).sum()),
            "up_ratio": round(float((df_r.chg_pct > 0).mean()*100), 1),
        },
    }


# ════════════════════════════════════════════════════════
# 3. EWY 스프레드 = 개장 갭 예보 (이 리포트만의 지표)
# ════════════════════════════════════════════════════════
def ewy_spread(D):
    """한국이 문을 닫은 뒤 미국에서 한국 주식이 얼마나 더 움직였나."""
    h = yf.Ticker("EWY").history(period="1mo")[["Open","High","Low","Close"]].dropna()
    i = [str(x.date()) for x in h.index]
    if D not in i:
        raise ValueError(f"EWY에 {D} 데이터 없음")
    k = i.index(D)
    o, hi, lo, c = [float(h.iloc[k][x]) for x in ("Open","High","Low","Close")]
    prev = float(h.iloc[k-1]["Close"])
    intra = (c/o - 1)*100        # ← 이 값이 다음 개장 갭의 기준선
    return {
        "prev_close": round(prev,2), "open": round(o,2),
        "high": round(hi,2), "low": round(lo,2), "close": round(c,2),
        "gap_from_prev": round((o/prev-1)*100, 2),   # 한국 마감 반영분
        "intraday_pct": round(intra, 2),            # 한국 마감 이후 추가분 ★
        "day_pct": round((c/prev-1)*100, 2),
        "band_low": round(intra*0.7, 2),            # 관측 구간(환율 오차 감안)
        "band_high": round(intra, 2),
        "held_high": round((c/hi-1)*100, 2),        # 고가를 지켰나
    }


# ════════════════════════════════════════════════════════
# 4. FRED 경제 체온계
# ════════════════════════════════════════════════════════
def fred_series(code):
    txt = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}")
    rows = list(csv.reader(io.StringIO(txt)))[1:]
    return [(r[0], float(r[1])) for r in rows if r[1] not in (".", "")]

def fred_all():
    out = {}
    for code, name in {**FRED_D, **FRED_M}.items():
        try:
            s = fred_series(code)
            last, prev = s[-1], s[-2]
            win = [v for _, v in s[-252:]]
            lo, hi = min(win), max(win)
            out[code] = {
                "name": name, "date": last[0], "value": last[1],
                "delta": round(last[1]-prev[1], 3),
                "y1_low": lo, "y1_high": hi,
                "y1_pos": round((last[1]-lo)/(hi-lo)*100, 1) if hi > lo else None,
                "freq": "daily" if code in FRED_D else "monthly",
            }
            # 물가는 전년 대비(YoY)로 바꿔야 의미가 있습니다
            if code in ("CPIAUCSL", "CPILFESL"):
                d = dict(s)
                y, m = int(last[0][:4]), int(last[0][5:7])
                base = d.get(f"{y-1}-{m:02d}-01")
                py, pm = int(prev[0][:4]), int(prev[0][5:7])
                pbase = d.get(f"{py-1}-{pm:02d}-01")
                if base and pbase:
                    now = (last[1]/base - 1)*100
                    bef = (prev[1]/pbase - 1)*100
                    out[code].update({"value": round(now,2), "delta": round(now-bef,2), "unit":"% YoY"})
            # 고용은 '증감'이 의미 있습니다
            if code == "PAYEMS":
                out[code].update({"value": round(last[1]-prev[1], 1), "unit": "천명 증감"})
            if code == "ICSA":
                out[code].update({"value": round(last[1]/10000, 1),
                                  "delta": round((last[1]-prev[1])/10000, 1), "unit": "만 건"})
        except Exception as e:
            out[code] = {"name": name, "error": str(e)[:120]}
    return out


# ════════════════════════════════════════════════════════
# 5. 캘린더 — 오늘 밤 뉴욕 일정
# ════════════════════════════════════════════════════════
def econ_calendar():
    """ForexFactory 주간 경제지표 캘린더 (미국분만)"""
    d = json.loads(get("https://nfs.faireconomy.media/ff_calendar_thisweek.json"))
    return [{"date": x.get("date"), "title": x.get("title"), "impact": x.get("impact"),
             "forecast": x.get("forecast"), "previous": x.get("previous")}
            for x in d if x.get("country") == "USD"]

def earnings_calendar(date_str):
    """나스닥 실적 캘린더. 시총 큰 순으로 정렬."""
    d = json.loads(get(f"https://api.nasdaq.com/api/calendar/earnings?date={date_str}"))
    rows = (d.get("data") or {}).get("rows") or []
    def cap(x):
        try: return float(str(x.get("marketCap","0")).replace("$","").replace(",",""))
        except Exception: return 0.0
    rows.sort(key=cap, reverse=True)
    return [{"symbol": r.get("symbol"), "name": r.get("name"),
             "time": r.get("time"), "eps_forecast": r.get("epsForecast"),
             "market_cap": r.get("marketCap")} for r in rows[:20]]


# ════════════════════════════════════════════════════════
# 6. 뉴스 RSS
# ════════════════════════════════════════════════════════
def rss(url, limit=12):
    import re, html as H
    x = get(url, timeout=20)
    items = re.findall(r"<item>(.*?)</item>|<entry>(.*?)</entry>", x, re.S)
    out = []
    for a, b in items[:limit]:
        s = a or b
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", s, re.S)
        l = re.search(r"<link.*?href=[\"'](.*?)[\"']|<link>(.*?)</link>", s, re.S)
        p = re.search(r"<pubDate>(.*?)</pubDate>|<updated>(.*?)</updated>", s, re.S)
        out.append({
            "title": H.unescape(t.group(1).strip()) if t else None,
            "link": (l.group(1) or l.group(2)).strip() if l else None,
            "published": (p.group(1) or p.group(2)).strip() if p else None,
        })
    return [o for o in out if o["title"]]


# ════════════════════════════════════════════════════════
# 7. 갭 예보 적중률 — 오늘부터 쌓아야 한 달 뒤에 나옵니다
# ════════════════════════════════════════════════════════
HIST = "gap_history.json"

def append_history(session_date, kst_date, spread):
    """오늘의 예보를 기록만 해둡니다. 실제 갭은 다음날 채워 넣습니다."""
    hist = []
    if os.path.exists(HIST):
        try: hist = json.load(open(HIST, encoding="utf-8"))
        except Exception: hist = []
    if any(h.get("kst_date") == kst_date for h in hist):
        return hist                              # 같은 날 두 번 쌓이지 않게
    hist.append({
        "kst_date": kst_date,                    # 예보한 한국 날짜
        "us_session": session_date,
        "forecast_pct": spread["intraday_pct"] if spread else None,
        "band": [spread["band_low"], spread["band_high"]] if spread else None,
        "actual_gap_pct": None,                  # ← 다음날 채움
        "hit": None,                             # ← 다음날 채움 (True/False)
    })
    json.dump(hist, open(HIST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return hist

def fill_yesterday(hist):
    """어제 예보의 실제 결과를 코스피 시가/전일종가로 채워 넣습니다."""
    try:
        k = yf.Ticker("^KS11").history(period="1mo")[["Open","Close"]].dropna()
        idx = [str(x.date()) for x in k.index]
        for h in hist:
            if h["actual_gap_pct"] is not None or h["forecast_pct"] is None:
                continue
            if h["kst_date"] in idx:
                p = idx.index(h["kst_date"])
                if p < 1: continue
                gap = (float(k.iloc[p]["Open"]) / float(k.iloc[p-1]["Close"]) - 1) * 100
                h["actual_gap_pct"] = round(gap, 2)
                h["hit"] = bool((gap >= 0) == (h["forecast_pct"] >= 0))
        json.dump(hist, open(HIST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception as e:
        print("  ⚠ 적중률 채우기 실패:", str(e)[:100])
    done = [h for h in hist if h.get("hit") is not None]
    return {"samples": len(done),
            "hit_rate": round(sum(h["hit"] for h in done)/len(done)*100, 1) if done else None,
            "recent": hist[-10:]}


# ════════════════════════════════════════════════════════
# 8. 메인
# ════════════════════════════════════════════════════════
def main():
    now_kst = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=TZ_OFFSET_H)
    kst_date = now_kst.strftime("%Y-%m-%d")
    print(f"\n{'='*58}\n 차트프로 미국 관제탑 · 데이터 수집  [{SCRIPT_VERSION}]")
    print(f" 한국시간 {now_kst:%Y-%m-%d %H:%M}\n{'='*58}")

    # ── 기준일 찾기: 가장 최근에 '완전히 마감된' 미국 세션
    spx = yf.Ticker("^GSPC").history(period="1mo")["Close"].dropna()
    D = str(spx.index[-1].date())
    print(f" 기준 세션(뉴욕 마감): {D}\n")

    all_tk = list(set(list(IDX)+list(ASIA)+list(ADR)+RADAR+list(THEME)+list(SECTOR)))
    print(f"[1/7] 야후 시세 {len(all_tk)}종목")
    big = safe("yfinance_bulk", bulk, all_tk, "1y")
    if big is None:
        raise SystemExit("❌ 시세를 못 받으면 리포트를 만들 수 없습니다. 중단합니다.")

    print("[2/7] 지수·아시아·ADR·섹터·테마 정리")
    idx    = safe("indices",  quotes, IDX,    big, D)
    asia   = safe("asia",     quotes_latest, ASIA, big)   # 아시아는 각자 최신 거래일 기준
    adr    = safe("kr_adr",   quotes, ADR,    big, D)
    sector = safe("sectors",  quotes, SECTOR, big, D)
    theme  = safe("themes",   quotes, THEME,  big, D)

    # 테마는 거래가 너무 적으면 시세를 못 믿습니다 → 걸러냅니다
    if theme:
        keep = {}
        for t, v in theme.items():
            if not v: continue
            vol = pick(big, "Volume", t); k = row_at(pick(big,"Close",t), D)
            amt = float(vol.iloc[max(0,k-10):k+1].mean()) * v["last"] / 1e6 if k else 0
            if amt >= MIN_THEME_AMT:
                v["amount_musd"] = round(amt, 1); keep[t] = v
        print(f"      └ 테마 {len(keep)}/{len(THEME)}개 통과 (거래대금 {MIN_THEME_AMT}백만$ 이상)")
        theme = keep

    print("[3/7] 레이더 스캔")
    radar = safe("radar", scan_radar, big, spx, D)

    print("[4/7] EWY 갭 예보")
    spread = safe("ewy_spread", ewy_spread, D)

    print("[5/7] FRED 경제 체온계")
    fred = safe("fred", fred_all)

    print("[6/7] 캘린더")
    econ = safe("econ_calendar", econ_calendar)
    tmr  = (dt.datetime.strptime(D, "%Y-%m-%d") + dt.timedelta(days=1)).strftime("%Y-%m-%d")
    earn = safe("earnings_calendar", earnings_calendar, tmr)

    print("[7/7] 뉴스 RSS")
    news = {}
    for k, u in RSS.items():
        r = safe(f"rss_{k}", rss, u)
        if r: news[k] = r

    # 적중률 기록 (오늘부터 쌓임)
    hist = append_history(D, kst_date, spread)
    acc  = fill_yesterday(hist)

    data = {
        "_meta": {"script_version": SCRIPT_VERSION, "built_kst": now_kst.isoformat(),
                  "us_session": D, "kst_date": kst_date},
        "_sources": SOURCES,
        "indices": idx, "asia": asia, "kr_adr": adr, "sectors": sector, "themes": theme,
        "radar": radar, "ewy_spread": spread, "fred": fred,
        "calendar": {"economic": econ, "earnings": earn},
        "news": news, "gap_accuracy": acc,
    }

    fn = f"data_{kst_date.replace('-','')}.json"
    json.dump(data, open(fn, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    ok = sum(1 for v in SOURCES.values() if v["ok"])
    print(f"\n{'='*58}")
    print(f" ✅ 저장: {fn}  ({os.path.getsize(fn)/1024:.0f} KB)")
    print(f" 소스 {ok}/{len(SOURCES)} 성공")
    if radar:
        b = radar["breadth"]
        print(f" 시장의 폭: {b['up']}/{b['universe']}개 상승 ({b['up_ratio']}%)")
        print(f" 강세 {radar['strong_total']}건 · 경보 {radar['alert_total']}건")
    if spread:
        print(f" 갭 예보: {spread['intraday_pct']:+.2f}%  (구간 {spread['band_low']:+.2f}~{spread['band_high']:+.2f}%)")
    if acc["hit_rate"] is not None:
        print(f" 갭 적중률: {acc['hit_rate']}% ({acc['samples']}회 누적)")
    else:
        print(f" 갭 적중률: 기록 시작 ({len(hist)}일차)")
    print("="*58 + "\n")
    return data


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise
