import requests
import json, os
from datetime import datetime, timedelta
import dotenv
import pandas as pd

dotenv.load_dotenv()

# ==========================================================
# [설정] 한국투자증권 API 설정 (반드시 입력!)
# ==========================================================
# 모의투자: https://openapivts.koreainvestment.com:29443
# 실전투자: https://openapi.koreainvestment.com:9443
KIS_BASE_URL = "https://openapivts.koreainvestment.com:29443"
KIS_BASE_URL_REAL = "https://openapi.koreainvestment.com:9443"

KIS_APP_KEY = os.environ.get("KIS_APP_KEY_MOCK")
KIS_APP_SECRET = os.environ.get("KIS_APP_SECRET_MOCK")
KIS_CANO = os.environ.get("KIS_CANO_MOCK")
KIS_ACNT_PRDT_CD = os.environ.get("KIS_ACNT_PRDT_CD_MOCK")

KIS_APP_KEY_REAL = os.environ.get("KIS_APP_KEY_REAL")
KIS_APP_SECRET_REAL = os.environ.get("KIS_APP_SECRET_REAL")
KIS_CANO_REAL = os.environ.get("KIS_CANO_REAL")
KIS_ACNT_PRDT_CD_REAL = os.environ.get("KIS_ACNT_PRDT_CD_REAL")

# 전역 변수 (토큰 캐싱용)
ACCESS_TOKEN = None
TOKEN_EXPIRY = None
IS_REAL = False

def get_kis_token(real:bool=False):
    """접근 토큰 발급/갱신 (싱글톤 패턴)"""
    global ACCESS_TOKEN, TOKEN_EXPIRY, IS_REAL
    
    if IS_REAL == real and ACCESS_TOKEN and TOKEN_EXPIRY and datetime.now() < TOKEN_EXPIRY:
        return ACCESS_TOKEN

    if real:
        url = f"{KIS_BASE_URL_REAL}/oauth2/tokenP"
    else:
        url = f"{KIS_BASE_URL}/oauth2/tokenP"

    headers = {"content-type": "application/json"}

    if real:
        body = {
            "grant_type": "client_credentials",
            "appkey": KIS_APP_KEY_REAL,
            "appsecret": KIS_APP_SECRET_REAL
        }
    else:
        body = {
            "grant_type": "client_credentials",
            "appkey": KIS_APP_KEY,
            "appsecret": KIS_APP_SECRET
        }
    
    try:
        res = requests.post(url, headers=headers, data=json.dumps(body))
        data = res.json()
        ACCESS_TOKEN = data['access_token']
        TOKEN_EXPIRY = datetime.now() + timedelta(hours=23) # 23시간 유효
        IS_REAL = real
        print(f"🔑 [KIS] 토큰 발급 완료")
        return ACCESS_TOKEN
    except Exception as e:
        print(f"❌ [KIS] 토큰 발급 실패: {e}")
        return None
    
def get_account_balance(real:bool=False):
    """
    계좌의 총 자산(USD)과 주문가능 현금(USD)을 조회
    return: (총자산, 주문가능현금)
    """
    token = get_kis_token(real)
    if not token: return 0.0, 0.0

    # 체결기준현재잔고조회 모의 TR ID: VTRP6504R / 실전: CTRP6504R
    if not real:
        tr_id = "VTRP6504R"
        url = f"{KIS_BASE_URL}/uapi/overseas-stock/v1/trading/inquire-present-balance"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {token}",
            "appKey": KIS_APP_KEY,
            "appSecret": KIS_APP_SECRET,
            "tr_id": tr_id
        }
        
        params = {
            "CANO": KIS_CANO,
            "ACNT_PRDT_CD": KIS_ACNT_PRDT_CD,
            "WCRC_FRCR_DVSN_CD": "02", # 외화
            "NATN_CD": "840", # 미국
            "TR_MKET_CD": "00", 
            "INQR_DVSN_CD": "00"
        }
    else:
        tr_id = "CTRP6504R"
        url = f"{KIS_BASE_URL_REAL}/uapi/overseas-stock/v1/trading/inquire-present-balance"

        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {token}",
            "appKey": KIS_APP_KEY_REAL,
            "appSecret": KIS_APP_SECRET_REAL,
            "tr_id": tr_id
        }

        params = {
            "CANO": KIS_CANO_REAL,
            "ACNT_PRDT_CD": KIS_ACNT_PRDT_CD_REAL,
            "WCRC_FRCR_DVSN_CD": "02", # 외화
            "NATN_CD": "840", # 미국
            "TR_MKET_CD": "00", 
            "INQR_DVSN_CD": "00"
        }

    try:
        res = requests.get(url, headers=headers, params=params)
        data = res.json()
        
        if data['rt_cd'] != '0':
            print(f"❌ [잔고조회 실패] {data['msg1']}")
            return 0.0, 0.0
            
        # output2: 계좌 상세 자산 내역
        output3 = data['output3']
        
        if real:
            stock_val = float(output3.get('pchs_amt_smtl_amt', 0))
            cash_val = float(output3.get('frcr_use_psbl_amt', 0))
        else:
            stock_val = float(output3.get('pchs_amt_smtl', 0))
            cash_val = float(output3.get('frcr_evlu_tota', 0))
        
        total_asset = stock_val + cash_val # 총 자산

        print(f"💰 [잔고조회 완료] {total_asset:.2f}원 | 주문가능 현금: {cash_val:.2f}원")
        
        return total_asset, cash_val

    except Exception as e:
        print(f"❌ [잔고조회 에러] {e}")
        return 0.0, 0.0

