"""Core, unit-tested helpers for the Ramadan price-surge analysis.

All functions are pure: they return new objects and never mutate inputs.
Monthly series use a month-start DatetimeIndex (freq "MS").
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
from convertdate import islamic
from hijridate import Gregorian, Hijri

RAMADAN = 9
SHAWWAL = 10


# --------------------------------------------------------------------------
# Ramadan calendar
# --------------------------------------------------------------------------
def ramadan_dates(hijri_year: int, calendar: str = "ummalqura",
                  offset_days: int = 0) -> tuple[dt.date, dt.date]:
    """First and last Gregorian day of Ramadan for a Hijri year.

    calendar="ummalqura" uses hijridate (Saudi Umm al-Qura tables);
    calendar="arithmetic" uses convertdate's tabular Islamic calendar.
    offset_days shifts both ends (Bangladesh often starts one day later).
    """
    if calendar == "ummalqura":
        start = Hijri(hijri_year, RAMADAN, 1).to_gregorian()
        shawwal = Hijri(hijri_year, SHAWWAL, 1).to_gregorian()
    elif calendar == "arithmetic":
        start = dt.date(*islamic.to_gregorian(hijri_year, RAMADAN, 1))
        shawwal = dt.date(*islamic.to_gregorian(hijri_year, SHAWWAL, 1))
    else:
        raise ValueError(f"unknown calendar: {calendar!r}")
    shift = dt.timedelta(days=offset_days)
    return start + shift, shawwal - dt.timedelta(days=1) + shift


def days_by_month(start: dt.date, end: dt.date) -> dict[pd.Timestamp, int]:
    """Number of days of [start, end] falling in each calendar month."""
    if end < start:
        raise ValueError("end must not be before start")
    days = pd.date_range(start, end, freq="D")
    counts = days.to_period("M").value_counts().sort_index()
    return {p.to_timestamp(): int(n) for p, n in counts.items()}


def ramadan_calendar(first_year: int, last_year: int, calendar: str = "ummalqura",
                     offset_days: int = 0, marginal_share: float = 0.6) -> pd.DataFrame:
    """One row per Ramadan whose start falls in [first_year, last_year] (Gregorian).

    flag_month  = calendar month holding the most Ramadan days (ties: earlier month)
    flag_share  = share of Ramadan days inside the flag month
    marginal    = flag_share < marginal_share (Ramadan split almost evenly)
    baseline_m1/m2 = the two calendar months before the month in which Ramadan starts
    """
    h_first = Gregorian(first_year, 1, 1).to_hijri().year - 1
    h_last = Gregorian(last_year, 12, 31).to_hijri().year + 1
    rows = []
    for hy in range(h_first, h_last + 1):
        start, end = ramadan_dates(hy, calendar, offset_days)
        if not first_year <= start.year <= last_year:
            continue
        counts = days_by_month(start, end)
        flag = max(counts, key=lambda m: (counts[m], -m.value))
        n_days = sum(counts.values())
        start_month = pd.Timestamp(start.year, start.month, 1)
        rows.append({
            "hijri_year": hy,
            "gregorian_year": start.year,
            "start": pd.Timestamp(start),
            "end": pd.Timestamp(end),
            "n_days": n_days,
            "start_month": start_month,
            "flag_month": flag,
            "flag_days": counts[flag],
            "flag_share": counts[flag] / n_days,
            "marginal": counts[flag] / n_days < marginal_share,
            "baseline_m1": start_month - pd.DateOffset(months=2),
            "baseline_m2": start_month - pd.DateOffset(months=1),
        })
    return pd.DataFrame(rows)


def ramadan_day_share(index: pd.DatetimeIndex, cal: pd.DataFrame) -> pd.Series:
    """Fraction of each month's days that are Ramadan days."""
    share = pd.Series(0.0, index=index)
    for _, r in cal.iterrows():
        for month, n in days_by_month(r["start"].date(), r["end"].date()).items():
            if month in share.index:
                share.loc[month] = n / month.days_in_month
    return share


