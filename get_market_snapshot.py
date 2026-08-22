#!/usr/bin/env python3
"""Descarga velas multi-timeframe y calcula los indicadores de la checklist.

Puerto 1:1 de Get-MarketSnapshot.ps1 para que el motor corra tambien fuera de
Windows (sesiones cloud, macOS, Linux). Mismo JSON de salida, mismo resumen.

Fuente: OKX (publica, sin API key). Solo libreria estandar: nada que instalar.

Uso:
  python3 get_market_snapshot.py --inst-id ETH-USDT
"""
import argparse
import json
import math
import re
import sys
import urllib.request
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

NAN = float("nan")


def isnan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


# ---------------------------------------------------------------- data fetch
def get_okx_candles(inst_id, bar, limit=300):
    url = ("https://www.okx.com/api/v5/market/candles"
           "?instId=%s&bar=%s&limit=%d" % (inst_id, bar, limit))
    req = urllib.request.Request(url, headers={"User-Agent": "claude-code-trade-check"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        r = json.loads(resp.read().decode("utf-8"))
    if r.get("code") != "0":
        raise RuntimeError("OKX error (%s): %s" % (bar, r.get("msg")))
    if not r.get("data"):
        raise RuntimeError("OKX sin datos para %s" % bar)
    out = []
    for row in r["data"]:
        out.append({
            "t": float(row[0]), "o": float(row[1]), "h": float(row[2]),
            "l": float(row[3]), "c": float(row[4]), "v": float(row[5]),
            "confirm": int(row[8]),
        })
    out.reverse()
    return out


# ---------------------------------------------------------------- indicators
def sma(src, length):
    n = len(src)
    out = [NAN] * n
    for i in range(n):
        if i < length - 1:
            continue
        out[i] = sum(src[i - length + 1:i + 1]) / length
    return out


def ema(src, length):
    n = len(src)
    out = [NAN] * n
    k = 2.0 / (length + 1)
    s = 0.0
    for i in range(n):
        if i < length - 1:
            s += src[i]
        elif i == length - 1:
            s += src[i]
            out[i] = s / length
        else:
            out[i] = (src[i] - out[i - 1]) * k + out[i - 1]
    return out


def rma(src, length):
    n = len(src)
    out = [NAN] * n
    s = 0.0
    for i in range(n):
        if i < length - 1:
            s += src[i]
        elif i == length - 1:
            s += src[i]
            out[i] = s / length
        else:
            out[i] = (out[i - 1] * (length - 1) + src[i]) / length
    return out


def stdev_pop(src, length):
    n = len(src)
    out = [NAN] * n
    for i in range(n):
        if i < length - 1:
            continue
        win = src[i - length + 1:i + 1]
        m = sum(win) / length
        out[i] = math.sqrt(sum((v - m) ** 2 for v in win) / length)
    return out


def true_range(candles):
    n = len(candles)
    tr = [0.0] * n
    tr[0] = candles[0]["h"] - candles[0]["l"]
    for i in range(1, n):
        a = candles[i]["h"] - candles[i]["l"]
        b = abs(candles[i]["h"] - candles[i - 1]["c"])
        d = abs(candles[i]["l"] - candles[i - 1]["c"])
        tr[i] = max(a, b, d)
    return tr


def adx_calc(candles, length=14):
    n = len(candles)
    tr = true_range(candles)
    pdm = [0.0] * n
    mdm = [0.0] * n
    for i in range(1, n):
        up = candles[i]["h"] - candles[i - 1]["h"]
        dn = candles[i - 1]["l"] - candles[i]["l"]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        mdm[i] = dn if (dn > up and dn > 0) else 0.0

    s_tr = rma(tr, length)
    s_pd = rma(pdm, length)
    s_md = rma(mdm, length)

    dip = [NAN] * n
    dim = [NAN] * n
    dx = [NAN] * n
    for i in range(n):
        if isnan(s_tr[i]) or s_tr[i] == 0:
            continue
        dip[i] = 100.0 * s_pd[i] / s_tr[i]
        dim[i] = 100.0 * s_md[i] / s_tr[i]
        total = dip[i] + dim[i]
        dx[i] = 0.0 if total == 0 else 100.0 * abs(dip[i] - dim[i]) / total

    adx = [NAN] * n
    start = -1
    for i in range(n):
        if not isnan(dx[i]):
            start = i
            break
    if start >= 0 and (start + length) <= n:
        adx[start + length - 1] = sum(dx[start:start + length]) / length
        for i in range(start + length, n):
            adx[i] = (adx[i - 1] * (length - 1) + dx[i]) / length
    return {"adx": adx, "diPlus": dip, "diMinus": dim, "atr": rma(tr, length)}


def linreg(src, length):
    n = len(src)
    out = [NAN] * n
    sx = sum(range(length))
    sxx = sum(x * x for x in range(length))
    den = length * sxx - sx * sx
    for i in range(n):
        if i < length - 1:
            continue
        sy = 0.0
        sxy = 0.0
        for x in range(length):
            y = src[i - length + 1 + x]
            sy += y
            sxy += x * y
        b = 0.0 if den == 0 else (length * sxy - sx * sy) / den
        a = (sy - b * sx) / length
        out[i] = a + b * (length - 1)
    return out


def squeeze(candles, length=20, mult=2.0, len_kc=20, mult_kc=1.5):
    n = len(candles)
    close = [c["c"] for c in candles]
    high = [c["h"] for c in candles]
    low = [c["l"] for c in candles]

    basis = sma(close, length)
    dev = stdev_pop(close, length)
    tr = true_range(candles)
    tr_ma = sma(tr, len_kc)
    ma = sma(close, len_kc)

    on = [False] * n
    off = [False] * n
    for i in range(n):
        if isnan(basis[i]) or isnan(tr_ma[i]):
            continue
        ub = basis[i] + mult * dev[i]
        lb = basis[i] - mult * dev[i]
        uk = ma[i] + mult_kc * tr_ma[i]
        lk = ma[i] - mult_kc * tr_ma[i]
        on[i] = (lb > lk and ub < uk)
        off[i] = (lb < lk and ub > uk)

    src = [NAN] * n
    for i in range(n):
        if i < len_kc - 1:
            continue
        hh = max(high[i - len_kc + 1:i + 1])
        ll = min(low[i - len_kc + 1:i + 1])
        src[i] = close[i] - (((hh + ll) / 2.0) + ma[i]) / 2.0
    return {"val": linreg(src, len_kc), "sqzOn": on, "sqzOff": off}


def volume_profile(candles, lookback=120, bins=60):
    frm = max(0, len(candles) - lookback)
    sl = candles[frm:]
    lo_p = min(c["l"] for c in sl)
    hi_p = max(c["h"] for c in sl)
    if hi_p <= lo_p:
        return None
    bw = (hi_p - lo_p) / bins
    vol = [0.0] * bins
    for c in sl:
        lo = int(math.floor((c["l"] - lo_p) / bw))
        hi = int(math.floor((c["h"] - lo_p) / bw))
        lo = max(lo, 0)
        hi = min(hi, bins - 1)
        span = hi - lo + 1
        for b in range(lo, hi + 1):
            vol[b] += c["v"] / span
    total = sum(vol)
    poc = 0
    for b in range(1, bins):
        if vol[b] > vol[poc]:
            poc = b

    acc = vol[poc]
    lo = hi = poc
    while acc < 0.70 * total and (lo > 0 or hi < bins - 1):
        v_lo = vol[lo - 1] if lo > 0 else -1.0
        v_hi = vol[hi + 1] if hi < bins - 1 else -1.0
        if v_hi >= v_lo:
            hi += 1
            acc += vol[hi]
        else:
            lo -= 1
            acc += vol[lo]
    return {
        "poc": round(lo_p + (poc + 0.5) * bw, 2),
        "vah": round(lo_p + (hi + 1) * bw, 2),
        "val": round(lo_p + lo * bw, 2),
        "low": round(lo_p, 2),
        "high": round(hi_p, 2),
        "lookback": len(sl),
    }


def swing_levels(candles, left=2, right=2, lookback=60):
    n = len(candles)
    frm = max(left, n - lookback)
    hs = []
    ls = []
    for i in range(frm, n - right):
        is_h = True
        is_l = True
        for j in range(i - left, i + right + 1):
            if j == i:
                continue
            if candles[j]["h"] >= candles[i]["h"]:
                is_h = False
            if candles[j]["l"] <= candles[i]["l"]:
                is_l = False
        if is_h:
            hs.append(round(candles[i]["h"], 2))
        if is_l:
            ls.append(round(candles[i]["l"], 2))
    return {"lastSwingHighs": hs[-4:], "lastSwingLows": ls[-4:]}


def _mom_run(val, candles, frm, to, sign):
    peak = 0.0
    peak_idx = frm
    for k in range(frm, to + 1):
        if isnan(val[k]):
            continue
        if abs(val[k]) > abs(peak):
            peak = val[k]
            peak_idx = k
    hi = max(candles[k]["h"] for k in range(frm, to + 1))
    lo = min(candles[k]["l"] for k in range(frm, to + 1))
    return {"sign": sign, "from": frm, "to": to, "peak": peak, "peakIdx": peak_idx,
            "priceHigh": hi, "priceLow": lo, "barras": to - frm + 1}


def _r(x, digits=2):
    """Round como [Math]::Round de .NET (half-to-even); None si NaN."""
    if x is None or isnan(x):
        return None
    return round(x, digits)


# Estructura del histograma de momentum: tramos del mismo signo ("valles"/"lomos"),
# tamano del tramo actual contra el anterior, y divergencias precio/momentum.
# Esto es lo que permite detectar patrones de SALIDA, no solo de entrada.
def momentum_structure(val, candles, serie=24):
    n = len(val)
    i = n - 1
    runs = []
    sign = 0
    start = -1
    for k in range(n):
        if isnan(val[k]):
            continue
        s = sign
        if val[k] > 0:
            s = 1
        elif val[k] < 0:
            s = -1
        if sign == 0:
            sign = s
            start = k
            continue
        if s != sign:
            runs.append(_mom_run(val, candles, start, k - 1, sign))
            sign = s
            start = k
    if start >= 0 and sign != 0:
        runs.append(_mom_run(val, candles, start, i, sign))

    hist = [_r(val[k]) for k in range(max(0, n - serie), i + 1)]

    cur = runs[-1] if runs else None
    prev_same = None
    if cur:
        for k in range(len(runs) - 2, -1, -1):
            if runs[k]["sign"] == cur["sign"]:
                prev_same = runs[k]
                break

    pend3 = None
    if i >= 3 and not isnan(val[i]) and not isnan(val[i - 3]):
        pend3 = round(val[i] - val[i - 3], 2)

    # "Girando" = el pico del tramo ya quedo atras y la pendiente se dio la vuelta.
    # Es la condicion de salida anticipada: no se espera a que la divergencia confirme.
    girando = False
    desde_pico = None
    if cur:
        desde_pico = i - cur["peakIdx"]
        if pend3 is not None:
            if cur["sign"] == 1:
                girando = (desde_pico >= 2 and pend3 < 0)
            if cur["sign"] == -1:
                girando = (desde_pico >= 2 and pend3 > 0)

    # Divergencia: precio hace extremo mas extremo, el momentum no acompana.
    # Solo cuenta si el tramo implicado es reciente (<= 3 velas de distancia).
    div_baj = False
    div_alc = False
    pos = [r for r in runs if r["sign"] == 1]
    if len(pos) >= 2:
        a, b = pos[-1], pos[-2]
        div_baj = (a["to"] >= i - 3 and a["priceHigh"] > b["priceHigh"] and a["peak"] < b["peak"])
    neg = [r for r in runs if r["sign"] == -1]
    if len(neg) >= 2:
        a, b = neg[-1], neg[-2]
        div_alc = (a["to"] >= i - 3 and a["priceLow"] < b["priceLow"]
                   and abs(a["peak"]) < abs(b["peak"]))

    pct_vs_prev = None
    if cur and prev_same and abs(prev_same["peak"]) > 0:
        pct_vs_prev = round(100.0 * abs(cur["peak"]) / abs(prev_same["peak"]))

    return {
        "serie": hist,
        "pendiente3": pend3,
        "signoTramo": cur["sign"] if cur else 0,
        "barrasTramo": cur["barras"] if cur else None,
        "picoTramo": _r(cur["peak"]) if cur else None,
        "picoPrevio": _r(prev_same["peak"]) if prev_same else None,
        "picoVsPrevioPct": pct_vs_prev,
        "barrasDesdePico": desde_pico,
        "girando": girando,
        "divergenciaBajista": div_baj,
        "divergenciaAlcista": div_alc,
    }


# Cuantas veces el precio cruzo la EMA55 en las ultimas N velas.
# Muchos cruces = lateral: ahi el cruce de medias no significa nada.
def cruces_ema(close, ema_vals, lookback=20):
    n = len(close)
    c = 0
    for k in range(max(1, n - lookback), n):
        if isnan(ema_vals[k]) or isnan(ema_vals[k - 1]):
            continue
        a = close[k - 1] - ema_vals[k - 1]
        b = close[k] - ema_vals[k]
        if (a > 0 and b < 0) or (a < 0 and b > 0):
            c += 1
    return c


# ---------------------------------------------------------------- per-TF calc
def timeframe_report(candles, label, range_lookback=30, vp_lookback=120):
    n = len(candles)
    live_open = (candles[n - 1]["confirm"] == 0)
    # Los indicadores se calculan sobre velas CERRADAS: la vela viva miente.
    closed = candles[:n - 1] if live_open else candles
    m = len(closed)

    close = [c["c"] for c in closed]

    ema10 = ema(close, 10)
    ema21 = ema(close, 21)
    ema55 = ema(close, 55)
    adx_r = adx_calc(closed, 14)
    sqz = squeeze(closed)
    vp = volume_profile(closed, vp_lookback, 60)
    sw = swing_levels(closed, 2, 2, 60)

    i = m - 1
    rl = min(range_lookback, m)
    sl = closed[m - rl:m]
    r_high = max(c["h"] for c in sl)
    r_low = min(c["l"] for c in sl)
    last_c = closed[i]["c"]
    pos = 100.0 * (last_c - r_low) / (r_high - r_low) if r_high > r_low else 50.0

    sqz_bars = 0
    for k in range(i, -1, -1):
        if sqz["sqzOn"][k]:
            sqz_bars += 1
        else:
            break

    mom_now = sqz["val"][i]
    mom_prev = sqz["val"][i - 1] if i >= 1 else NAN
    adx_now = adx_r["adx"][i]
    adx_prev = adx_r["adx"][i - 5] if i >= 5 else NAN
    mom = momentum_structure(sqz["val"], closed, 24)
    cruces = cruces_ema(close, ema55, 20)

    # Estrechamiento de medias: la separacion EMA10/EMA55 encogiendose precede al giro
    # de tendencia. Es la unica excepcion que permite operar cerca de una resistencia.
    j5 = max(0, i - 5)
    if isnan(ema10[i]) or isnan(ema55[i]) or ema55[i] == 0:
        sep_ahora = NAN
    else:
        sep_ahora = 100.0 * abs(ema10[i] - ema55[i]) / ema55[i]
    if isnan(ema10[j5]) or isnan(ema55[j5]) or ema55[j5] == 0:
        sep_hace5 = NAN
    else:
        sep_hace5 = 100.0 * abs(ema10[j5] - ema55[j5]) / ema55[j5]
    estrechando = ((not isnan(sep_ahora)) and (not isnan(sep_hace5))
                   and (sep_ahora < sep_hace5))

    def pend5():
        if isnan(ema55[i]) or isnan(ema55[j5]):
            return NAN
        return ema55[i] - ema55[j5]

    def precio_vs_ema55():
        if isnan(ema55[i]) or ema55[i] == 0:
            return NAN
        return 100.0 * (last_c - ema55[i]) / ema55[i]

    def atr_pct():
        if isnan(adx_r["atr"][i]) or last_c == 0:
            return NAN
        return 100.0 * adx_r["atr"][i] / last_c

    ts = datetime.fromtimestamp(closed[i]["t"] / 1000.0, tz=timezone.utc)

    return OrderedDict([
        ("timeframe", label),
        ("velasCerradas", m),
        ("ultimoCierre", _r(last_c)),
        ("fechaUltimoCierre", ts.strftime("%Y-%m-%d %H:%M") + " UTC"),
        ("ema10", _r(ema10[i])),
        ("ema21", _r(ema21[i])),
        ("ema55", _r(ema55[i])),
        ("ema10SobreEma55", (not isnan(ema10[i])) and (not isnan(ema55[i]))
         and ema10[i] > ema55[i]),
        ("ema55Pendiente5", _r(pend5())),
        ("precioVsEma55Pct", _r(precio_vs_ema55())),
        ("emaSeparacionPct", _r(sep_ahora)),
        ("emaSeparacionPctHace5", _r(sep_hace5)),
        ("emaEstrechandose", estrechando),
        ("adx", _r(adx_now)),
        ("adxHace5", _r(adx_prev)),
        ("adxSubiendo", (not isnan(adx_now)) and (not isnan(adx_prev)) and adx_now > adx_prev),
        ("diPlus", _r(adx_r["diPlus"][i])),
        ("diMinus", _r(adx_r["diMinus"][i])),
        ("atr14", _r(adx_r["atr"][i])),
        ("atrPct", _r(atr_pct())),
        ("squeezeComprimido", bool(sqz["sqzOn"][i])),
        ("squeezeBarrasComprimido", sqz_bars),
        ("momentum", _r(mom_now)),
        ("momentumPrev", _r(mom_prev)),
        ("momentumExpandiendo", (not isnan(mom_now)) and (not isnan(mom_prev))
         and abs(mom_now) > abs(mom_prev)),
        ("momentumSerie", mom["serie"]),
        ("momentumPendiente3", mom["pendiente3"]),
        ("momentumSignoTramo", mom["signoTramo"]),
        ("momentumBarrasTramo", mom["barrasTramo"]),
        ("momentumPicoTramo", mom["picoTramo"]),
        ("momentumPicoPrevio", mom["picoPrevio"]),
        ("momentumPicoVsPrevioPct", mom["picoVsPrevioPct"]),
        ("momentumBarrasDesdePico", mom["barrasDesdePico"]),
        ("momentumGirando", mom["girando"]),
        ("divergenciaBajista", mom["divergenciaBajista"]),
        ("divergenciaAlcista", mom["divergenciaAlcista"]),
        ("crucesEma55Ultimas20", cruces),
        ("rangoLookback", rl),
        ("rangoAlto", _r(r_high)),
        ("rangoBajo", _r(r_low)),
        ("posicionEnRangoPct", _r(pos)),
        ("poc", vp["poc"] if vp else None),
        ("valueAreaAlto", vp["vah"] if vp else None),
        ("valueAreaBajo", vp["val"] if vp else None),
        ("swingHighs", sw["lastSwingHighs"]),
        ("swingLows", sw["lastSwingLows"]),
        ("velaVivaAbierta", live_open),
    ])


# ---------------------------------------------------------------- main
TFS = [
    {"bar": "1Dutc", "label": "Diario", "range": 30, "vp": 60},
    {"bar": "4H", "label": "4h", "range": 42, "vp": 168},
    {"bar": "1H", "label": "1h", "range": 48, "vp": 168},
]


def main():
    ap = argparse.ArgumentParser(description="Snapshot de mercado multi-timeframe.")
    ap.add_argument("--inst-id", "-i", default="ETH-USDT")
    ap.add_argument("--out-file", "-o", default="")
    ap.add_argument("--limit", "-l", type=int, default=300)
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    now = datetime.now()
    report = OrderedDict([
        ("activo", args.inst_id),
        ("generadoUtc", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + " UTC"),
        ("generadoLocal", now.strftime("%Y-%m-%d %H:%M:%S")),
        ("fuente", "OKX (api.okx.com, publico)"),
        ("precioActual", None),
        ("timeframes", OrderedDict()),
    ])

    for tf in TFS:
        candles = get_okx_candles(args.inst_id, tf["bar"], args.limit)
        report["timeframes"][tf["label"]] = timeframe_report(
            candles, tf["label"], tf["range"], tf["vp"])
        if tf["bar"] == "1H":
            report["precioActual"] = round(candles[-1]["c"], 2)

    out_file = args.out_file
    if not out_file:
        root = Path(__file__).resolve().parents[4]
        d = root / "data" / "snapshots"
        d.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9]", "", args.inst_id)
        out_file = str(d / ("snapshot-%s-%s.json" % (stem, now.strftime("%Y%m%d-%H%M"))))

    text = json.dumps(report, indent=2, ensure_ascii=False)
    with open(out_file, "w", encoding="utf-8") as fh:
        fh.write(text)

    if args.json_only:
        print(text)
        return 0

    # ------------------------------------------------------ resumen humano
    print("=" * 68)
    print("  SNAPSHOT %s   precio ahora: %s" % (report["activo"], report["precioActual"]))
    print("  %s   (local: %s)" % (report["generadoUtc"], report["generadoLocal"]))
    print("  json: %s" % out_file)
    print("=" * 68)
    for t in report["timeframes"].values():
        print("")
        print("--- %s ---  ultimo cierre %s @ %s"
              % (t["timeframe"], t["fechaUltimoCierre"], t["ultimoCierre"]))
        print("  EMA    10=%s  21=%s  55=%s   10>55: %s   pendEMA55(5)=%s"
              % (t["ema10"], t["ema21"], t["ema55"], t["ema10SobreEma55"], t["ema55Pendiente5"]))
        print("  EMASEP separacion 10/55: %s%%  (hace 5: %s%%)   estrechandose: %s"
              % (t["emaSeparacionPct"], t["emaSeparacionPctHace5"], t["emaEstrechandose"]))
        print("  ADX    %s  (hace 5: %s, subiendo: %s)   DI+=%s  DI-=%s"
              % (t["adx"], t["adxHace5"], t["adxSubiendo"], t["diPlus"], t["diMinus"]))
        print("  ATR    %s  (%s%% del precio)" % (t["atr14"], t["atrPct"]))
        print("  SQZ    comprimido: %s (%s velas)   mom=%s prev=%s  expandiendo: %s"
              % (t["squeezeComprimido"], t["squeezeBarrasComprimido"], t["momentum"],
                 t["momentumPrev"], t["momentumExpandiendo"]))
        print("  MOM    tramo %s (%s velas)  pico=%s  previo=%s (%s%%)  pend3=%s  "
              "desdePico=%s  girando: %s"
              % (t["momentumSignoTramo"], t["momentumBarrasTramo"], t["momentumPicoTramo"],
                 t["momentumPicoPrevio"], t["momentumPicoVsPrevioPct"], t["momentumPendiente3"],
                 t["momentumBarrasDesdePico"], t["momentumGirando"]))
        print("  DIVERG bajista: %s   alcista: %s   cruces EMA55 (20 velas): %s"
              % (t["divergenciaBajista"], t["divergenciaAlcista"], t["crucesEma55Ultimas20"]))
        print("  RANGO  %s - %s  (%s velas)   posicion: %s%%"
              % (t["rangoBajo"], t["rangoAlto"], t["rangoLookback"], t["posicionEnRangoPct"]))
        print("  VP     POC=%s   VA=[%s - %s]"
              % (t["poc"], t["valueAreaBajo"], t["valueAreaAlto"]))
        print("  SWING  highs: %s   lows: %s"
              % (", ".join(str(x) for x in t["swingHighs"]),
                 ", ".join(str(x) for x in t["swingLows"])))
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