def send_buy_order(ticker, price, qty, exchange="NASD", real:bool=False):
    """지정가 매수 주문"""
    token = get_kis_token(real)
    if not token: return False, 0
    
    # [중요] 모의투자 매수 TR ID: VTTT1002U / 실전: TTTT1002U
    if real:
        tr_id = "TTTT1002U"
        url = f"{KIS_BASE_URL_REAL}/uapi/overseas-stock/v1/trading/order"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {token}",
            "appKey": KIS_APP_KEY_REAL,
            "appSecret": KIS_APP_SECRET_REAL,
            "tr_id": tr_id,
        }
        body = {
            "CANO": KIS_CANO_REAL,
            "ACNT_PRDT_CD": KIS_ACNT_PRDT_CD_REAL,
            "OVRS_EXCG_CD": exchange,
            "PDNO": ticker,
            "ORD_QTY": str(int(qty)),
            "OVRS_ORD_UNPR": str(price),
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00"        # 00: 지정가
        }
    else:
        tr_id = "VTTT1002U"
        url = f"{KIS_BASE_URL}/uapi/overseas-stock/v1/trading/order"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {token}",
            "appKey": KIS_APP_KEY,
            "appSecret": KIS_APP_SECRET,
            "tr_id": tr_id, 
        }
        
        body = {
            "CANO": KIS_CANO,
            "ACNT_PRDT_CD": KIS_ACNT_PRDT_CD,
            "OVRS_EXCG_CD": exchange,  # 기본 나스닥 설정 (필요 시 로직 추가)
            "PDNO": ticker,
            "ORD_QTY": str(int(qty)),
            "OVRS_ORD_UNPR": str(price),
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00"        # 00: 지정가
        }

    try:
        res = requests.post(url, headers=headers, data=json.dumps(body))
        data = res.json()
        if data['rt_cd'] == '0':
            print(f"✅ [주문성공] {ticker} ${price} / {qty}주 (주문번호: {data['output']['ODNO']})")
            return True, data['output']['ODNO']
        else:
            print(f"❌ [주문실패] {ticker}: {data['msg1']} (Code: {data['msg_cd']})")
            return False, 0
    except Exception as e:
        print(f"❌ [API오류] {e}")
        return False, 0
    
