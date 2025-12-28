import ccxt
import pandas as pd
from dash import Dash, dash_table, html, dcc
from dash.dependencies import Input, Output
import dash_bootstrap_components as dbc
import os

# ================= CONFIG =================
SYMBOLS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT",
    "AVAXUSDT","LINKUSDT","XRPUSDT","TRXUSDT","ZECUSDT",
    "ATOMUSDT","TRUMPUSDT","SUIUSDT","DOGEUSDT","DOTUSDT",
    "ADAUSDT","LUNCUSDT","AAVEUSDT","DASHUSDT","LTCUSDT",
    "XTZUSDT","TURTLEUSDT","INJUSDT","ICPUSDT","TONUSDT",
    "USDTUSD","SHIBUSDT"
]

HTF = "1h"
LTF = "15m"
LIMIT = 300
REFRESH_SEC = 900  # 15 minutes

RR_TREND = 2.0
RR_RANGE = 1.5

# ================= CCXT EXCHANGE =================
exchange = ccxt.binance({
    "enableRateLimit": True
})

# ================= INDICATORS =================
def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(period).mean() / loss.rolling(period).mean()
    return 100 - (100 / (1 + rs))

def macd(series):
    fast = ema(series, 12)
    slow = ema(series, 26)
    signal = ema(fast - slow, 9)
    hist = (fast - slow) - signal
    return fast - slow, signal, hist

# ================= CANDLE CLOSE POSITION =================
def candle_bias(c):
    rng = c["h"] - c["l"]
    if rng == 0:
        return "NEUTRAL"
    pos = (c["c"] - c["l"]) / rng
    if pos >= 0.65:
        return "BULLISH"
    elif pos <= 0.35:
        return "BEARISH"
    else:
        return "RANGE"

# ================= DATA =================
def ccxt_symbol(symbol):
    return symbol.replace("USDT", "/USDT")

def get_df(symbol, tf):
    ohlcv = exchange.fetch_ohlcv(
        ccxt_symbol(symbol),
        timeframe=tf,
        limit=LIMIT
    )
    df = pd.DataFrame(
        ohlcv,
        columns=["time","o","h","l","c","v"]
    )
    return df

# ================= ENGINE =================
def evaluate(symbol):

    ltf = get_df(symbol, LTF)
    htf = get_df(symbol, HTF)

    for p in [20,50,200]:
        ltf[f"EMA{p}"] = ema(ltf["c"], p)
        htf[f"EMA{p}"] = ema(htf["c"], p)

    ltf["RSI"] = rsi(ltf["c"])
    macd_line, macd_signal, macd_hist = macd(ltf["c"])

    i = -2  # last closed candle
    candle = ltf.iloc[i]

    # -------- Candle metrics --------
    high = round(candle["h"], 4)
    low = round(candle["l"], 4)
    rng = round(high - low, 4)
    close_pct = round((candle["c"] - low) / (rng if rng else 1) * 100, 1)
    bias = candle_bias(candle)

    price = round(candle["c"], 4)
    ema20 = ltf["EMA20"].iloc[i]
    ema50 = ltf["EMA50"].iloc[i]
    ema200 = ltf["EMA200"].iloc[i]
    rsi_now = ltf["RSI"].iloc[i]
    hist_now = macd_hist.iloc[i]
    hist_prev = macd_hist.iloc[i-1]

    # -------- REGIME (HTF) --------
    uptrend = (
        htf["c"].iloc[-2] > htf["EMA200"].iloc[-2]
        and htf["EMA50"].iloc[-2] > htf["EMA50"].iloc[-5]
    )
    regime = "UPTREND" if uptrend else "RANGE"

    # -------- SUPPORT / RESIST --------
    support = min(ltf["l"].iloc[i-6:i])
    resistance = max(ltf["h"].iloc[i-6:i])

    # ================= BUY =================
    buy = buy_reason = ""
    entry = target = stop = ""

    if (
        regime == "UPTREND"
        and bias == "BULLISH"
        and ema20 > ema50 > ema200
        and price >= ema50 * 0.995
        and rsi_now > 45
    ):
        buy = "BUY"
        buy_reason = "Uptrend + EMA50 pullback + bullish close"
        entry = price
        stop = round(support, 4)
        target = round(entry + (entry - stop) * RR_TREND, 4)

    elif (
        regime == "RANGE"
        and bias == "RANGE"
        and price <= support * 1.01
        and hist_now > hist_prev
        and rsi_now > 35
    ):
        buy = "BUY"
        buy_reason = "Range support + MACD rising + neutral close"
        entry = price
        stop = round(support, 4)
        target = round(entry + (entry - stop) * RR_RANGE, 4)

    # ================= SELL =================
    sell = sell_reason = ""

    if regime == "UPTREND" and (price < ema50 or bias == "BEARISH"):
        sell = "SELL"
        sell_reason = "EMA50 loss or bearish close"

    elif regime == "RANGE" and hist_now < 0:
        sell = "SELL"
        sell_reason = "MACD turned negative"

    return {
        "Symbol": symbol.replace("USDT",""),
        "Price": price,
        "Regime": regime,

        "High": high,
        "Low": low,
        "Range": rng,
        "Close %": close_pct,
        "Candle": bias,

        "BUY": buy,
        "Entry": entry,
        "Target": target,
        "Stop": stop,
        "BUY Reason": buy_reason,

        "SELL": sell,
        "SELL Reason": sell_reason,

        "Chart": f"https://www.binance.com/en/trade/{symbol.replace('USDT','')}_USDT?type=spot"
    }

# ================= DASH =================
app = Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])
server = app.server

app.layout = dbc.Container([
    html.H3("📊 Final Trend + Range Engine — Candle Metrics Enabled",
            className="text-center my-3"),

    dash_table.DataTable(
        id="table",
        style_table={"overflowX": "auto"},
        style_cell={
            "backgroundColor": "#111",
            "color": "white",
            "border": "1px solid #333",
            "textAlign": "center",
            "fontSize": "12px"
        },
        style_header={"backgroundColor": "#222", "fontWeight": "bold"},
        style_data_conditional=[
            {"if": {"filter_query": '{Candle} = "BULLISH"'}, "backgroundColor": "#003300"},
            {"if": {"filter_query": '{Candle} = "BEARISH"'}, "backgroundColor": "#330000"},
            {"if": {"filter_query": '{BUY} = "BUY"'}, "backgroundColor": "#004422"},
            {"if": {"filter_query": '{SELL} = "SELL"'}, "backgroundColor": "#442200"}
        ],
        columns=[
            {"name": c, "id": c, "presentation": "markdown" if c=="Chart" else "input"}
            for c in [
                "Symbol","Price","Regime",
                "High","Low","Range","Close %","Candle",
                "BUY","Entry","Target","Stop","BUY Reason",
                "SELL","SELL Reason","Chart"
            ]
        ]
    ),

    dcc.Interval(id="interval", interval=REFRESH_SEC * 1000)
], fluid=True)

@app.callback(Output("table","data"), Input("interval","n_intervals"))
def refresh(_):
    rows = []
    for s in SYMBOLS:
        try:
            r = evaluate(s)
            r["Chart"] = f"[Open]({r['Chart']})"
            rows.append(r)
        except Exception as e:
            print(s, e)
            continue
    return rows

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    app.run(debug=False, host="0.0.0.0", port=port)
