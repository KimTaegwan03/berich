import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import yfinance as yf
import pandas as pd
import math
from datetime import datetime, timedelta
import warnings
import os, json, tempfile


# 모듈 임포트
from toss_crawler import scrape_toss_data
from utils import ichimoku, span_b_signal
from kis_api import *

warnings.filterwarnings("ignore")
app = FastAPI()
templates = Jinja2Templates(directory="templates")

STATE_LOCK = asyncio.Lock()

# ==========================================================
# [설정] 봇 파라미터
# ==========================================================
CRAWL_INTERVAL_SEC = 120  # [정찰병] 크롤링 주기 (3분) -> 밴 방지!
TRADE_INTERVAL_SEC = 20   # [스나이퍼] 매매 주기 (15초) -> 급등주 대응!

MAX_SLOTS = 5
BUY_PERCENT = 19

GLOBAL_TARGET_TICKERS = []

# 손익비 및 트레일링 단계 비율
REMAINING_RATIO = {0: 1.0, 1: 0.70, 2: 0.50, 3: 0.30, 4: 0.15, 5: 0.0}
PROFIT_STEPS = [
    # (target_stage, trigger_profit_pct, sell_ratio_on_init_qty)
    (1, 15.0, 0.30),
    (2, 50.0, 0.20),
    (3, 100.0, 0.20),
    (4, 150.0, 0.15),
    (5, 200.0, 0.15),
]

# stage별 트레일링 드로다운(최고수익률 대비 몇 % 하락하면 전량 정리)
TRAILING_DD = {
    1: 12.0,  # stage1: 최고수익률에서 12%p 빠지면
    2: 15.0,
    3: 18.0,
    4: 22.0,
    5: 28.0,
}

SMALL_INIT_QTY_THRESHOLD = 25   # 초기수량(추정)이 이 이하면 "소량"으로 간주
MIN_REMAIN_SHARES = 1           # stage 1~4에서는 최소 1주 남기기(전량 방지)

LOSS_RATIO = 10  # %

SIGNAL_N = 5 # Flat 유지 기간
SIGNAL_K = 2 # 오차 범위 (%)
ORDER_LIFETIME_LIMIT = 2 * 60 * 60 # 2시간


ACC_STOCK = {}       # 매도 감시용 (보유주식)
PENDING_ORDERS = {}  # 슬롯 점유용 (미체결)

BOT_STATE_PATH = os.environ.get("BOT_STATE_PATH", "./bot_state.json")

def calc_sell_qty(estimated_init_qty: float, sell_ratio: float, cur_qty: int, target_stage: int) -> int:
    """
    소량 포지션에서 ceil로 인한 과매도 왜곡을 완화하고,
    마지막 stage(5) 이전에는 최소 1주 남기도록 보호.
    """
    desired = estimated_init_qty * sell_ratio

    # 1) 소량 포지션은 round 기반(왜곡 완화)
    if estimated_init_qty <= SMALL_INIT_QTY_THRESHOLD:
        sell_qty = int(round(desired))
        # 원하는 게 0.x로 나와도 비중 익절 의도가 있으면 1주는 팔게
        if sell_qty <= 0 and desired > 0:
            sell_qty = 1
    else:
        # 2) 일반 포지션은 기존대로 ceil(원금기준 비율 매도 유지)
        sell_qty = math.ceil(desired)

    # 3) 마지막 졸업(stage=5) 전에는 전량 방지(최소 1주 남기기)
    if target_stage < 5 and cur_qty > MIN_REMAIN_SHARES:
        max_sell = cur_qty - MIN_REMAIN_SHARES
        if sell_qty > max_sell:
            sell_qty = max_sell

    # 4) 방어
    if sell_qty > cur_qty:
        sell_qty = cur_qty
    if sell_qty < 0:
        sell_qty = 0

    return sell_qty