def send_sell_order(ticker, price, qty, exchange="NASD", real:bool=False):
    """
    해외주식 지정가 매도 주문
    """
    token = get_kis_token(real)
    if not token: return False

    # [중요] 모의투자 매도 TR ID: VTTT1001U (실전: TTTT1006U)
    if real:
        tr_id = "TTTT1006U"
        url = f"{KIS_BASE_URL_REAL}/uapi/overseas-stock/v1/trading/order"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {token}",
            "appKey": KIS_APP_KEY_REAL,
            "appSecret": KIS_APP_SECRET_REAL,
            "tr_id": tr_id
        }
        body = {
            "CANO": KIS_CANO_REAL,
            "ACNT_PRDT_CD": KIS_ACNT_PRDT_CD_REAL,
            "OVRS_EXCG_CD": exchange,
            "PDNO": ticker,
            "ORD_QTY": str(int(qty)),
            "OVRS_ORD_UNPR": str(round(price*0.98,2)), # 현재가보다 2% 낮게 주문
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00"           # 00: 지정가
        }
    
    else:
        tr_id = "VTTT1001U"
        url = f"{KIS_BASE_URL}/uapi/overseas-stock/v1/trading/order"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {token}",
            "appKey": KIS_APP_KEY,
            "appSecret": KIS_APP_SECRET,
            "tr_id": tr_id  # <--- 매도용 ID 확인
        }
        body = {
            "CANO": KIS_CANO,
            "ACNT_PRDT_CD": KIS_ACNT_PRDT_CD,
            "OVRS_EXCG_CD": exchange,
            "PDNO": ticker,
            "ORD_QTY": str(int(qty)),  # 수량은 반드시 정수 문자열
            "OVRS_ORD_UNPR": str(round(price*0.98,2)),
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00"           # 00: 지정가
        }

    try:
        res = requests.post(url, headers=headers, data=json.dumps(body))
        data = res.json()
        
        if data['rt_cd'] == '0':
            print(f"📉 [매도주문 성공] {ticker} ${price} / {qty}주 (주문번호: {data['output']['ODNO']})")
            return True
        else:
            print(f"❌ [매도주문 실패] {ticker}: {data['msg1']} (Code: {data['msg_cd']})")
            return False
    except Exception as e:
        print(f"❌ [API오류] {e}")
        return False

def get_stock_quantity(real:bool=False):
    """
    계좌 전체 보유 수량 조회 (매도 전 확인용)
    return: 보유수량 (int)
    """
    token = get_kis_token(real)
    if not token: return 0

    # 잔고 조회 TR 사용 (모의: VTTS3012R)
    if real:
        tr_id = "TTTS3012R"
        url = f"{KIS_BASE_URL_REAL}/uapi/overseas-stock/v1/trading/inquire-balance"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {token}",
            "appKey": KIS_APP_KEY_REAL,
            "appSecret": KIS_APP_SECRET_REAL,
            "tr_id": tr_id
        }
        params = {
            "CANO": KIS_CANO_REAL,
            "ACNT_PRDT_CD": KIS_ACNT_PRDT_CD_REAL,
            "OVRS_EXCG_CD": "NASD", 
            "TR_CRCY_CD": "USD",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": ""
        }

    else:
        tr_id = "VTTS3012R"
        url = f"{KIS_BASE_URL}/uapi/overseas-stock/v1/trading/inquire-balance"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {token}",
            "appKey": KIS_APP_KEY,
            "appSecret": KIS_APP_SECRET,
            "tr_id": tr_id
        }
        params = {
            "CANO": KIS_CANO,
            "ACNT_PRDT_CD": KIS_ACNT_PRDT_CD,
            "OVRS_EXCG_CD": "NASD", 
            "TR_CRCY_CD": "USD",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": ""
        }

    try:
        res = requests.get(url, headers=headers, params=params)
        data = res.json()
        
        if data['rt_cd'] == '0':
            # output1: 보유 종목 리스트
            holdings = data['output1']
            return holdings
        else:
            return 0
    except Exception as e:
        print(f"❌ [수량조회 오류] {e}")
        return 0

