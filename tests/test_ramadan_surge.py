import datetime as dt
import os
import sys

import numpy as np
import pandas as pd
import pytest
from statsmodels.tsa.seasonal import seasonal_decompose

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import ramadan_surge as rs  # noqa: E402


def monthly(values, start="2010-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"), dtype=float)


# ---- calendar ---------------------------------------------------------------
@pytest.mark.parametrize("hy,start,end", [
    (1441, dt.date(2020, 4, 24), dt.date(2020, 5, 23)),
    (1448, dt.date(2027, 2, 8), None),
])
def test_ramadan_dates_ummalqura(hy, start, end):
    s, e = rs.ramadan_dates(hy)
    assert s == start
    assert 28 <= (e - s).days <= 29
    if end:
        assert e == end


def test_ramadan_dates_offset_and_arithmetic():
    s0, e0 = rs.ramadan_dates(1441)
    s1, e1 = rs.ramadan_dates(1441, offset_days=1)
    assert (s1 - s0).days == 1 and (e1 - e0).days == 1
    sa, _ = rs.ramadan_dates(1441, calendar="arithmetic")
    assert abs((sa - s0).days) <= 2
    with pytest.raises(ValueError):
        rs.ramadan_dates(1441, calendar="lunar")


def test_days_by_month_counts_and_validation():
    counts = rs.days_by_month(dt.date(2020, 4, 24), dt.date(2020, 5, 23))
    assert counts == {pd.Timestamp("2020-04-01"): 7, pd.Timestamp("2020-05-01"): 23}
    with pytest.raises(ValueError):
        rs.days_by_month(dt.date(2020, 5, 2), dt.date(2020, 5, 1))


def test_ramadan_calendar_flag_baseline_marginal():
    cal = rs.ramadan_calendar(2019, 2021).set_index("gregorian_year")
    assert list(cal.index) == [2019, 2020, 2021]
    r = cal.loc[2020]
    assert r["flag_month"] == pd.Timestamp("2020-05-01")
    assert r["baseline_m1"] == pd.Timestamp("2020-02-01")
    assert r["baseline_m2"] == pd.Timestamp("2020-03-01")
    assert not r["marginal"]
    # 2021: 13 Apr to 12 May -> 18 days in April of 30 -> share 0.6, not marginal
    assert cal.loc[2021, "flag_month"] == pd.Timestamp("2021-04-01")


def test_ramadan_day_share_sums_to_length():
    cal = rs.ramadan_calendar(2020, 2020)
    idx = pd.date_range("2020-01-01", "2020-12-01", freq="MS")
    share = rs.ramadan_day_share(idx, cal)
    days = (share * idx.days_in_month).round().sum()
    assert days == cal.loc[0, "n_days"]


# ---- cleaning ---------------------------------------------------------------
def test_fill_short_gaps_rules():
    s = monthly([1, np.nan, 3, 4, np.nan, np.nan, 10, 11, np.nan, np.nan, np.nan, 20, np.nan])
    filled, log = rs.fill_short_gaps(s)
    assert filled.iloc[1] == 2.0
    assert filled.iloc[4] == pytest.approx(6.0) and filled.iloc[5] == pytest.approx(8.0)
    assert filled.iloc[8:11].isna().all()          # run of 3 never filled
    assert np.isnan(filled.iloc[12])               # trailing gap not filled
    assert len(log) == 3 and set(log["gap_length"]) == {1, 2}
    assert s.isna().sum() == 7                     # input not mutated


def test_longest_complete_window():
    s = monthly([1, np.nan, 1, 1, 1, np.nan, 1])
    start, end = rs.longest_complete_window(s)
    assert start == s.index[2] and end == s.index[4]


def test_chained_index_matched_and_bridged():
    idx = pd.date_range("2020-01-01", periods=5, freq="MS")
    panel = pd.DataFrame({
        "a": [10, 11, np.nan, 12.1, 12.1],
        "b": [20, 22, np.nan, 24.2, 24.2],
        "c": [np.nan, np.nan, 99, np.nan, 50],     # never matched with a/b at month 3
    }, index=idx)
    out = rs.chained_index(panel)
    assert out["index"].iloc[0] == 1.0
    assert out["index"].iloc[1] == pytest.approx(1.1)
    assert np.isnan(out["index"].iloc[2])           # only one market: cannot link
    assert out["index"].iloc[3] == pytest.approx(1.21)
    assert out["lag"].iloc[3] == 2                  # bridged over the missing month
    assert out["index"].iloc[4] == pytest.approx(1.21)  # c ignored: no matched history
    with pytest.raises(ValueError):
        rs.chained_index(panel[["c"]])