def save_bot_state():
    """
    봇 상태(보유/미체결)를 JSON 파일로 저장.
    os.replace를 써서 원자적(atomic)으로 교체 -> 읽는 쪽에서 깨진 파일 볼 확률 줄임.
    """
    state = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "acc_stock": ACC_STOCK,
        "pending_orders": PENDING_ORDERS,
    }

    dirpath = os.path.dirname(BOT_STATE_PATH) or "."
    os.makedirs(dirpath, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix="bot_state_", suffix=".json", dir=dirpath)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, BOT_STATE_PATH)  # atomic replace
    except Exception:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        raise

def fetch_account_snapshot(real:bool=False):
    """
    API에서 실시간 잔고와 미체결 내역을 가져와서
    ACC_STOCK(보유)과 PENDING_ORDERS(미체결)를 최신 상태로 동기화함.
    *중요: 기존 보유 종목의 stage, max_profit 정보는 유지해야 함!
    """
    global ACC_STOCK, PENDING_ORDERS

    real_holdings = get_stock_quantity(real)
    real_unfilled = get_unfilled_quantity(real)

    return real_holdings, real_unfilled
  
async def sync_account_data_safe(real:bool=False):
    """
    이벤트 루프에서 실행: 스레드에서 가져온 스냅샷을 락 걸고 전역 상태에 반영
    stage/max_profit 보존
    """
    global ACC_STOCK, PENDING_ORDERS

    print("🔄 [Sync] 계좌 동기화 진행 중...")

    real_holdings, real_unfilled = await asyncio.to_thread(fetch_account_snapshot, real=real)

    # ---- 미체결 동기화 ----
    NEW_PENDING = {}
    if real_unfilled:
        for order in real_unfilled:
            ticker = order['pdno']
            NEW_PENDING[ticker] = {
                "order_price": float(order['ovrs_ord_unpr']),
                "qty": int(order['nccs_qty']),
                "order_no": order['odno']
            }

    # ---- 보유 동기화(stage/max_profit 보존) ----
    real_ticker_list = []
    NEW_ACC = dict(ACC_STOCK)  # 복사 후 갱신

    if real_holdings:
        for stock in real_holdings:
            ticker = stock['ovrs_pdno']
            qty = int(stock['ord_psbl_qty'])
            avg_price = float(stock['pchs_avg_pric'])
            excg = stock['ovrs_excg_cd']

            real_ticker_list.append(ticker)
            if qty <= 0:
                continue

            if ticker in NEW_ACC:
                # 진행상황 보존하면서 수량/평단만 갱신
                NEW_ACC[ticker]["qty"] = qty
                NEW_ACC[ticker]["avg_pric"] = avg_price
            else:
                print(f"🎉 [체결 확인] {ticker} {qty}주가 잔고로 들어왔습니다!")
                NEW_ACC[ticker] = {
                    "avg_pric": avg_price,
                    "qty": qty,
                    "excg": excg,
                    "stage": 0,
                    "max_profit": -999.0
                }

    # 잔고에서 사라진 종목 제거
    for ticker in list(NEW_ACC.keys()):
        if ticker not in real_ticker_list:
            print(f"👋 [매도 확인] {ticker} 잔고에서 사라짐 (삭제 처리)")
            del NEW_ACC[ticker]

    # ---- 전역 반영은 락 안에서 한 번에 ----
    async with STATE_LOCK:
        PENDING_ORDERS = NEW_PENDING
        ACC_STOCK = NEW_ACC


async def crawler_loop():
    print(f"🐢 [Crawler] 정찰병 시작 (주기: {CRAWL_INTERVAL_SEC}초)")
    global GLOBAL_TARGET_TICKERS
    
    while True:
        try:
            print("🔍 [Crawler] 토스 랭킹 갱신 중...")
            new_data = await asyncio.to_thread(scrape_toss_data)
            
            if new_data:
                async with STATE_LOCK:
                    GLOBAL_TARGET_TICKERS = new_data
                print(f"✅ [Crawler] 타겟 리스트 갱신 완료 ({len(new_data)}개)")
            else:
                print("⚠️ [Crawler] 데이터 없음 (기존 리스트 유지)")
                
        except Exception as e:
            print(f"❌ [Crawler Error] {e}")
        
        # 3분 휴식 (밴 방지 핵심)
        await asyncio.sleep(CRAWL_INTERVAL_SEC)

