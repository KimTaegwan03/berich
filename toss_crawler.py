import time
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import warnings
warnings.filterwarnings("ignore")

MAX_MARKET_CAP_USD = 50_000_000 

def scrape_toss_data():
    """
    기존 스크래핑 로직을 함수화하여 데이터를 리스트로 반환
    """
    results = []
    
    # ---------------------------------------------------------
    # [Step 1] 셀레니움으로 쿠키 획득
    # ---------------------------------------------------------
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    chrome_options.add_argument(f'user-agent={user_agent}')

    # webdriver_manager를 사용하여 드라이버 자동 관리
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    base_url = "https://tossinvest.com/?market=us&live-chart=biggest_total_amount"
    try:
        driver.get(base_url)
        time.sleep(3)
        selenium_cookies = driver.get_cookies()
    finally:
        driver.quit()

    # ---------------------------------------------------------
    # [Step 2] Requests 세션 설정
    # ---------------------------------------------------------
    session = requests.Session()
    for cookie in selenium_cookies:
        session.cookies.set(cookie['name'], cookie['value'])

    headers = {
        'User-Agent': user_agent,
        'Referer': base_url,
        'Content-Type': 'application/json',
        'Origin': 'https://tossinvest.com',
        'Accept': 'application/json'
    }

    # ---------------------------------------------------------
    # [Step 3] 랭킹 API 호출
    # ---------------------------------------------------------
    rank_api_url = "https://wts-cert-api.tossinvest.com/api/v2/dashboard/wts/overview/ranking"
    rank_payload = {
        'id': 'biggest_total_amount',
        'filters': [], # 필터 없이 전체 가져온 뒤 파이썬에서 거름
        'duration': 'realtime',
        'tag': 'us',
    }

    rank_resp = session.post(rank_api_url, headers=headers, json=rank_payload)
    if rank_resp.status_code != 200:
        return {"error": f"랭킹 조회 실패: {rank_resp.status_code}"}

    rank_data = rank_resp.json()
    products = [p for p in rank_data.get('result', {}).get('products', []) if p.get('tossSecuritiesAmount', 0) >= 100_000_000]
    product_codes = [p['productCode'] for p in products]

    if not product_codes:                                                                                                                                                           
        return []

    # ---------------------------------------------------------
    # [Step 4] 상세 정보 API 호출
    # ---------------------------------------------------------
    codes_str = ",".join(product_codes)
    info_api_url = f"https://wts-info-api.tossinvest.com/api/v1/stock-infos?codes={codes_str}"
    
    info_resp = session.get(info_api_url, headers=headers)
    if info_resp.status_code != 200:
        return {"error": f"상세 조회 실패: {info_resp.status_code}"}

    info_json = info_resp.json()
    stock_infos = info_json.get('result', {})

    details_map = {}
    for info in stock_infos:
        p_code = info.get('code')
        symbol = info.get('symbol')
        shares = info.get('sharesOutstanding')

        group_code = info.get('group', {}).get('code','')
        market_code = info.get('market', {}).get('code','NSQ')
        

        if p_code:
            details_map[p_code] = {
                'symbol': symbol or "N/A",
                'shares': shares or 0,
                'group_code': group_code,
                'exchange': market_code
            }

    # ---------------------------------------------------------
    # [Step 5] 데이터 가공 및 필터링
    # ---------------------------------------------------------
    for item in products:
        p_code = item['productCode']

        detail = details_map.get(p_code, {'symbol': 'N/A', 'shares': 0, 'group_code': '', 'exchange': 'NSQ'})
        if detail['group_code'] == 'EF':
            continue

        price_data = item.get('price', {})
        
        # 토스 데이터 기준: base가 전일종가, close가 현재가
        current_price = price_data.get('close', 0)
        prev_close = price_data.get('base', 0)

        # 등락률 계산
        if prev_close > 0:
            change_rate = ((current_price - prev_close) / prev_close) * 100
        else:
            change_rate = 0.0
            
        detail = details_map.get(p_code, {'symbol': 'N/A', 'shares': 0, 'group_code': '', 'exchange': 'NSQ'})
        ticker = detail['symbol']
        shares = detail['shares']
        
        market_cap = current_price * shares
        
        # 필터링 로직
        if market_cap > MAX_MARKET_CAP_USD:
            continue
        
        # 시총 문자열 포맷팅
        if market_cap >= 1_000_000_000:
            cap_str = f"{market_cap/1_000_000_000:.2f}B"
        elif market_cap >= 1_000_000:
            cap_str = f"{market_cap/1_000_000:.2f}M"
        else:
            cap_str = f"{market_cap:,.0f}"
        
        exchange = detail['exchange']

        results.append({
            "rank": item['rank'],
            "ticker": ticker,
            "exchange": exchange,
            "name": item['name'],
            "price": current_price,
            "change_rate": round(change_rate, 2),
            "market_cap": cap_str,
            "raw_cap": market_cap # 정렬용 원본 데이터
        })
        
    return results