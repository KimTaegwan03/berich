import requests
import json, os
from datetime import datetime, timedelta
import dotenv

dotenv.load_dotenv()

# ==========================================================
# [설정] 한국투자증권 API 설정 (반드시 입력!)
# ==========================================================
# 모의투자: https://openapivts.koreainvestment.com:29443
# 실전투자: https://openapi.koreainvestment.com:9443
KIS_BASE_URL = "https://openapivts.koreainvestment.com:29443"

KIS_APP_KEY = os.environ.get("KIS_APP_KEY_MOCK")
KIS_APP_SECRET = os.environ.get("KIS_APP_SECRET_MOCK")
KIS_CANO = os.environ.get("KIS_CANO_MOCK")
KIS_ACNT_PRDT_CD = os.environ.get("KIS_ACNT_PRDT_CD_MOCK")

# 전역 변수 (토큰 캐싱용)
ACCESS_TOKEN = None
TOKEN_EXPIRY = None

def get_kis_token():
    """접근 토큰 발급/갱신 (싱글톤 패턴)"""
    global ACCESS_TOKEN, TOKEN_EXPIRY
    
    if ACCESS_TOKEN and TOKEN_EXPIRY and datetime.now() < TOKEN_EXPIRY:
        return ACCESS_TOKEN

    url = f"{KIS_BASE_URL}/oauth2/tokenP"
    headers = {"content-type": "application/json"}
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
        print(f"🔑 [KIS] 토큰 발급 완료")
        return ACCESS_TOKEN
    except Exception as e:
        print(f"❌ [KIS] 토큰 발급 실패: {e}")
        return None
    
def get_account_balance():
    """
    계좌의 총 자산(USD)과 주문가능 현금(USD)을 조회
    return: (총자산, 주문가능현금)
    """
    token = get_kis_token()
    if not token: return 0.0, 0.0

    # 모의투자 잔고조회 TR ID: VTRP6504R / 실전: CTRP6504R
    tr_id = "VTRP6504R" if KIS_BASE_URL == "https://openapivts.koreainvestment.com:29443" else "CTRP6504R"
    
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

    try:
        res = requests.get(url, headers=headers, params=params)
        data = res.json()
        
        if data['rt_cd'] != '0':
            print(f"❌ [잔고조회 실패] {data['msg1']}")
            return 0.0, 0.0
            
        # output2: 계좌 상세 자산 내역
        output3 = data['output3']
        
        # ovrs_tot_pfls_amt: 해외주식 평가 금액 (주식 가치)
        # frcr_drwg_psbl_amt_1: 외화 예수금 (현금)
        stock_val = float(output3.get('evlu_amt_smtl', 0))
        cash_val = float(output3.get('frcr_evlu_tota', 0))
        
        total_asset = stock_val + cash_val # 총 자산

        print(f"💰 [잔고조회 완료] {total_asset:.2f}")
        
        return total_asset, cash_val

    except Exception as e:
        print(f"❌ [잔고조회 에러] {e}")
        return 0.0, 0.0

def send_buy_order(ticker, price, qty, exchange="NAS"):
    """지정가 매수 주문"""
    token = get_kis_token()
    if not token: return False
    
    # [중요] 모의투자 매수 TR ID: JTTT1002U / 실전: TTTT1002U
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
        "ORD_QTY": str(qty),
        "OVRS_ORD_UNPR": str(price),
        "ORD_SVR_DVSN_CD": "0",
        "ORD_DVSN": "00"        # 00: 지정가
    }

    try:
        res = requests.post(url, headers=headers, data=json.dumps(body))
        data = res.json()
        if data['rt_cd'] == '0':
            print(f"✅ [주문성공] {ticker} ${price} / {qty}주 (주문번호: {data['output']['ODNO']})")
            return True
        else:
            print(f"❌ [주문실패] {ticker}: {data['msg1']} (Code: {data['msg_cd']})")
            return False
    except Exception as e:
        print(f"❌ [API오류] {e}")
        return False
    
def send_sell_order(ticker, price, qty, exchange="NAS"):
    """
    해외주식 지정가 매도 주문
    """
    token = get_kis_token()
    if not token: return False

    # [중요] 모의투자 매도 TR ID: JTTT1006U (실전: TTTT1006U)
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
        "OVRS_ORD_UNPR": str(price),
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

def get_stock_quantity():
    """
    특정 종목의 보유 수량 조회 (매도 전 확인용)
    return: 보유수량 (int)
    """
    token = get_kis_token()
    if not token: return 0

    # 잔고 조회 TR 사용 (모의: VTTS3012R)
    tr_id = "VTTS3012R"
    
    url = f"{KIS_BASE_URL}/uapi/overseas-stock/v1/trading/inquire-balance"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appKey": KIS_APP_KEY,
        "appSecret": KIS_APP_SECRET,
        "tr_id": tr_id
    }
    
    # 거래소 코드는 보유량 조회할 때 크게 중요하지 않음 (NAS로 통일)
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
    token = get_kis_token()
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
                    if ord['nccs_qty'] > 0 and ord['sll_buy_dvsn_cd'] == "02":
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
        url = f"{KIS_BASE_URL}/uapi/overseas-stock/v1/trading/inquire-nccs"

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
            "OVRS_EXCG_CD": "NADS",
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
                    if ord['nccs_qty'] > 0:
                        outputs.append(ord)

                return outputs
            else:
                return 0
        except Exception as e:
            print(f"❌ [미체결내역조회 오류] {e}")
            return 0

# 주문 취소
def cancel_order(ticker, order_no, qty):
    token = get_kis_token()
    if not token: return False

    ## 모의투자
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
        "OVRS_EXCG_CD": "NADS",
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



if __name__ == "__main__":
    import json
    get_kis_token()
    total, orderable = get_account_balance()
    hold = get_stock_quantity()

    print(total)
    print(orderable)
    print(json.dumps(hold, indent=2))

    send_sell_order('BIYA','4','5251','NASD')
    send_sell_order('BNAI','4','1878','NASD')
    send_sell_order('EVTV','2','7001','NASD')
    send_sell_order('SEGG','1','20310','NASD')