async def trading_bot_loop(real:bool=False):
    print("🚀 [System] 자동매매 봇이 백그라운드에서 시작되었습니다.")

    # ACC_STOCK 초기화
    global ACC_STOCK, PENDING_ORDERS

    async with STATE_LOCK:
        ACC_STOCK = {}
        PENDING_ORDERS = {}

    # get_kis_token(real)

    holdings = get_stock_quantity(real)
    if holdings:
        async with STATE_LOCK:
            for stock in holdings:
                ticker = stock['ovrs_pdno']
                qty = int(stock['ord_psbl_qty'])
                if qty <= 0:
                    continue

                avg_price = float(stock['pchs_avg_pric'])
                excg_code = stock['ovrs_excg_cd']

                ACC_STOCK[ticker] = {
                    "avg_pric": avg_price,
                    "qty": qty,
                    "excg": excg_code,
                    "stage": 0,
                    "max_profit": -999.0
                }
    
    # 지정가 구매 주문 내역 불러오기
    unfilled_orders = get_unfilled_quantity(real)
    if unfilled_orders:
        async with STATE_LOCK:
            for order in unfilled_orders:
                ticker = order['pdno']
                PENDING_ORDERS[ticker] = {
                    "order_price": float(order['ft_ord_unpr3']),
                    "qty": int(order['nccs_qty']),
                    "order_no": order['odno'],
                }
    
    # 총 슬롯 사용량 계산
    async with STATE_LOCK:
        total_slots = len(ACC_STOCK) + len(PENDING_ORDERS)
        print(f"💼 [로드 완료] 보유: {len(ACC_STOCK)}개 / 미체결: {len(PENDING_ORDERS)}개 (총 {total_slots} 슬롯 사용)")

    while True:
        # 시간대가 오후 6시~오후9시59분, 오후11시~익일오전2시 일때만 동작            
        now = datetime.now().time()
        print(f"[현재시각_디버깅용] {now}")
        print(f"[시작시각_디버깅용] {datetime.strptime('18:00:00', '%H:%M:%S').time()}")
        if not (
            (now >= datetime.strptime("18:00:00", "%H:%M:%S").time() and now <= datetime.strptime("21:59:59", "%H:%M:%S").time()) or
            (now >= datetime.strptime("23:00:00", "%H:%M:%S").time() and now <= datetime.strptime("23:59:59", "%H:%M:%S").time()) or
            (now >= datetime.strptime("00:00:00", "%H:%M:%S").time() and now <= datetime.strptime("02:00:00", "%H:%M:%S").time())
            ):
            print("😴 [Bot] 미국 주식 시장 운영 시간 외에는 대기합니다.")

            # 만약 주식을 가지고 있거나, 미체결 내역이 있으면 팔기 및 취소하기            
            if ACC_STOCK or PENDING_ORDERS:
                print("⚠️ [Bot] 시장 운영 시간 외, 보유 종목 및 미체결 주문 정리 시도...")
                
                # 보유 종목 매도
                for ticker, info in list(ACC_STOCK.items()):
                    print(f"💰 [정리] {ticker} 보유 수량 {info['qty']}주 매도 시도...")
                    # 현재가 조회 (실전 투자만 가능하므로 모의투자 시에는 임의 가격으로 매도 시도)
                    current_price_data = get_current_price(ticker, info['excg'], real)
                    if current_price_data:
                        current_price = float(current_price_data['last'])
                    else:
                        # 모의투자이거나 현재가 조회 실패 시, 매수 평균가로 매도 시도 (손실 감수)
                        current_price = info['avg_pric'] * 0.95 # 보수적으로 5% 낮은 가격으로 매도 시도
                        print(f"⚠️ [정리] {ticker} 현재가 조회 실패, 평균가 {info['avg_pric']:.2f}의 95%인 {current_price:.2f}로 매도 시도")

                    if send_sell_order(ticker, current_price, info['qty'], info['excg'], real):
                        del ACC_STOCK[ticker]
                        print(f"✅ [정리] {ticker} 매도 완료.")
                    else:
                        print(f"❌ [정리] {ticker} 매도 실패.")
                
                # 미체결 주문 취소
                for ticker, order_info in list(PENDING_ORDERS.items()):
                    print(f"🗑️ [정리] {ticker} 미체결 주문 {order_info['order_no']} 취소 시도...")
                    if cancel_order(ticker, order_info['order_no'], order_info['qty'], real):
                        del PENDING_ORDERS[ticker]
                        print(f"✅ [정리] {ticker} 미체결 주문 취소 완료.")
                    else:
                        print(f"❌ [정리] {ticker} 미체결 주문 취소 실패.")

            
            await asyncio.sleep(600) # 10분 대기
            continue

        try:
            #### 매수 루프 ####
            # 1. KIS 토큰 점검
            get_kis_token(real)

            await sync_account_data_safe(real)

            # 오래된 지정가 주문내역 취소
            unfilled_orders = get_unfilled_quantity(real)
            if unfilled_orders:
                for order in unfilled_orders:
                    ticker = order['pdno']
                    ord_date = order['ord_dt']
                    ord_time = order['ord_tmd']
                    qty = int(order['nccs_qty'])

                    ord_datetime = datetime.strptime(f"{ord_date} {ord_time}", "%Y%m%d %H%M%S")
                    now = datetime.now()
                    diff = now - ord_datetime

                    if diff > timedelta(seconds=ORDER_LIFETIME_LIMIT):
                        ord_no = order['odno']

                        success = cancel_order(ticker, ord_no, qty, real)
                        if success:
                            if ticker in PENDING_ORDERS:
                                del PENDING_ORDERS[ticker]
                        
            
            async with STATE_LOCK:
                current_targets = list(GLOBAL_TARGET_TICKERS)
                
            # 3. 각 종목 분석 및 주문
            for item in current_targets:
                ticker = item['ticker']
                toss_exchange = item.get('exchange', 'NSQ')

                if (len(ACC_STOCK) + len(PENDING_ORDERS)) >= MAX_SLOTS:
                    break

                if ticker in ACC_STOCK or ticker in PENDING_ORDERS:
                    continue

                try:
                    df = yf.download(ticker, interval="5m", period="5d", prepost=True, progress=False, multi_level_index=False)
                    if len(df) < 60: continue

                    # 분석
                    chart_data = ichimoku(df, {"delta": timedelta(minutes=5)})
                    if not chart_data: continue

                    # 시그널 확인
                    signal, price = span_b_signal(chart_data, n=SIGNAL_N, k=SIGNAL_K)

                    if signal:
                        order_price = round(price, 2)
                        
                        # ==================================================
                        # [핵심] 자산 대비 수량 계산 로직
                        # ==================================================
                        # 1. 내 계좌 총 자산 조회 (주식평가금 + 현금)
                        total_asset, orderable_cash = get_account_balance(real)

                        total_asset = total_asset / 1500 # 환율 적용
                        orderable_cash = orderable_cash / 1500 # 환율 적용
                        
                        if total_asset <= 0:
                            print(f"⚠️ [Skip] 자산 조회 오류 또는 잔고 0 (Asset: {total_asset})")
                            continue

                        # 2. 목표 매수 금액 계산 (총자산의 5%)
                        target_amount = total_asset * (BUY_PERCENT / 100)
                        
                        # 3. 매수 가능 수량 계산 (목표금액 / 주당가격) -> 소수점 버림
                        qty = math.floor(target_amount / order_price)
                        
                        # 4. 예외 처리
                        if qty < 1:
                            # 1주도 못 사는 경우 (돈이 없거나 주식이 너무 비쌈)
                            # print(f"   [Skip] {ticker} 자산 부족 (필요: ${order_price}, 할당: ${target_amount:.2f})")
                            continue
                            
                        # (선택) 현금 부족 시 주문 가능한 만큼만 사기 (Safety)
                        max_qty_by_cash = math.floor(orderable_cash / order_price)
                        if qty > max_qty_by_cash:
                            qty = max_qty_by_cash # 현금 있는 만큼만 조정
                            if qty < 1: continue

                        print(f"⚡ [SIGNAL] {ticker} ({toss_exchange}) 매수! ${order_price} x {qty}주 (비중 {BUY_PERCENT}%)")
                        
                        # 5. 주문 전송
                        kis_exchange = map_exchange_code(toss_exchange)
                        success, odno = send_buy_order(ticker, order_price, qty, kis_exchange, real)
                        
                        if success:
                            PENDING_ORDERS[ticker] = {
                                "order_price": order_price,
                                "qty": qty,
                                "order_no": odno}
                    
                except Exception as e:
                    continue # 개별 종목 에러 무시
            
            #################

            #### 매도 루프 ####
            # 손익 보고 익절, 손절
            current_tickers = list(ACC_STOCK.keys())
            for ticker in current_tickers:
                info = ACC_STOCK[ticker]

                avg_price = info["avg_pric"]
                qty = info["qty"]
                excg = info["excg"]
                stage = info.get("stage", 0)

                if "max_profit" not in info:
                    info["max_profit"] = -999.0
                
                try:
                    # 현재가 조회
                    df = await asyncio.to_thread(yf.download, ticker, interval="5m", period="1d", prepost=True, progress=False, multi_level_index=False)
                    if len(df) < 1: continue

                    curr_price = float(df['Close'].iloc[-1])
                    profit_pct = ((curr_price - avg_price) / avg_price) * 100

                    # 최고 수익률 갱신 (트레일링 스탑용)
                    if profit_pct > info["max_profit"]:
                        info["max_profit"] = profit_pct

                    max_p = info["max_profit"] # 현재까지의 최고 수익률

                    # -------------------------------------------------------
                    # 1. 🛑 손절 (-10%)
                    # -------------------------------------------------------
                    if profit_pct <= -10.0:
                        print(f"❌ [손절] {ticker} -10% 도달.. 전량 매도")
                        if send_sell_order(ticker, curr_price, qty, excg, real):
                            del ACC_STOCK[ticker]
                        continue

                    if stage == 0 and info["max_profit"] >= 15.0 and profit_pct <= 1.0:
                        print(f"🛡️ [본절 스탑] {ticker} +15% 찍고 하락..")
                        if send_sell_order(ticker, curr_price, qty, excg, real): del ACC_STOCK[ticker]
                        continue

                    if stage >= 1:
                        dd = TRAILING_DD.get(stage, None)
                        if dd is not None and (max_p - profit_pct) >= dd:
                            print(f"📉 [트레일링 스탑] {ticker} stage={stage} max={max_p:.2f}% -> now={profit_pct:.2f}% (DD {dd}%) 전량 매도")
                            if send_sell_order(ticker, curr_price, qty, excg, real):
                                del ACC_STOCK[ticker]
                            continue

                    cur_qty = qty
                    cur_stage = stage

                    for target_stage, trigger_profit, sell_ratio in PROFIT_STEPS:
                        # 아직 그 단계 안 갔고, 수익률이 트리거 이상이면 실행
                        if cur_stage < target_stage and profit_pct >= trigger_profit:

                            # 역산 공식 그대로 사용 (현재 stage에서 남아있어야 하는 비율 기반)
                            current_ratio_factor = REMAINING_RATIO.get(cur_stage, 1.0)
                            estimated_init_qty = cur_qty / current_ratio_factor

                            sell_qty = calc_sell_qty(estimated_init_qty, sell_ratio, cur_qty, target_stage)

                            if sell_qty <= 0:
                                # 방어
                                cur_stage = target_stage
                                ACC_STOCK[ticker]["stage"] = cur_stage
                                continue

                            print(f"💰 [분할익절] {ticker} stage {cur_stage}->{target_stage} "
                                f"profit={profit_pct:.2f}% trigger={trigger_profit}% sell={sell_qty}/{cur_qty}")

                            if send_sell_order(ticker, curr_price, sell_qty, excg, real):
                                # 주문 성공 반영
                                cur_qty -= sell_qty
                                ACC_STOCK[ticker]["qty"] = cur_qty
                                cur_stage = target_stage
                                ACC_STOCK[ticker]["stage"] = cur_stage

                                if cur_qty <= 0:
                                    del ACC_STOCK[ticker]
                                    print(f"👋 {ticker} 졸업 완료.")
                                    break
                            else:
                                # 주문 실패면 더 진행하지 않음
                                print(f"⚠️ [익절 실패] {ticker} 매도 주문 실패, 다음 루프에서 재시도")
                                break


                except Exception as e:
                    print(f"❌ 매도 로직 에러 ({ticker}): {e}")
                    continue

        except Exception as e:
            print(f"❌ [Bot Error] 루프 치명적 오류: {e}")
        
        # 주기 대기
        save_bot_state()
        await asyncio.sleep(TRADE_INTERVAL_SEC)

