"""Monthly-Daily CRT scanner with FVG, IFVG, OB and BOB retest entries.

Mechanical OHLC definitions are explicit below. Only completed Monthly/Daily
candles are used; this is a screening model, not a guaranteed trade signal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time as dtime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ZONE_PRIORITY = {"FVG": 0, "IFVG": 1, "OB": 2, "BOB": 3}


@dataclass(frozen=True)
class ScanConfig:
    pivot_left: int = 3
    pivot_right: int = 3
    entry_valid_days: int = 3
    ob_lookback_days: int = 10
    bob_lookback_days: int = 30


def _normalise_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        names = {"open", "high", "low", "close", "volume"}
        data.columns = [
            next((str(x).title() for x in col if str(x).lower() in names), str(col[0]).title())
            for col in data.columns
        ]
    data.columns = [str(c).strip().title() for c in data.columns]
    required = ["Open", "High", "Low", "Close"]
    if not all(c in data.columns for c in required):
        return pd.DataFrame()
    cols = required + (["Volume"] if "Volume" in data.columns else [])
    data = data[cols].copy()
    data.index = pd.to_datetime(data.index)
    if getattr(data.index, "tz", None) is not None:
        data.index = data.index.tz_localize(None)
    data = data[~data.index.duplicated(keep="last")].sort_index()
    for col in cols:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    return data.dropna(subset=required)


def _confirmed_pivots(series: pd.Series, left: int, right: int, is_high: bool) -> pd.Series:
    """Publish a pivot only when its right-side confirmation bars have closed."""
    values = series.to_numpy(float)
    out = np.full(len(values), np.nan)
    width = left + right + 1
    for i in range(width - 1, len(values)):
        p = i - right
        window = values[i - width + 1 : i + 1]
        value = values[p]
        if (
            np.isfinite(window).all()
            and value == (np.max(window) if is_high else np.min(window))
            and np.count_nonzero(window == value) == 1
        ):
            out[i] = value
    return pd.Series(out, index=series.index)


def _three_month_context(data: pd.DataFrame) -> dict[str, Any] | None:
    """M1 and M2 are completed months; M3 is the current Daily-structure month."""
    if data.empty:
        return None
    keys = data.index.to_period("M")
    months = data.groupby(keys).agg(High=("High", "max"), Low=("Low", "min"), Close=("Close", "last"))
    if len(months) < 3:
        return None
    m1, m2 = months.iloc[-3], months.iloc[-2]
    m1p, m2p, m3p = months.index[-3], months.index[-2], months.index[-1]
    rows2 = data.loc[keys == m2p]
    rows3 = data.loc[keys == m3p]
    if rows2.empty or rows3.empty:
        return None

    m1_high, m1_low = float(m1.High), float(m1.Low)
    m2_close = float(m2.Close)
    close_inside = m1_low < m2_close < m1_high
    # Sweep candle itself must close back inside the full M1 range.
    bull_rows = rows2[
        (rows2.Low < m1_low) & (rows2.Close > m1_low) & (rows2.Close < m1_high)
    ]
    bear_rows = rows2[
        (rows2.High > m1_high) & (rows2.Close < m1_high) & (rows2.Close > m1_low)
    ]

    bias = 0
    sweep_row = None
    if not bull_rows.empty and not bear_rows.empty:
        monthly_status = "AMBIGUOUS_BOTH_SIDES_SWEPT"
    elif not close_inside:
        monthly_status = "INVALID_M2_CLOSE_OUTSIDE_M1_RANGE"
    elif not bull_rows.empty:
        bias, monthly_status, sweep_row = 1, "VALID_BULLISH_SWEEP", bull_rows.iloc[-1]
    elif not bear_rows.empty:
        bias, monthly_status, sweep_row = -1, "VALID_BEARISH_SWEEP", bear_rows.iloc[-1]
    else:
        monthly_status = "NO_M1_LIQUIDITY_SWEEP"

    return {
        "m1_high": m1_high, "m1_low": m1_low,
        "m2_high": float(m2.High), "m2_low": float(m2.Low), "m2_close": m2_close,
        "m2_start": rows2.index[0], "m3_start": rows3.index[0],
        "sweep_date": sweep_row.name if sweep_row is not None else None,
        "sweep_high": float(sweep_row.High) if sweep_row is not None else np.nan,
        "sweep_low": float(sweep_row.Low) if sweep_row is not None else np.nan,
        "m1_period": str(m1p), "m2_period": str(m2p), "m3_period": str(m3p),
        "bias": bias, "monthly_status": monthly_status,
    }


def _monthly_context(data: pd.DataFrame) -> dict[str, Any] | None:
    ctx = _three_month_context(data)
    if ctx is None:
        return None
    keys = {"m1_high", "m1_low", "m2_high", "m2_low", "m2_close", "m2_start", "m1_period", "m2_period"}
    return {key: value for key, value in ctx.items() if key in keys}


def _zone(kind: str, low: float, high: float, origin_index: int, available_index: int, **extra: Any) -> dict[str, Any]:
    return {
        "type": kind,
        "low": float(min(low, high)),
        "high": float(max(low, high)),
        "origin_index": int(origin_index),
        "available_index": int(available_index),
        **extra,
    }


def _collect_entry_zones(
    data: pd.DataFrame,
    m3_start: int,
    choch_index: int,
    last_index: int,
    direction: int,
    config: ScanConfig,
) -> list[dict[str, Any]]:
    """Find independent directional FVG, IFVG, OB and BOB zones.

    FVG: same-direction three-candle gap formed after CHoCH.
    IFVG: opposite three-candle gap closed through after CHoCH; then it flips.
    OB: nearest opposite-colour candle before the directional CHoCH candle.
    BOB: an older counter-direction block broken through its far edge in the
         trade direction after CHoCH.
    """
    zones: list[dict[str, Any]] = []
    start, ch, end = int(m3_start), int(choch_index), int(last_index)

    # FVG: must form strictly after CHoCH; a retest cannot be the formation bar.
    for i in range(max(ch + 1, start + 2, 2), end + 1):
        if direction == 1 and float(data.Low.iloc[i]) > float(data.High.iloc[i - 2]):
            zones.append(_zone("FVG", data.High.iloc[i - 2], data.Low.iloc[i], i - 2, i))
        elif direction == -1 and float(data.High.iloc[i]) < float(data.Low.iloc[i - 2]):
            zones.append(_zone("FVG", data.High.iloc[i], data.Low.iloc[i - 2], i - 2, i))

    # IFVG: identify every opposite FVG and its first post-CHoCH close-through.
    for i in range(max(start + 2, 2), end + 1):
        gap = None
        if direction == 1 and float(data.High.iloc[i]) < float(data.Low.iloc[i - 2]):
            gap = (float(data.High.iloc[i]), float(data.Low.iloc[i - 2]))
        elif direction == -1 and float(data.Low.iloc[i]) > float(data.High.iloc[i - 2]):
            gap = (float(data.High.iloc[i - 2]), float(data.Low.iloc[i]))
        if gap is None:
            continue
        low, high = gap
        flip = next(
            (
                k for k in range(max(ch, i + 1), end + 1)
                if (float(data.Close.iloc[k]) > high if direction == 1 else float(data.Close.iloc[k]) < low)
            ),
            None,
        )
        if flip is not None:
            zones.append(_zone("IFVG", low, high, i - 2, flip, flip_index=flip))

    # OB: nearest counter-direction candle immediately preceding the CHoCH break.
    choch_is_directional = (
        float(data.Close.iloc[ch]) > float(data.Open.iloc[ch])
        if direction == 1 else float(data.Close.iloc[ch]) < float(data.Open.iloc[ch])
    )
    latest_ob_index = None
    if choch_is_directional:
        ob_start = max(start, ch - max(1, int(config.ob_lookback_days)))
        for j in range(ch - 1, ob_start - 1, -1):
            opposite = (
                float(data.Close.iloc[j]) < float(data.Open.iloc[j])
                if direction == 1 else float(data.Close.iloc[j]) > float(data.Open.iloc[j])
            )
            if opposite:
                zones.append(_zone("OB", data.Low.iloc[j], data.High.iloc[j], j, ch))
                latest_ob_index = j
                break

    # BOB: an older counter-direction block (not the nearest OB candle) is
    # broken through its far edge in the trade direction after CHoCH. The
    # broken block is treated as a breaker only after that completed close;
    # its retest must happen on a later Daily candle.
    bob_start = max(start, ch - max(1, int(config.bob_lookback_days)))
    for j in range(bob_start, ch):
        if j == latest_ob_index:
            continue
        counter_candle = (
            float(data.Close.iloc[j]) < float(data.Open.iloc[j])
            if direction == 1 else float(data.Close.iloc[j]) > float(data.Open.iloc[j])
        )
        if not counter_candle:
            continue
        flip = next(
            (
                k for k in range(ch, end + 1)
                if (
                    float(data.Close.iloc[k]) > float(data.High.iloc[j])
                    if direction == 1 else float(data.Close.iloc[k]) < float(data.Low.iloc[j])
                )
            ),
            None,
        )
        if flip is not None:
            zones.append(_zone("BOB", data.Low.iloc[j], data.High.iloc[j], j, flip, flip_index=flip))

    zones.sort(key=lambda z: (z["available_index"], ZONE_PRIORITY[z["type"]], z["origin_index"]))
    return zones


def _zone_is_active(data: pd.DataFrame, zone: dict[str, Any], direction: int) -> bool:
    """A zone is active only while no completed close has invalidated its far edge."""
    for i in range(int(zone["available_index"]) + 1, len(data)):
        close = float(data.Close.iloc[i])
        if direction == 1 and close < float(zone["low"]):
            return False
        if direction == -1 and close > float(zone["high"]):
            return False
    return True


def _find_entry_in_zones(
    data: pd.DataFrame,
    zones: list[dict[str, Any]],
    direction: int,
    entry_valid_days: int,
) -> dict[str, Any] | None:
    """A zone must be touched, then confirmed by a directional Daily close within N bars."""
    entries: list[dict[str, Any]] = []
    valid_days = max(1, int(entry_valid_days))
    for zone in zones:
        touched_at = None
        for i in range(int(zone["available_index"]) + 1, len(data)):
            close, opened = float(data.Close.iloc[i]), float(data.Open.iloc[i])
            if direction == 1 and close < float(zone["low"]):
                break
            if direction == -1 and close > float(zone["high"]):
                break
            touched = float(data.Low.iloc[i]) <= float(zone["high"]) and float(data.High.iloc[i]) >= float(zone["low"])
            if touched and touched_at is None:
                touched_at = i
            if touched_at is not None and i - touched_at < valid_days:
                confirmed = (
                    close > opened and close > float(zone["high"])
                    if direction == 1 else close < opened and close < float(zone["low"])
                )
                if confirmed:
                    entries.append({"entry_index": i, "retest_index": touched_at, "zone": zone})
                    break
            elif touched_at is not None and i - touched_at >= valid_days:
                touched_at = i if touched else None

    if not entries:
        return None
    entries.sort(
        key=lambda x: (
            x["entry_index"], ZONE_PRIORITY[x["zone"]["type"]], x["zone"]["available_index"]
        )
    )
    first_index = entries[0]["entry_index"]
    same_bar = [x for x in entries if x["entry_index"] == first_index]
    zone_types = list(dict.fromkeys(x["zone"]["type"] for x in same_bar))
    primary = same_bar[0]
    return {
        "entry_index": first_index,
        "retest_index": primary["retest_index"],
        "zone": primary["zone"],
        "zone_types": zone_types,
    }


def scan_symbol(symbol: str, name: str, raw_data: pd.DataFrame, config: ScanConfig) -> dict[str, Any] | None:
    data = _normalise_ohlc(raw_data)
    now = pd.Timestamp.now(tz=ZoneInfo("Asia/Kolkata"))
    if not data.empty and data.index[-1].date() == now.date() and now.time() < dtime(15, 40):
        data = data.iloc[:-1]
    if len(data) < max(config.atr_length + 10, 80):
        return None
    ctx = _three_month_context(data)
    if ctx is None:
        return None

    direction = int(ctx["bias"])
    last = len(data) - 1
    entry = sl = np.nan
    sweep_date = entry_date = retest_date = choch_date = None
    zone_low = zone_high = np.nan
    entry_zone_type = ""
    available_zones: list[str] = []
    stage = 0
    zones: list[dict[str, Any]] = []
    target = ctx["m1_high"] if direction == 1 else (ctx["m1_low"] if direction == -1 else np.nan)
    target_status = "NOT READY"
    entry_status = "WAITING"

    if ctx["monthly_status"] == "AMBIGUOUS_BOTH_SIDES_SWEPT":
        stage = 6
    elif direction:
        m3_indices = np.flatnonzero(data.index >= ctx["m3_start"])
        if len(m3_indices):
            m3_start = int(m3_indices[0])
            highs = _confirmed_pivots(data.High, config.pivot_left, config.pivot_right, True)
            lows = _confirmed_pivots(data.Low, config.pivot_left, config.pivot_right, False)
            choch_index = None
            # A CHoCH must break a pivot that was itself confirmed during M3.
            # Do not reuse a stale swing level from a preceding month.
            first_choch_bar = max(m3_start + 1, m3_start + config.pivot_left + config.pivot_right)
            for i in range(first_choch_bar, last + 1):
                available = highs.iloc[m3_start:i].dropna() if direction == 1 else lows.iloc[m3_start:i].dropna()
                if available.empty:
                    continue
                level = float(available.iloc[-1])
                broken = (
                    float(data.Close.iloc[i]) > level
                    if direction == 1 else float(data.Close.iloc[i]) < level
                )
                if broken:
                    choch_index = i
                    break
            if choch_index is None:
                stage = 1
            else:
                choch_date = data.index[choch_index].date().isoformat()
                sweep_date = ctx["sweep_date"].date().isoformat() if ctx["sweep_date"] is not None else None
                stage = 2
                zones = _collect_entry_zones(data, m3_start, choch_index, last, direction, config)
                active_zones = [z for z in zones if _zone_is_active(data, z, direction)]
                available_zones = list(dict.fromkeys(z["type"] for z in active_zones))
                candidate = _find_entry_in_zones(data, active_zones, direction, config.entry_valid_days)
                if candidate is not None:
                    entry_index = int(candidate["entry_index"])
                    retest_index = int(candidate["retest_index"])
                    selected = candidate["zone"]
                    entry = float(data.Close.iloc[entry_index])
                    entry_date = data.index[entry_index].date().isoformat()
                    retest_date = data.index[retest_index].date().isoformat()
                    zone_low, zone_high = float(selected["low"]), float(selected["high"])
                    entry_zone_type = "+".join(candidate["zone_types"])
                    sl = float(ctx["sweep_low"]) if direction == 1 else float(ctx["sweep_high"])
                    stage = 3

    if stage == 3 and pd.notna(entry) and pd.notna(sl) and pd.notna(target):
        entry_ts = pd.Timestamp(entry_date)
        sweep_ts = pd.Timestamp(ctx["sweep_date"]) if ctx.get("sweep_date") is not None else pd.Timestamp(ctx["m2_start"])
        # Do not issue a fresh entry after the monthly target liquidity or the
        # sweep-candle stop has already been taken between the M2 sweep and entry.
        before_entry = data.loc[(data.index > sweep_ts) & (data.index <= entry_ts)]
        pre_entry_outcome = None
        for bar_time, bar in before_entry.iterrows():
            hit_target = float(bar["High"]) >= target if direction == 1 else float(bar["Low"]) <= target
            # Entry is at the confirming candle close; stop tests on that same
            # candle happened before entry, so only test SL on earlier candles.
            hit_stop = (
                float(bar["Low"]) <= sl if direction == 1 else float(bar["High"]) >= sl
            ) if bar_time < entry_ts else False
            if hit_target and hit_stop:
                pre_entry_outcome = "AMBIGUOUS"
                break
            if hit_target:
                pre_entry_outcome = "TARGET"
                break
            if hit_stop:
                pre_entry_outcome = "STOP"
                break

        if pre_entry_outcome == "TARGET":
            stage = 7
            target_status = "TARGET HIT BEFORE ENTRY"
            entry_status = "NOT TRIGGERED - TARGET ALREADY TAKEN"
        elif pre_entry_outcome == "STOP":
            stage = 8
            target_status = "STOP LOSS HIT BEFORE ENTRY"
            entry_status = "NOT TRIGGERED - SWEEP STOP ALREADY HIT"
        elif pre_entry_outcome == "AMBIGUOUS":
            stage = 6
            target_status = "AMBIGUOUS - SL AND TARGET TOUCHED BEFORE ENTRY"
            entry_status = "NOT TRIGGERED - AMBIGUOUS PRE-ENTRY CANDLE"
        elif (direction == 1 and entry >= target) or (direction == -1 and entry <= target):
            stage = 7
            target_status = "TARGET ALREADY PASSED AT ENTRY"
            entry_status = "NOT TRIGGERED - TARGET ALREADY TAKEN"
        else:
            entry_status = "TRIGGERED"
            target_status = "TARGET PENDING"
            # Only candles after the confirmation close can resolve this trade.
            for _, bar in data.loc[data.index > entry_ts].iterrows():
                hit_target = float(bar["High"]) >= target if direction == 1 else float(bar["Low"]) <= target
                hit_stop = float(bar["Low"]) <= sl if direction == 1 else float(bar["High"]) >= sl
                if hit_target and hit_stop:
                    stage, target_status = 6, "AMBIGUOUS (SL AND TARGET SAME CANDLE)"
                    break
                if hit_target:
                    stage, target_status = 4, "TARGET HIT"
                    break
                if hit_stop:
                    stage, target_status = 5, "STOP LOSS HIT"
                    break

    bias = "Bullish" if direction == 1 else ("Bearish" if direction == -1 else "Neutral")
    if stage == 3:
        setup = "BUY" if direction == 1 else "SELL"
        entry_status = "TRIGGERED"
    elif stage == 1:
        setup = "Wait CHoCH"
    elif stage == 2:
        setup = "Wait Retest" if available_zones else "Wait FVG/IFVG/OB/BOB"
    elif stage == 4:
        setup = "Target Hit"
    elif stage == 5:
        setup = "Stop Loss Hit"
    elif stage == 6:
        setup = "Ambiguous"
        if target_status == "NOT READY":
            target_status = "AMBIGUOUS MONTHLY SWEEP OR SAME-CANDLE SL/TARGET"
    elif stage == 7:
        setup = "Target Hit Before Entry"
    elif stage == 8:
        setup = "Stop Loss Hit Before Entry"
    else:
        setup = "No Valid Monthly Sweep"

    return {
        "Symbol": symbol, "Name": name, "Bias": bias, "Stage": stage, "Setup": setup,
        "LTP": float(data.Close.iloc[-1]), "Entry": entry, "Entry Status": entry_status,
        "Entry Zone Type": entry_zone_type, "Available Entry Zones": ", ".join(available_zones),
        "SL": sl,
        "T1 (2R)": (
            entry + 2 * (entry - sl) if direction == 1 and pd.notna(entry) and pd.notna(sl)
            else entry - 2 * (sl - entry) if direction == -1 and pd.notna(entry) and pd.notna(sl)
            else np.nan
        ),
        "Target (M1 Monthly H/L)": target, "Target Status": target_status,
        "Monthly Status": ctx["monthly_status"],
        "Invalidation": ctx["m1_low"] if direction == 1 else (ctx["m1_high"] if direction == -1 else np.nan),
        "M1 High": ctx["m1_high"], "M1 Low": ctx["m1_low"],
        "M2 High": ctx["m2_high"], "M2 Low": ctx["m2_low"], "M2 Close": ctx["m2_close"],
        "M1 Month": ctx["m1_period"], "M2 Month": ctx["m2_period"], "M3 Month": ctx["m3_period"],
        "Sweep Date": sweep_date, "Sweep Candle High": ctx.get("sweep_high", np.nan),
        "Sweep Candle Low": ctx.get("sweep_low", np.nan), "CHoCH Date": choch_date,
        "Retest Date": retest_date, "Entry Date": entry_date,
        "Zone Low": zone_low, "Zone High": zone_high,
        "Last Candle": data.index[-1].date().isoformat(),
    }