def test_chained_index_unlinkable_gap():
    idx = pd.date_range("2020-01-01", periods=6, freq="MS")
    panel = pd.DataFrame({"a": [1, np.nan, np.nan, np.nan, np.nan, 2],
                          "b": [1, np.nan, np.nan, np.nan, np.nan, 2]}, index=idx)
    out = rs.chained_index(panel, max_bridge=3)
    assert out["index"].iloc[1:].isna().all()
    linked = rs.chained_index(panel, max_bridge=None)
    assert linked["index"].iloc[1:5].isna().all() and linked["index"].iloc[5] == pytest.approx(2.0)


def test_chain_link_ratio_and_errors():
    old = monthly([10, 10, 10, np.nan], "2020-01-01")
    new = monthly([np.nan, 5, 5, 6], "2020-01-01")
    joined, k = rs.chain_link(old, new, [pd.Timestamp("2020-02-01"), pd.Timestamp("2020-03-01")])
    assert k == 2.0
    assert joined.iloc[-1] == 12.0 and len(joined) == 4
    with pytest.raises(ValueError):
        rs.chain_link(old, new, [pd.Timestamp("2021-01-01")])


# ---- decomposition ----------------------------------------------------------
def test_ratio_to_cma_matches_statsmodels():
    rng = np.random.default_rng(0)
    n = 96
    season = 1 + 0.05 * np.sin(2 * np.pi * np.arange(n) / 12)
    s = monthly(np.linspace(20, 40, n) * season * np.exp(rng.normal(0, 0.01, n)))
    manual = rs.ratio_to_cma(s)
    sm = seasonal_decompose(s, model="multiplicative", period=12)
    assert np.allclose(manual["trend"].dropna(), sm.trend.dropna())
    assert np.allclose(manual["seasonal"], sm.seasonal)
    assert manual["seasonal"].iloc[:12].mean() == pytest.approx(1.0)


def test_ratio_to_cma_tolerates_gap_and_rejects_short():
    s = monthly(np.linspace(20, 40, 72) * (1 + 0.05 * np.sin(2 * np.pi * np.arange(72) / 12)))
    gappy = s.copy()
    gappy.iloc[30:33] = np.nan
    dec = rs.ratio_to_cma(gappy)
    full = rs.ratio_to_cma(s)
    assert dec["trend"].iloc[24:39].isna().all()
    assert np.allclose(dec["seasonal"], full["seasonal"], atol=0.002)
    with pytest.raises(ValueError):
        rs.ratio_to_cma(s.iloc[:14])


def test_flag_spikes_detects_revert_not_level_shift():
    s = monthly([40, 41, 40, 25, 25, 23, 41, 40, np.nan, 40, 60, 61, 62, 41, 30, 41])
    f = rs.flag_spikes(s)
    assert list(f[f].index) == list(s.index[[3, 4, 5, 10, 11, 12, 14]])
    shift = monthly([40, 41, 40, 25, 25, 25, 25, 25])  # permanent fall: not an error
    assert not rs.flag_spikes(shift).any()


def test_flag_panel_errors_keeps_nationwide_moves():
    lone = [40, 41, 40, 25, 25, 23, 41, 40]
    surge = [40, 40, 40, 52, 40, 40, 40, 40]       # all markets spike together
    panel = pd.DataFrame({
        "bad": monthly(lone), "m2": monthly(surge), "m3": monthly(surge), "m4": monthly(surge),
    })
    panel.loc[panel.index[3:6], ["m2", "m3", "m4"]] = [[52, 52, 52], [40, 40, 40], [40, 40, 40]]
    flags = rs.flag_panel_errors(panel)
    assert list(flags.index[flags["bad"]]) == list(panel.index[3:6])
    assert not flags[["m2", "m3", "m4"]].any().any()
    single = pd.DataFrame({"only": monthly(lone)})
    assert rs.flag_panel_errors(single)["only"].sum() == 3


def test_centered_ma_odd_period():
    s = monthly([1, 2, 3, 4, 5])
    assert rs.centered_ma(s, 3).iloc[2] == 3.0