def map_exchange_code(toss_code):
    # Toss Code -> KIS Code
    mapping = {
        "NSQ": "NASD", # 나스닥
        "NYS": "NYSE", # 뉴욕
        "ASE": "AMEX", # 아멕스 (확인 필요, 보통 AMS)
    }
    return mapping.get(toss_code, "NASD") # 모르면 일단 나스닥


# --- API Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/scrape")
async def get_scraped_data():
    data = scrape_toss_data()
    return data

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    state = {}
    try:
        with open("./bot_state.json", "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        pass

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "state": state}
    )

@app.get("/api/history/{ticker}")
async def get_stock_history(ticker: str):
    # 각 봉 별 시간 간격 정의
    configs = [
        {"label": "1분봉 (최근 2일)", "interval": "1m", "period": "2d", "delta": timedelta(minutes=1)},
        {"label": "2분봉 (최근 3일)", "interval": "2m", "period": "3d", "delta": timedelta(minutes=2)}, 
        {"label": "5분봉 (최근 10일)", "interval": "5m", "period": "10d", "delta": timedelta(minutes=5)},
        {"label": "15분봉 (최근 20일)", "interval": "15m", "period": "20d", "delta": timedelta(minutes=15)}, 
        {"label": "30분봉 (최근 30일)", "interval": "30m", "period": "30d", "delta": timedelta(minutes=30)}
    ]
    
    response_data = []

    for conf in configs:
        try:
            # 1. 데이터 다운로드
            df = yf.download(ticker, interval=conf['interval'], period=conf['period'], progress=False, prepost=True, multi_level_index=False)
            
            chart_data = ichimoku(df, conf)
            
            response_data.append(chart_data)
            
        except Exception as e:
            print(f"❌ Error fetching {conf['interval']} for {ticker}: {e}")

    return response_data

