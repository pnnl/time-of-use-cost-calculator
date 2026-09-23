"""
Generates dst_offset_check.csv for manual inspection of DST timestamp adjustment.

Run with:
    python tests/test_dst_offset.py
or include in pytest (the csv is written as a side-effect).
"""

import os
import sys
import pytest
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from helpers.energyplus_date_helpers import DateTimeEP

SAMPLE_CSV = os.path.join(
    os.path.dirname(__file__), "data", "sample_simulation_output", "sample.csv"
)
OUTPUT_CSV = os.path.join(
    os.path.dirname(__file__), "test_outputs", "dst_offset_check.csv"
)
DST_COL = "Environment:Site Daylight Saving Time Status [](Hourly)"
DAY_TYPE_COL = "Environment:Site Day Type Index [](Hourly)"


def _build_dst_df():
    df = pd.read_csv(SAMPLE_CSV)
    dtep = DateTimeEP(df, year=2017)
    df = dtep.transform()
    day_type_col = DAY_TYPE_COL if DAY_TYPE_COL in df.columns else None
    df = dtep.add_dst_clocktime(dst_type_col=DST_COL, day_type_col=day_type_col)
    return df


@pytest.fixture(autouse=True, scope="module")
def write_dst_csv():
    _write_output_csv(_build_dst_df())


def test_dst_offset_is_one_hour():
    """Every DST=1 row should have DST_time exactly 1 hour ahead of its EnergyPlus index."""
    df = _build_dst_df()
    dst_rows = df[df[DST_COL] == 1]
    offsets = (dst_rows["DST_time"] - dst_rows.index).dt.total_seconds() / 3600
    assert (offsets == 1.0).all(), f"Unexpected offsets:\n{offsets[offsets != 1.0]}"


def test_dst_offset_is_zero_outside_dst():
    """Every DST=0 row should have DST_time equal to its EnergyPlus index."""
    df = _build_dst_df()
    std_rows = df[df[DST_COL] == 0]
    offsets = (std_rows["DST_time"] - std_rows.index).dt.total_seconds() / 3600
    assert (offsets == 0.0).all(), f"Unexpected offsets:\n{offsets[offsets != 0.0]}"


def test_dst_day_type_midnight_crossing():
    """Rows that cross midnight due to DST should carry the next day's day_type."""
    df = _build_dst_df()
    if DAY_TYPE_COL not in df.columns:
        pytest.skip("No day type column in sample data")
    dst_rows = df[df[DST_COL] == 1].copy()
    dst_rows["dst_date"] = dst_rows["DST_time"].dt.date
    dst_rows["orig_date"] = dst_rows.index.date
    midnight_crossings = dst_rows[dst_rows["dst_date"] != dst_rows["orig_date"]]
    if midnight_crossings.empty:
        pytest.skip("No midnight crossings found in sample data")
    for ts, row in midnight_crossings.iterrows():
        next_ts = ts + pd.Timedelta(hours=1)
        if next_ts in df.index:
            assert row[DAY_TYPE_COL] == df.loc[next_ts, DAY_TYPE_COL], (
                f"Day type mismatch at midnight crossing {ts}: "
                f"got {row[DAY_TYPE_COL]}, expected {df.loc[next_ts, DAY_TYPE_COL]}"
            )


def _write_output_csv(df):
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    data = {
        "original_time": df.index,
        "DST_time": df["DST_time"].values,
        "offset_hours": (df["DST_time"] - df.index).dt.total_seconds() / 3600,
        DST_COL: df[DST_COL].values,
    }
    if DAY_TYPE_COL in df.columns:
        data[DAY_TYPE_COL] = df[DAY_TYPE_COL].values
    out = pd.DataFrame(data)
    out.to_csv(OUTPUT_CSV, index=False)
    print(f"\nWrote {len(out)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    df = _build_dst_df()
    _write_output_csv(df)