# --------------------------------------------------------------------------
# Cleaning
# --------------------------------------------------------------------------
def fill_short_gaps(s: pd.Series, max_gap: int = 2) -> tuple[pd.Series, pd.DataFrame]:
    """Fill interior NaN runs of length <= max_gap.

    A single missing month is the mean of its two neighbours; a run of two
    is linearly interpolated between its neighbours. Longer runs and gaps
    at either end are left missing. Returns (filled copy, log of filled cells).
    """
    out = s.copy()
    log = []
    isna = s.isna().to_numpy()
    i, n = 0, len(s)
    while i < n:
        if not isna[i]:
            i += 1
            continue
        j = i
        while j < n and isna[j]:
            j += 1
        run = j - i
        interior = i > 0 and j < n
        if interior and run <= max_gap:
            left, right = s.iloc[i - 1], s.iloc[j]
            for k in range(run):
                w = (k + 1) / (run + 1)
                val = left + w * (right - left)
                out.iloc[i + k] = val
                log.append({"date": s.index[i + k], "gap_length": run,
                            "left": left, "right": right, "filled": val,
                            "method": "neighbour mean" if run == 1 else "linear interpolation"})
        i = j
    return out, pd.DataFrame(log, columns=["date", "gap_length", "left", "right", "filled", "method"])


def flag_spikes(s: pd.Series, threshold: float = 0.25, revert_tol: float = 0.10,
                max_len: int = 3) -> pd.Series:
    """Flag spike-and-revert runs that look like recording errors.

    A run of 1..max_len observed months is flagged when every month in it
    differs from the last observation before the run by more than `threshold`
    in log terms, all in the same direction, and the first observation after
    the run is back within `revert_tol` (log) of the pre-run level.
    Genuine level shifts (no reversion) are never flagged.
    """
    x = np.log(s.dropna())
    flags = pd.Series(False, index=s.index)
    vals, idx = x.to_numpy(), x.index
    i = 1
    while i < len(vals):
        hit = False
        for k in range(1, max_len + 1):
            if i + k >= len(vals):
                break
            dev = vals[i:i + k] - vals[i - 1]
            same_sign = np.all(dev > threshold) or np.all(dev < -threshold)
            if same_sign and abs(vals[i + k] - vals[i - 1]) < revert_tol:
                flags.loc[idx[i:i + k]] = True
                i, hit = i + k, True
                break
        i += 0 if hit else 1
    return flags