# ---- surges -----------------------------------------------------------------
def test_surge_table_and_summary():
    idx = pd.date_range("2020-01-01", "2020-06-01", freq="MS")
    prices = pd.DataFrame({"rice": [1, 10, 10, 10, 11, 1], "oil": [1, np.nan, 10, 10, 12, 1]}, index=idx)
    cal = rs.ramadan_calendar(2020, 2020)
    tab = rs.surge_table(prices, cal)
    assert list(tab["commodity"]) == ["rice"]      # oil dropped: missing baseline month
    assert tab.loc[0, "surge"] == pytest.approx(0.1)
    summ = rs.summarize_surges(pd.concat([tab, tab.assign(surge=0.3)]))
    assert summ.loc["rice", "mean"] == pytest.approx(0.2)
    assert summ.loc["rice", "cv"] == pytest.approx(summ.loc["rice", "sd"] / 0.2)


# ---- extra helpers ------------------------------------------------------------
def test_first_month_after_long_gaps():
    s = monthly([1, np.nan, np.nan, np.nan, 1, np.nan, 1, 1])
    assert rs.first_month_after_long_gaps(s, s.index[-1]) == s.index[4]
    s2 = monthly([1, np.nan, np.nan, 1])
    assert rs.first_month_after_long_gaps(s2, s2.index[-1]) == s2.index[0]
    with pytest.raises(ValueError):
        rs.first_month_after_long_gaps(monthly([1, np.nan, np.nan, np.nan]), monthly([0] * 4).index[-1])


@pytest.mark.parametrize("family", ["normal", "lognormal"])
def test_fit_moments_roundtrip(family):
    x = np.array([0.02, 0.05, -0.01, 0.10, 0.04, 0.00, 0.07])
    fit = rs.fit_surge_distribution(x, family)
    z = np.random.default_rng(1).standard_normal(400_000)
    draws = rs.surge_from_z(z, family, fit["mean"], fit["sd"])
    assert draws.mean() == pytest.approx(fit["mean"], abs=1e-3)
    assert draws.std() == pytest.approx(fit["sd"], rel=1e-2)
    assert rs.surge_cdf(np.array([fit["mean"]]), fit)[0] == pytest.approx(0.5, abs=0.05)
    q = rs.surge_ppf(np.array([0.3]), fit)
    assert rs.surge_cdf(q, fit)[0] == pytest.approx(0.3)
    assert np.isfinite(rs.surge_loglik(x, fit))


def test_fit_errors():
    with pytest.raises(ValueError):
        rs.fit_surge_distribution(np.array([-1.5, 0.1]), "lognormal")
    with pytest.raises(ValueError):
        rs.fit_surge_distribution(np.array([0.1, 0.2]), "gamma")
    with pytest.raises(ValueError):
        rs.surge_from_z(np.zeros(2), "gamma", 0, 1)
    with pytest.raises(ValueError):
        rs.lognormal_from_moments(-2, 0.1)


def test_lognormal_moment_inverse():
    mu, sigma = rs.lognormal_from_moments(0.05, 0.08)
    assert rs.lognormal_moments(mu, sigma) == pytest.approx((0.05, 0.08))


def test_gof_tests_accept_true_model_and_flag_small_n():
    rng = np.random.default_rng(3)
    x = rng.normal(0.05, 0.1, 200)
    ks = rs.ks_lilliefors(x, "normal", 300, np.random.default_rng(4))
    assert ks["p_lilliefors"] > 0.01 and 0 < ks["ks_d"] < 0.2
    chi = rs.chi_square_gof(x, "normal")
    assert chi["bins"] == 40 and chi["dof"] == 37 and chi["p"] > 0.01
    small = rs.chi_square_gof(x[:12], "lognormal")
    assert small["bins"] == 3 and np.isnan(small["p"])


def test_hedges_g_and_welch_ci():
    a, b = np.array([1.0, 2, 3, 4]), np.array([0.0, 1, 2, 3])
    assert rs.hedges_g(a, b) > 0
    lo, hi = rs.welch_ci(a, b)
    assert lo < 1 < hi


def test_normal_scores_corr_is_rank_based():
    f = pd.DataFrame({"a": [1, 2, 3, 4, 5.0], "b": [1, 4, 9, 16, 1000.0], "c": [5, 4, 3, 2, 1.0]})
    r = rs.normal_scores_corr(f)
    assert r[0, 1] == pytest.approx(1.0) and r[0, 2] == pytest.approx(-1.0)
