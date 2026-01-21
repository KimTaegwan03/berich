import pandas as pd
import numpy as np

## 주식 보조지표

def ichimoku(df: pd.DataFrame, conf):

    def clean_list(data_list):
        return [None if pd.isna(x) else float(x) for x in data_list]

    if df.empty:
        return None
    
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.reset_index(inplace=True)

    date_col = 'Datetime' if 'Datetime' in df.columns else 'Date'
    if date_col not in df.columns:
        return None
    
    # 전환선, 기준선
    high_9 = df['High'].rolling(window=9).max()
    low_9 = df['Low'].rolling(window=9).min()
    tenkan = (high_9 + low_9) / 2

    high_26 = df['High'].rolling(window=26).max()
    low_26 = df['Low'].rolling(window=26).min()
    kijun = (high_26 + low_26) / 2

    span_a_calc = (tenkan + kijun) / 2

    high_52 = df['High'].rolling(window=52).max()
    low_52 = df['Low'].rolling(window=52).min()
    span_b_calc = (high_52 + low_52) / 2

    last_date = df[date_col].iloc[-1]
    future_dates = []
    current_delta = conf['delta']

    for i in range(1, 27):
        future_dates.append(last_date + (current_delta * i))

    full_dates = df[date_col].tolist() + future_dates
    full_dates_str = [d.strftime('%Y-%m-%d %H:%M') for d in full_dates]

    pad_none = [None] * 26

    final_open = clean_list(df['Open'].tolist()) + pad_none
    final_high = clean_list(df['High'].tolist()) + pad_none
    final_low = clean_list(df['Low'].tolist()) + pad_none
    final_close = clean_list(df['Close'].tolist()) + pad_none

    span_a_list = span_a_calc.tolist()
    span_b_list = span_b_calc.tolist()
    final_span_a = pad_none + clean_list(span_a_list)
    final_span_b = pad_none + clean_list(span_b_list)

    chart_data = {
                "dates": full_dates_str,
                "open": final_open,
                "high": final_high,
                "low": final_low,
                "close": final_close,
                "span_a": final_span_a,
                "span_b": final_span_b
            }
    
    return chart_data

def span_b_signal(data, n, k):
    '''
    Docstring for span_b_signal
    
    :param data: data = {
                "dates": full_dates_str,
                "open": final_open,
                "high": final_high,
                "low": final_low,
                "close": final_close,
                "span_a": final_span_a,
                "span_b": final_span_b
            }
    '''

    #[디버깅용] 마지막 n개 span_b 값 출력
    # print(data['span_b'][-n:])
    
    # 마지막 span_b 값 기준 이전 n개의 span_b 값이 오차범위 k% 내에 있으면 일단 통과
    span_b_values = data['span_b']
    close_values = data['close']

    if len(span_b_values) < n or len(close_values) < 1:
        return False, None #"데이터 부족"

    last_span_b = span_b_values[-1]
    last_close = close_values[-1-26]

    if last_span_b is None or last_close is None:
        return False, None # "최신 Span B 또는 종가 데이터 없음"

    # 마지막 n개의 span_b 값 추출 (None 값 제외)
    recent_span_b_raw = [val for val in span_b_values[-n:] if val is not None]

    # [디버깅용] recent_span_b_raw 출력
    # print(recent_span_b_raw)
    
    if not recent_span_b_raw:
        return False, None # "최근 Span B 데이터 부족"

    # 마지막 유효한 span_b 값
    current_span_b_val = recent_span_b_raw[-1]

    # 오차 범위 내에 있는지 확인
    is_flat = True
    for val in recent_span_b_raw:
        if not (current_span_b_val * (1 - k/100) <= val <= current_span_b_val * (1 + k/100)):
            is_flat = False
            break
    
    if is_flat:
        # 현재 종가가 Span B 위에 있는지 확인 (k% 오차범위 허용)
        if last_close > current_span_b_val * (1 - k/100):

            # 최근 n개의 봉의 저가가 모두 Span B 위에 있는지 확인
            recent_lows = [val for val in close_values[-n-26:-26] if val is not None] # 종가 대신 저가 사용
            # print(recent_lows)

            if not recent_lows:
                return False, None # "최근 저가 데이터 부족"

            is_above_span_b = all(low > current_span_b_val * (1 - k/100) for low in recent_lows)

            if is_above_span_b:
                return True, current_span_b_val
                # f"Span B Flat & {n}봉 동안 Span B 위에 있음 (Flat Value: {current_span_b_val:.2f})"
            else:
                return False, current_span_b_val
                # f"Span B Flat 이지만 {n}봉 동안 Span B 위에 있지 않음 (Flat Value: {current_span_b_val:.2f})"
        else:
            return False, current_span_b_val
            # f"Span B Flat 이지만 현재가가 아래에 있음 (Flat Value: {current_span_b_val:.2f})"
    else:
        return False, None
        # "Span B Flat 조건 불충족"


if __name__ == "__main__":
    import yfinance as yf
    from datetime import timedelta
    from kis_api import get_5m_candles

    

    ticker = "BNAI"
    excg = "NASD"

    prices = get_5m_candles(ticker, excg, real=True)

    print(prices)

    chart_data = ichimoku(prices, {"delta": timedelta(minutes=5)})

    ichimoku_signal = span_b_signal(chart_data,7,2)
    print(ticker)
    print(ichimoku_signal)