## 매수 주문 미체결 수량 조회
def get_unfilled_quantity(real: bool = False):
    token = get_kis_token(real)
    if not token: return 0

    ## 모의투자
    if not real:
        # 해외주식 주문체결내역 tr id : VTTS3035R
        tr_id = "VTTS3035R"

        url = f"{KIS_BASE_URL}/uapi/overseas-stock/v1/trading/inquire-ccnl"

        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {token}",
            "appKey": KIS_APP_KEY,
            "appSecret": KIS_APP_SECRET,
            "tr_id": tr_id
        }

        today = datetime.now().strftime("%Y%m%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

        params = {
            "CANO": KIS_CANO,
            "ACNT_PRDT_CD": KIS_ACNT_PRDT_CD,
            "PDNO": "%",
            "ORD_STRT_DT": yesterday,
            "ORD_END_DT": today,
            "SLL_BUY_DVSN" : "00", # 00: 전체, 01: 매도, 02: 매수 ()
            "CCLD_NCCS_DVSN": "00",
            "OVRS_EXCG_CD": "%",
            "SORT_SQN": "DS",
            "ORD_DT": "",
            "ODNO": "",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": ""
        }

        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()

            if data['rt_cd'] == '0':
                output = data['output']

                outputs = []
                for ord in output:
                    if int(ord['nccs_qty']) > 0 and ord['sll_buy_dvsn_cd'] == "02":
                        outputs.append(ord)

                return outputs
            else:
                return 0
        except Exception as e:
            print(f"❌ [체결내역조회 오류] {e}")
            return 0

    ## 실전투자
    else:
        # 해외주식 미체결내역 tr id : TTTS3018R
        tr_id = "TTTS3018R"
        url = f"{KIS_BASE_URL_REAL}/uapi/overseas-stock/v1/trading/inquire-nccs"

        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {token}",
            "appKey": KIS_APP_KEY_REAL,
            "appSecret": KIS_APP_SECRET_REAL,
            "tr_id": tr_id
        }

        params = {
            "CANO": KIS_CANO_REAL,
            "ACNT_PRDT_CD": KIS_ACNT_PRDT_CD_REAL,
            "OVRS_EXCG_CD": "NASD",
            "SORT_SQN": "DS",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": ""
            }
        
        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()

            if data['rt_cd'] == '0':
                output = data['output']
                outputs = []
                for ord in output:
                    if int(ord['nccs_qty']) > 0 and ord['sll_buy_dvsn_cd'] == "02":
                        outputs.append(ord)

                return outputs
            else:
                return 0
        except Exception as e:
            print(f"❌ [미체결내역조회 오류] {e}")
            return 0

# 주문 취소
def cancel_order(ticker, order_no, qty, real:bool=False):
    token = get_kis_token(real)
    if not token: return False

    ## 모의투자
    if not real:
        # tr_id: VTTT1004U
        tr_id = "VTTT1004U"
        url = f"{KIS_BASE_URL}/uapi/overseas-stock/v1/trading/order-rvsecncl"

        headers = {
                "Content-Type": "application/json",
                "authorization": f"Bearer {token}",
                "appKey": KIS_APP_KEY,
                "appSecret": KIS_APP_SECRET,
                "tr_id": tr_id
            }

        params = {
            "CANO": KIS_CANO,
            "ACNT_PRDT_CD": KIS_ACNT_PRDT_CD,
            "OVRS_EXCG_CD": "NASD",
            "PDNO": ticker,
            "ORGN_ODNO": order_no,
            "RVSE_CNCL_DVSN_CD": "02", # 취소 02
            "ORD_QTY": str(qty),
            "OVRS_ORD_UNPR": "0"
        }
    else:
        tr_id = "TTTT1004U"
        url = f"{KIS_BASE_URL_REAL}/uapi/overseas-stock/v1/trading/order-rvsecncl"

        headers = { 
            "Content-Type": "application/json",
            "authorization": f"Bearer {token}",
            "appKey": KIS_APP_KEY_REAL,
            "appSecret": KIS_APP_SECRET_REAL,
            "tr_id": tr_id
        }

        params = {
            "CANO": KIS_CANO_REAL,
            "ACNT_PRDT_CD": KIS_ACNT_PRDT_CD_REAL,
            "OVRS_EXCG_CD": "NASD",
            "PDNO": ticker,
            "ORGN_ODNO": order_no,
            "RVSE_CNCL_DVSN_CD": "02", # 취소 02
            "ORD_QTY": str(qty),
            "OVRS_ORD_UNPR": "0"
        }

    try:
        res = requests.post(url, headers=headers, params=params)
        data = res.json()
        if data['rt_cd'] == '0':
            print(f"✅ [주문취소 성공] {ticker} (주문번호: {data['output']['ODNO']})")
            return True
        else:
            print(f"❌ [주문취소 실패] {ticker} ({data['msg1']})")
            return False
    except Exception as e:
        print(f"❌ [API오류] {e}")
        return False

