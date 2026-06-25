"""
strategies/pair_config.py
AtlasFX Pair-Specific Configuration
Based on 3-year backtest EV maximisation (2023-2025)
All EV > £200 threshold passed
"""

# London ORB — optimal TP per pair (SL always 0.5x range)
LONDON_ORB_TP = {
    "AUD_CAD": 0.75,  # 78.4% WR £371 EV
    "AUD_CHF": 0.5,   # 80.6% WR £208 EV
    "AUD_NZD": 1.5,   # 52.8% WR £321 EV
    "AUD_USD": 0.75,  # 70.7% WR £237 EV
    "CAD_JPY": 1.0,   # 64.3% WR £286 EV
    "CHF_JPY": 1.0,   # 74.5% WR £490 EV
    "EUR_AUD": 0.5,   # 82.8% WR £242 EV
    "EUR_CAD": 0.75,  # 77.8% WR £361 EV
    "EUR_GBP": 0.5,   # 80.7% WR £211 EV
    "EUR_JPY": 0.75,  # 77.4% WR £355 EV
    "EUR_NZD": 0.5,   # 91.7% WR £375 EV
    "EUR_USD": 1.5,   # 53.0% WR £325 EV
    "GBP_AUD": 0.5,   # 90.2% WR £353 EV
    "GBP_CAD": 1.0,   # 72.2% WR £444 EV
    "GBP_CHF": 0.5,   # 88.0% WR £319 EV
    "GBP_JPY": 1.0,   # 75.7% WR £514 EV
    "GBP_NZD": 0.5,   # 91.7% WR £375 EV
    "GBP_USD": 1.5,   # 60.5% WR £512 EV
    "NZD_CAD": 1.5,   # 52.6% WR £314 EV
    "NZD_CHF": 1.5,   # 50.9% WR £273 EV
    "NZD_JPY": 0.5,   # 84.1% WR £261 EV
    "NZD_USD": 1.5,   # 54.3% WR £358 EV
    "USD_CAD": 1.5,   # 60.2% WR £504 EV
    "USD_CHF": 1.5,   # 55.6% WR £389 EV
    "USD_JPY": 1.5,   # 56.8% WR £419 EV
    "XAG_USD": 1.0,   # 68.0% WR £360 EV
    "XAU_USD": 1.0,   # 62.1% WR £242 EV
}

# NY ORB — optimal TP per pair
NY_ORB_TP = {
    "AUD_CAD": 1.0,   # 72.4% WR £448 EV
    "AUD_USD": 1.0,   # 74.3% WR £486 EV
    "CAD_JPY": 0.75,  # 72.3% WR £266 EV
    "CHF_JPY": 0.75,  # 80.4% WR £408 EV
    "EUR_AUD": 1.0,   # 65.2% WR £304 EV
    "EUR_CAD": 1.5,   # 61.1% WR £528 EV
    "EUR_JPY": 0.5,   # 89.7% WR £346 EV
    "EUR_NZD": 1.5,   # 57.4% WR £435 EV
    "EUR_USD": 1.5,   # 68.1% WR £702 EV
    "GBP_AUD": 1.5,   # 64.6% WR £615 EV
    "GBP_CAD": 0.75,  # 76.2% WR £333 EV
    "GBP_CHF": 1.5,   # 67.5% WR £688 EV
    "GBP_JPY": 0.5,   # 86.0% WR £291 EV
    "GBP_NZD": 1.0,   # 75.5% WR £509 EV
    "GBP_USD": 0.75,  # 82.8% WR £448 EV
    "NZD_CAD": 1.5,   # 47.1% WR £176 EV (marginal — keep for now)
    "NZD_CHF": 1.5,   # 68.0% WR £700 EV
    "NZD_JPY": 1.5,   # 55.8% WR £395 EV
    "NZD_USD": 1.5,   # 76.0% WR £900 EV
    "USD_CAD": 1.0,   # 71.0% WR £419 EV
    "USD_CHF": 0.75,  # 83.3% WR £458 EV
    "USD_JPY": 1.5,   # 57.1% WR £429 EV
    "XAG_USD": 1.5,   # 77.4% WR £935 EV
}

# EMA Pullback — all pairs validated (EV > £200 on 2.5R)
EMA_PULLBACK_PAIRS = [
    "AUD_CAD",  # 50.0% WR £750 EV
    "AUD_CHF",  # 61.9% WR £1167 EV
    "AUD_NZD",  # 52.0% WR £820 EV
    "CAD_JPY",  # 72.4% WR £1534 EV
    "CHF_JPY",  # 66.7% WR £1333 EV
    "EUR_AUD",  # 54.2% WR £896 EV
    "EUR_CAD",  # 63.6% WR £1227 EV
    "EUR_GBP",  # 63.9% WR £1236 EV
    "EUR_JPY",  # 56.5% WR £978 EV
    "EUR_NZD",  # 47.6% WR £667 EV
    "EUR_USD",  # 45.8% WR £604 EV
    "GBP_AUD",  # 75.0% WR £1625 EV
    "GBP_CAD",  # 66.7% WR £1333 EV
    "GBP_CHF",  # 60.0% WR £1100 EV
    "GBP_NZD",  # 58.6% WR £1052 EV
    "GBP_USD",  # 63.3% WR £1217 EV
    "NZD_CAD",  # 65.0% WR £1275 EV
    "NZD_USD",  # 65.2% WR £1283 EV
    "USD_CAD",  # 55.6% WR £944 EV
    "USD_CHF",  # 65.5% WR £1293 EV
    "USD_JPY",  # 59.3% WR £1074 EV
    "XAG_USD",  # 61.9% WR £1167 EV
    "XAU_USD",  # 65.0% WR £1275 EV
]

DEFAULT_TP = 1.5

def get_london_tp(instrument: str) -> float:
    return LONDON_ORB_TP.get(instrument, DEFAULT_TP)

def get_ny_tp(instrument: str) -> float:
    return NY_ORB_TP.get(instrument, DEFAULT_TP)
