from __future__ import annotations
from logs.logger import get_logger
log = get_logger(__name__)

CORRELATION_GROUPS = {
    "MAJOR_USD_LONGS":["EUR_USD","GBP_USD","AUD_USD","NZD_USD"],
    "MAJOR_USD_SHORTS":["USD_JPY","USD_CHF","USD_CAD"],
    "EURO_CROSSES":["EUR_GBP","EUR_JPY","EUR_CHF","EUR_AUD","EUR_CAD"],
    "GBP_CROSSES":["GBP_JPY","GBP_CHF","GBP_AUD","GBP_CAD"],
    "AUD_CROSSES":["AUD_JPY","AUD_CAD","AUD_CHF","AUD_NZD"],
    "JPY_CROSSES":["CAD_JPY","CHF_JPY","NZD_JPY"],
    "METALS":["XAU_USD","XAG_USD"],
}

INSTRUMENT_TO_GROUP = {}
for g, insts in CORRELATION_GROUPS.items():
    for i in insts: INSTRUMENT_TO_GROUP[i] = g

MAX_OPEN_POSITIONS = 6
MAX_PER_GROUP = 2

class CorrelationFilter:
    def can_open(self, instrument, direction, open_positions):
        if len(open_positions) >= MAX_OPEN_POSITIONS:
            return False, f"Max open positions reached ({MAX_OPEN_POSITIONS})"
        new_group = INSTRUMENT_TO_GROUP.get(instrument)
        if not new_group: return True, "OK"
        group_positions = [
            {"instrument":p.get("instrument"),"direction":p.get("direction"),"trade_id":tid}
            for tid,p in open_positions.items()
            if INSTRUMENT_TO_GROUP.get(p.get("instrument","")) == new_group
        ]
        if len(group_positions) >= MAX_PER_GROUP:
            ex = group_positions[0]
            reason = (f"Correlation block: already have {ex["instrument"]} "
                     f"{ex["direction"]} in group {new_group}")
            log.info("correlation_blocked", instrument=instrument,
                     direction=direction, group=new_group,
                     existing=ex["instrument"])
            return False, reason
        return True, "OK"

    def get_group(self, instrument): return INSTRUMENT_TO_GROUP.get(instrument,"UNKNOWN")

    def get_group_exposure(self, open_positions):
        exposure = {g:[] for g in CORRELATION_GROUPS}
        for tid,p in open_positions.items():
            g = INSTRUMENT_TO_GROUP.get(p.get("instrument",""))
            if g and g in exposure:
                exposure[g].append({"instrument":p.get("instrument"),
                    "direction":p.get("direction"),"trade_id":tid})
        return {k:v for k,v in exposure.items() if v}