def flag_panel_errors(panel: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """Confirm spike-and-revert candidates against the other markets.

    A candidate run (flag_spikes) in one market is kept as a suspected
    recording error only if, over the same months, the median log move of
    the other markets (relative to the month before the run) is less than
    half of this market's move, in the same direction. Nationwide moves,
    such as a real Ramadan surge, are therefore never removed; peer moves in
    the opposite direction count as not moving. Returns a boolean frame.
    """
    logp = np.log(panel)
    out = pd.DataFrame(False, index=panel.index, columns=panel.columns)
    for col in panel.columns:
        cand = flag_spikes(panel[col], **kwargs)
        if not cand.any():
            continue
        anchors = panel[col].dropna().index.difference(cand[cand].index)
        for t in cand[cand].index:
            prev = anchors[anchors < t].max()
            own = logp.at[t, col] - logp.at[prev, col]
            others = (logp.loc[t].drop(col) - logp.loc[prev].drop(col)).dropna()
            same_way = others.median() * np.sign(own) if not others.empty else 0.0
            if same_way < abs(own) / 2:
                out.at[t, col] = True
    return out


def longest_complete_window(s: pd.Series) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Start and end of the longest run without missing values."""
    best, cur_start, best_len = (None, None), None, 0
    for t, v in s.items():
        if pd.isna(v):
            cur_start = None
            continue
        cur_start = t if cur_start is None else cur_start
        length = len(s.loc[cur_start:t])
        if length > best_len:
            best, best_len = (cur_start, t), length
    return best


def chained_index(panel: pd.DataFrame, min_matched: int = 2, max_bridge: int | None = 3) -> pd.DataFrame:
    """Matched-market chained geometric-mean (Jevons) index.

    panel: wide frame, month-start index, one column per market, prices.
    The log change at month t is the mean log price change over markets
    observed both at t and at the most recent earlier month s (t-s <= max_bridge)
    that already has an index value; at least min_matched markets are needed.
    max_bridge=None links across gaps of any length (gap months stay NaN).
    Months that cannot be linked get NaN. Returns index (first valid month = 1),
    the number of matched markets and the bridged lag.
    """
    logp = np.log(panel)
    months = list(panel.index)
    first = next((i for i, m in enumerate(months) if logp.loc[m].notna().sum() >= min_matched), None)
    if first is None:
        raise ValueError("no month has enough markets to start the index")
    level = {months[first]: 0.0}
    rows = [{"month": months[first], "log_index": 0.0, "n_matched": int(logp.iloc[first].notna().sum()), "lag": 0}]
    for i in range(first + 1, len(months)):
        t = months[i]
        for lag in range(1, (max_bridge or i) + 1):
            s = months[i - lag] if i - lag >= 0 else None
            if s is None or s not in level:
                continue
            both = logp.loc[t].notna() & logp.loc[s].notna()
            if both.sum() >= min_matched:
                level[t] = level[s] + float((logp.loc[t, both] - logp.loc[s, both]).mean())
                rows.append({"month": t, "log_index": level[t], "n_matched": int(both.sum()), "lag": lag})
                break
        else:
            rows.append({"month": t, "log_index": np.nan, "n_matched": 0, "lag": np.nan})
    out = pd.DataFrame(rows).set_index("month").reindex(panel.index)
    out["index"] = np.exp(out["log_index"])
    return out


def chain_link(old: pd.Series, new: pd.Series, overlap: list[pd.Timestamp]) -> tuple[pd.Series, float]:
    """Join two series: old up to its end, new rescaled by mean(old/new) on overlap."""
    ratios = [old[m] / new[m] for m in overlap
              if m in old.index and m in new.index and pd.notna(old[m]) and pd.notna(new[m])]
    if not ratios:
        raise ValueError("no overlapping months to link on")
    k = float(np.mean(ratios))
    cut = old.dropna().index.max()
    joined = pd.concat([old.loc[:cut], new.loc[new.index > cut] * k])
    return joined, k


# --------------------------------------------------------------------------
# Decomposition
# --------------------------------------------------------------------------
def centered_ma(s: pd.Series, period: int = 12) -> pd.Series:
    """2 x period centered moving average (period even)."""
    if period % 2:
        return s.rolling(period, center=True).mean()
    weights = np.r_[0.5, np.ones(period - 1), 0.5] / period
    return s.rolling(period + 1, center=True).apply(lambda x: float(x @ weights), raw=True)


def ratio_to_cma(s: pd.Series, period: int = 12) -> pd.DataFrame:
    """Manual multiplicative decomposition by ratio to centered moving average.

    Missing months are tolerated: the moving average is undefined wherever its
    window touches a gap, and the seasonal indices average the remaining ratios.
    """
    trend = centered_ma(s, period)
    ratio = s / trend
    pos = np.arange(len(s)) % period
    raw_idx = pd.Series(ratio.to_numpy()).groupby(pos).mean()
    if raw_idx.isna().any():
        raise ValueError("a calendar month has no usable ratio; series too short or too gappy")
    idx = raw_idx / raw_idx.mean()
    seasonal = pd.Series(idx.to_numpy()[pos], index=s.index)
    return pd.DataFrame({"observed": s, "trend": trend, "seasonal": seasonal,
                         "resid": s / (trend * seasonal)})


# --------------------------------------------------------------------------
# Surges
# --------------------------------------------------------------------------
def surge_table(prices: pd.DataFrame, cal: pd.DataFrame) -> pd.DataFrame:
    """Surge% = price(flag month) / mean(price in the two baseline months) - 1.

    prices: wide frame, month-start index, one column per commodity.
    Rows with any missing input are dropped (never imputed here).
    """
    rows = []
    for _, r in cal.iterrows():
        for c in prices.columns:
            months = [r["baseline_m1"], r["baseline_m2"], r["flag_month"]]
            if not all(m in prices.index for m in months):
                continue
            b1, b2, f = (prices.at[m, c] for m in months)
            if pd.isna(b1) or pd.isna(b2) or pd.isna(f):
                continue
            base = (b1 + b2) / 2
            rows.append({"hijri_year": r["hijri_year"], "year": r["gregorian_year"],
                         "commodity": c, "flag_month": r["flag_month"],
                         "baseline_m1_price": b1, "baseline_m2_price": b2,
                         "baseline": base, "flag_price": f, "surge": f / base - 1,
                         "marginal": r["marginal"]})
    return pd.DataFrame(rows)


def summarize_surges(surges: pd.DataFrame) -> pd.DataFrame:
    g = surges.groupby("commodity")["surge"]
    out = g.agg(n="size", mean="mean", sd="std", min="min", max="max")
    out["cv"] = out["sd"] / out["mean"].abs()
    return out


def first_month_after_long_gaps(s: pd.Series, end: pd.Timestamp, max_gap: int = 2) -> pd.Timestamp:
    """First month from which, up to `end`, no run of missing months exceeds max_gap."""
    s = s.loc[:end]
    first = s.first_valid_index()
    full = s.reindex(pd.date_range(first, end, freq="MS"))
    start, run = first, 0
    for t, v in full.items():
        run = run + 1 if pd.isna(v) else 0
        if run > max_gap:
            start = None
        elif start is None and run == 0:
            start = t
    if start is None:
        raise ValueError("series ends inside a long gap")
    return start


# --------------------------------------------------------------------------
# Distribution fitting and goodness of fit
# --------------------------------------------------------------------------
def fit_surge_distribution(x: np.ndarray, family: str) -> dict:
    """Closed-form MLE. normal: surge ~ N(mu, sigma); lognormal: 1 + surge ~ LN(mu, sigma)."""
    x = np.asarray(x, dtype=float)
    if family == "normal":
        mu, sigma = x.mean(), x.std(ddof=0)
        mean, sd = mu, sigma
    elif family == "lognormal":
        if np.any(1 + x <= 0):
            raise ValueError("lognormal needs 1 + surge > 0")
        lg = np.log1p(x)
        mu, sigma = lg.mean(), lg.std(ddof=0)
        mean, sd = lognormal_moments(mu, sigma)
    else:
        raise ValueError(f"unknown family: {family!r}")
    return {"family": family, "mu": float(mu), "sigma": float(sigma), "mean": float(mean), "sd": float(sd)}


def lognormal_moments(mu: float, sigma: float) -> tuple[float, float]:
    """Mean and SD of surge = G - 1 when G ~ LN(mu, sigma)."""
    mean_g = np.exp(mu + sigma ** 2 / 2)
    sd_g = np.sqrt((np.exp(sigma ** 2) - 1) * np.exp(2 * mu + sigma ** 2))
    return float(mean_g - 1), float(sd_g)


def lognormal_from_moments(mean: float, sd: float) -> tuple[float, float]:
    """Inverse of lognormal_moments (moment matching on G = 1 + surge)."""
    if 1 + mean <= 0 or sd <= 0:
        raise ValueError("need 1 + mean > 0 and sd > 0")
    sigma2 = np.log(1 + (sd / (1 + mean)) ** 2)
    return float(np.log(1 + mean) - sigma2 / 2), float(np.sqrt(sigma2))


def surge_from_z(z: np.ndarray, family: str, mean: float, sd: float) -> np.ndarray:
    """Map standard normal draws to surges with the given family, mean and SD."""
    if family == "normal":
        return mean + sd * z
    if family == "lognormal":
        mu, sigma = lognormal_from_moments(mean, sd)
        return np.expm1(mu + sigma * z)
    raise ValueError(f"unknown family: {family!r}")


def surge_cdf(x: np.ndarray, fit: dict) -> np.ndarray:
    from scipy import stats
    if fit["family"] == "normal":
        return stats.norm.cdf(x, fit["mu"], fit["sigma"])
    return stats.lognorm.cdf(1 + np.asarray(x), s=fit["sigma"], scale=np.exp(fit["mu"]))


def surge_ppf(q: np.ndarray, fit: dict) -> np.ndarray:
    from scipy import stats
    if fit["family"] == "normal":
        return stats.norm.ppf(q, fit["mu"], fit["sigma"])
    return stats.lognorm.ppf(q, s=fit["sigma"], scale=np.exp(fit["mu"])) - 1


def surge_loglik(x: np.ndarray, fit: dict) -> float:
    from scipy import stats
    x = np.asarray(x, dtype=float)
    if fit["family"] == "normal":
        return float(stats.norm.logpdf(x, fit["mu"], fit["sigma"]).sum())
    return float(stats.lognorm.logpdf(1 + x, s=fit["sigma"], scale=np.exp(fit["mu"])).sum())


def ks_lilliefors(x: np.ndarray, family: str, n_boot: int, rng: np.random.Generator) -> dict:
    """KS statistic with a naive p-value and a parametric-bootstrap p-value.

    The naive p-value ignores that parameters were estimated from the same
    data (it is too lenient); the bootstrap refits on each simulated sample
    (Lilliefors correction).
    """
    from scipy import stats
    x = np.asarray(x, dtype=float)
    fit = fit_surge_distribution(x, family)
    d, p_naive = stats.kstest(x, lambda v: surge_cdf(v, fit))
    z = rng.standard_normal((n_boot, len(x)))
    sims = fit["mu"] + fit["sigma"] * z
    sims = sims if family == "normal" else np.expm1(sims)
    d_boot = np.empty(n_boot)
    for b in range(n_boot):
        fb = fit_surge_distribution(sims[b], family)
        d_boot[b] = stats.kstest(sims[b], lambda v: surge_cdf(v, fb)).statistic
    return {"ks_d": float(d), "p_naive": float(p_naive), "p_lilliefors": float((d_boot >= d).mean())}


def chi_square_gof(x: np.ndarray, family: str, min_expected: int = 5) -> dict:
    """Chi-square test on k equal-probability bins (k = n // min_expected, at least 3).

    dof = k - 1 - 2 estimated parameters; p is NaN when dof < 1.
    """
    from scipy import stats
    x = np.asarray(x, dtype=float)
    n = len(x)
    k = max(3, n // min_expected)
    fit = fit_surge_distribution(x, family)
    edges = surge_ppf(np.linspace(0, 1, k + 1), fit)
    observed = np.histogram(x, bins=np.r_[-np.inf, edges[1:-1], np.inf])[0]
    expected = np.full(k, n / k)
    chi2 = float(((observed - expected) ** 2 / expected).sum())
    dof = k - 3
    p = float(stats.chi2.sf(chi2, dof)) if dof >= 1 else float("nan")
    return {"bins": k, "expected_per_bin": n / k, "chi2": chi2, "dof": dof, "p": p}


def hedges_g(a: np.ndarray, b: np.ndarray) -> float:
    """Standardised mean difference (a - b) with small-sample correction."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    na, nb = len(a), len(b)
    sp = np.sqrt(((na - 1) * a.var(ddof=1) + (nb - 1) * b.var(ddof=1)) / (na + nb - 2))
    j = 1 - 3 / (4 * (na + nb) - 9)
    return float(j * (a.mean() - b.mean()) / sp)


def welch_ci(a: np.ndarray, b: np.ndarray, level: float = 0.95) -> tuple[float, float]:
    """Welch-Satterthwaite confidence interval for mean(a) - mean(b)."""
    from scipy import stats
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
    dof = (va + vb) ** 2 / (va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1))
    half = stats.t.ppf(0.5 + level / 2, dof) * np.sqrt(va + vb)
    diff = a.mean() - b.mean()
    return float(diff - half), float(diff + half)


def normal_scores_corr(frame: pd.DataFrame) -> np.ndarray:
    """Correlation of van der Waerden normal scores (rank-based, for a Gaussian copula)."""
    from scipy import stats
    complete = frame.dropna()
    scores = complete.rank().apply(lambda r: stats.norm.ppf(r / (len(complete) + 1)))
    return np.corrcoef(scores.to_numpy(), rowvar=False)