# 현재가 데이터 조회
def get_current_price(ticker,exchange, real:bool=False):
    if not real:
        # 모의투자는 지원하지 않음
        print("❌ [KIS] 모의투자에서는 현재가 데이터를 직접 조회할 수 없습니다.")
        return False

    token = get_kis_token(real)
    if not token: return False

    excd_mapping = {
        "NASD": "NAS",
        "NYSE": "NYS",
        "AMEX": "AMS"
    }

    excg = excd_mapping.get(exchange, exchange)


    tr_id = 'HHDFS76200200'
    url = f"{KIS_BASE_URL_REAL}/uapi/overseas-price/v1/quotations/price-detail"
    headers = { 
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appKey": KIS_APP_KEY_REAL,
        "appSecret": KIS_APP_SECRET_REAL,
        "tr_id": tr_id
    }
    params = {
        "AUTH":"",
        "EXCD":excg,
        "SYMB":ticker,
    }

    try:
        res = requests.get(url, headers=headers, params=params)
        data = res.json()
        if data['rt_cd'] == '0':
            
            return data['output']
        else:
            print(f"❌ [현재가조회실패] {ticker}: {data['msg1']} (Code: {data['msg_cd']})")
            return False
        
    except Exception as e:
        print(f"❌ [API오류] {e}")
        return False

def get_5m_candles(ticker, exchange, real:bool=False):
    if not real:
        # 모의투자는 지원하지 않음
        print("❌ [KIS] 모의투자에서는 현재가 데이터를 직접 조회할 수 없습니다.")
        return False

    token = get_kis_token(real)
    if not token: return False

    tr_id = "HHDFS76950200"
    url = f"{KIS_BASE_URL_REAL}/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
    headers = { 
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appKey": KIS_APP_KEY_REAL,
        "appSecret": KIS_APP_SECRET_REAL,
        "tr_id": tr_id
    }

    excd_mapping = {
        "NASD": "NAS",
        "NYSE": "NYS",
        "AMEX": "AMS"
    }

    excg = excd_mapping.get(exchange, exchange)

    params = {
        "AUTH":"",
        "EXCD":excg,
        "SYMB":ticker,
        "NMIN":"5",
        "PINC":"1",
        "NEXT":"",
        "NREC":"120",
        "FILL":"",
        "KEYB":""
        }
    
    try:
        res = requests.get(url, headers=headers, params=params)
        data = res.json()
        if data['rt_cd'] == '0':
            df = pd.DataFrame(data['output2'])
            df.rename({'open':'Open','high':'High','low':'Low','last':'Close','evol':'Volume'}, inplace=True, axis=1)
            df["Datetime"] = pd.to_datetime(
                    df["kymd"].astype(str) + df["khms"].astype(str).str.zfill(6),
                    format="%Y%m%d%H%M%S"
                )
            df.set_index("Datetime", inplace=True)

            # 순서 뒤집기
            df = df.iloc[::-1]

            return df
        else:
            print(f"❌ [현재가조회실패]")
            return False
    except Exception as e:
        print(f"❌ [API오류] {ticker} {exchange} {e}")
        return False
    
        
        
    

if __name__ == "__main__":
    import json
    import yfinance as yf
    # json_str = "{'pchs_amt_smtl': '195380412', 'evlu_amt_smtl': '123605717', 'evlu_pfls_amt_smtl': '-71774695', 'dncl_amt': '0', 'cma_evlu_amt': '0', 'tot_dncl_amt': '0', 'etc_mgna': '0', 'wdrw_psbl_tot_amt': '0', 'frcr_evlu_tota': '168397959', 'evlu_erng_rt1': '0.0000000000', 'pchs_amt_smtl_amt': '195380412', 'evlu_amt_smtl_amt': '123605717', 'tot_evlu_pfls_amt': '-71774695.26603001', 'tot_asst_amt': '292003677', 'buy_mgn_amt': '0', 'mgna_tota': '0', 'frcr_use_psbl_amt': '0.00', 'ustl_sll_amt_smtl': '0', 'ustl_buy_amt_smtl': '0', 'tot_frcr_cblc_smtl': '0.000000', 'tot_loan_amt': '0'}"

    # print(json.loads(json_str))
    get_kis_token(True)

    
    # _5m_price = get_5m_candles('TSLA','NASD', True)
    # print(_5m_price[:20])

    # yf_5m = yf.download("BIYA",progress=False,prepost=True,multi_level_index=False)
    # print(yf_5m.head(5))

    total, orderable = get_account_balance(True)
    # hold = get_stock_quantity(True)
    # unfilled = get_unfilled_quantity(True)

    # print(hold)
    # print(unfilled)

    print(total)
    print(orderable)
    # print(json.dumps(hold, indent=2))

    # send_sell_order('BIYA','4','5251','NASD')
    # send_sell_order('BNAI','4','1878','NASD')
    # send_sell_order('EVTV','2','7001','NASD')
    # send_sell_order('SEGG','1','20310','NASD')