@app.post("/api/scan/signals")
async def scan_signals(request: Request):
    data = await request.json()
    tickers = data.get("tickers", []) 
    
    INTERVAL = "5m" 
    PERIOD = "5d"

    signals = {}

    for ticker in tickers:
        if not ticker or ticker == "N/A": continue
        
        try:
            # 1. 데이터 가져오기
            df = yf.download(ticker, interval=INTERVAL, period=PERIOD, prepost=True, progress=False, multi_level_index=False)
            if len(df) < 60: continue 

            chart_data = ichimoku(df, {"label": f"{INTERVAL} (최근 5일)", "interval": INTERVAL, "period": PERIOD, "delta": timedelta(minutes=5)})

            is_floating, value = span_b_signal(chart_data, 7, 2)

            curr_span_b = value

            if is_floating:
                # 이격도는 '현재가' 기준으로 계산 (가장 최근 봉)
                curr_close = df['Close'].iloc[-1]
                gap_pct = ((curr_close - curr_span_b) / curr_span_b) * 100
                
                signals[ticker] = {
                    "detected": True,
                    "flat_price": float(curr_span_b),
                    "gap_pct": round(gap_pct, 2),
                    "msg": f"5봉 연속 공중부양 (Gap +{round(gap_pct, 2)}%)"
                }

        except Exception as e:
            print(f"Scan Error {ticker}: {e}")
            continue

    return signals

if __name__ == "__main__":
    import uvicorn
    # 실행 명령어: python main.py
    uvicorn.run(app, host="0.0.0.0", port=8000)