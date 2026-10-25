"""
ValgusWatch — Phase 0 validation: real motion-data analysis from a smartphone
ICC x Ignyte Hackathon 2026 · Idea Track · Problem Statement 3

WHAT THIS DOES
--------------
Runs the SAME signal-processing logic as the dual-BNO055 Arduino firmware
(landing detection, valgus-angle extraction, personal-baseline calibration,
single-leg sway, transparent risk score) on real sensor data logged from a
smartphone — at zero hardware cost, before any dedicated IMU purchase.

HOW TO COLLECT THE DATA (free, ~10 minutes)
--------------------------------------------
1. Install a free sensor-logging app:
     - "Physics Toolbox Sensor Suite" (Android/iOS, free), OR
     - "Sensor Logger" by Tszheichoi (Android/iOS, free)
2. Strap or tape your phone securely flat against one shin (a sock, ankle
   wrap, or armband works — anything that stops it sliding on landing).
3. Log TWO sensors over the same session, then export each as its own CSV:
     - "Linear Accelerometer" (acceleration WITHOUT gravity, m/s^2 or g)
     - "Device Orientation" (gives roll / pitch / azimuth in degrees — this
       is the same kind of fused-orientation output the BNO055 gives us,
       just from the phone's own sensor fusion instead)
4. Do 5-6 controlled two-leg landings (small box jump, or jump-and-land in
   place) with a clear pause between each, then export both logs as CSV.
5. Optional: also record a 10-second single-leg stance (eyes open) at the
   end of the session for the sway test.
6. Run this script:
     python valguswatch_phone_analysis.py linear_accel.csv orientation.csv

WHAT THIS VALIDATES (and what it doesn't)
------------------------------------------
This validates the PIPELINE on real human motion data: does the landing
detector actually fire on real jumps, does the valgus-angle proxy respond
to real movement, does baseline-deviation scoring behave sensibly.

It does NOT validate true bilateral (left-right) asymmetry captured in one
instant, since a single phone can only be on one leg at a time. Run the
same protocol on the other leg as a SEPARATE recording and pass those
files too (--leg-b-accel / --leg-b-orient) for a rough, non-simultaneous
asymmetry comparison instead of a true simultaneous one.

COLUMN NAMES WILL LIKELY NEED ADJUSTING
-----------------------------------------
Sensor-logging apps don't all name their CSV columns the same way. This
script prints the columns it finds in each file before doing anything else,
and tries common defaults (see CONFIG below). If it can't find a match, it
tells you exactly which columns it saw so you can edit CONFIG.

Needs: pip install pandas numpy matplotlib
"""

import argparse
import sys

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ----------------------------------------------------------------------
# CONFIG — edit these if your app's CSV uses different column names.
# Each is a list of candidate names (lowercase, checked in order); the
# script also falls back to "any column containing this substring".
# ----------------------------------------------------------------------
TIME_CANDIDATES = ["time", "timestamp", "seconds_elapsed", "elapsed"]
ACCEL_X_CANDIDATES = ["ax", "gfx", "x", "accelerometerx", "linear_accel_x"]
ACCEL_Y_CANDIDATES = ["ay", "gfy", "y", "accelerometery", "linear_accel_y"]
ACCEL_Z_CANDIDATES = ["az", "gfz", "z", "accelerometerz", "linear_accel_z"]
ROLL_CANDIDATES = ["roll", "device_orientation_roll", "orientation_roll"]

# Landing detection: a peak in acceleration magnitude above this many
# times the session's median magnitude counts as a "landing". Tune this
# up/down if it over- or under-detects on your data (the script prints
# how many landings it found — sanity check against how many jumps you
# actually did).
LANDING_PEAK_FACTOR = 2.5
# Minimum seconds between two detected landings (debounce, mirrors the
# Arduino sketch's LANDING_DEBOUNCE_MS).
MIN_LANDING_GAP_S = 0.6
# How many of the earliest landings form the personal baseline (mirrors
# the Arduino sketch's 3-landing calibration).
BASELINE_LANDING_COUNT = 3


def find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols_lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand in cols_lower:
            return cols_lower[cand]
    for cand in candidates:
        for lower, original in cols_lower.items():
            if cand in lower:
                return original
    return None


def load_csv(path: str, label: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    print(f"\n[{label}] loaded {path} — {len(df)} rows")
    print(f"[{label}] columns found: {list(df.columns)}")
    return df


def normalize_time(df: pd.DataFrame, time_col: str) -> pd.Series:
    t = df[time_col].astype(float)
    # Heuristic: if values look like milliseconds (large numbers), convert to seconds.
    if t.max() > 1e5:
        t = t / 1000.0
    return t - t.min()


def detect_landings(accel_df: pd.DataFrame) -> pd.DataFrame:
    time_col = find_column(accel_df, TIME_CANDIDATES)
    x_col = find_column(accel_df, ACCEL_X_CANDIDATES)
    y_col = find_column(accel_df, ACCEL_Y_CANDIDATES)
    z_col = find_column(accel_df, ACCEL_Z_CANDIDATES)

    missing = [n for n, c in [("time", time_col), ("x", x_col), ("y", y_col), ("z", z_col)] if c is None]
    if missing:
        print(f"\nERROR: couldn't auto-detect accelerometer column(s): {missing}")
        print("Edit the *_CANDIDATES lists at the top of this script to match your CSV's real column names.")
        sys.exit(1)

    t = normalize_time(accel_df, time_col)
    mag = np.sqrt(accel_df[x_col] ** 2 + accel_df[y_col] ** 2 + accel_df[z_col] ** 2)

    threshold = mag.median() * LANDING_PEAK_FACTOR
    landings = []
    last_landing_t = -999.0
    for i in range(1, len(mag) - 1):
        if mag.iloc[i] > threshold and mag.iloc[i] >= mag.iloc[i - 1] and mag.iloc[i] >= mag.iloc[i + 1]:
            if t.iloc[i] - last_landing_t >= MIN_LANDING_GAP_S:
                landings.append({"time_s": t.iloc[i], "accel_mag": mag.iloc[i]})
                last_landing_t = t.iloc[i]

    result = pd.DataFrame(landings)
    print(f"\nDetected {len(result)} landing(s) (threshold={threshold:.2f} m/s^2). "
          f"Compare this to how many jumps you actually did — adjust LANDING_PEAK_FACTOR if it's off.")
    return result


def attach_valgus_angle(landings: pd.DataFrame, orientation_df: pd.DataFrame) -> pd.DataFrame:
    time_col = find_column(orientation_df, TIME_CANDIDATES)
    roll_col = find_column(orientation_df, ROLL_CANDIDATES)

    if time_col is None or roll_col is None:
        print(f"\nERROR: couldn't auto-detect orientation column(s): "
              f"time={time_col}, roll={roll_col}")
        print("Edit TIME_CANDIDATES / ROLL_CANDIDATES at the top of this script.")
        sys.exit(1)

    ot = normalize_time(orientation_df, time_col)
    roll = orientation_df[roll_col].astype(float)

    valgus_vals = []
    for t in landings["time_s"]:
        idx = (ot - t).abs().idxmin()
        valgus_vals.append(abs(roll.iloc[idx]))
    landings = landings.copy()
    landings["valgus_deg"] = valgus_vals
    return landings


def score_against_baseline(landings: pd.DataFrame) -> pd.DataFrame:
    if len(landings) < BASELINE_LANDING_COUNT + 1:
        print(f"\nWARNING: only {len(landings)} landing(s) detected — need at least "
              f"{BASELINE_LANDING_COUNT + 1} (baseline + 1 test) for a meaningful score. "
              f"Record a few more jumps.")
    baseline = landings["valgus_deg"].iloc[:BASELINE_LANDING_COUNT].mean() if len(landings) else float("nan")
    landings = landings.copy()
    landings["baseline_deg"] = baseline
    landings["deviation_pct"] = (landings["valgus_deg"] - baseline) / baseline * 100.0
    landings["session"] = range(1, len(landings) + 1)
    return landings


def compute_sway(orientation_df: pd.DataFrame, window_start_s: float | None, window_len_s: float = 10.0) -> float | None:
    """Angular variance over a stance window — mirrors the Arduino sway test.
    If window_start_s is None, uses the LAST window_len_s seconds of the file
    (assumes you recorded the single-leg stance at the end of the session)."""
    time_col = find_column(orientation_df, TIME_CANDIDATES)
    roll_col = find_column(orientation_df, ROLL_CANDIDATES)
    if time_col is None or roll_col is None:
        return None
    ot = normalize_time(orientation_df, time_col)
    roll = orientation_df[roll_col].astype(float)
    end = ot.max() if window_start_s is None else window_start_s + window_len_s
    start = end - window_len_s
    mask = (ot >= start) & (ot <= end)
    if mask.sum() < 5:
        return None
    return float(roll[mask].var())


def plot_report(landings: pd.DataFrame, out_path: str) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(landings["session"], landings["valgus_deg"], color="#0F9E7C", label="Valgus angle (deg)")
    baseline = landings["baseline_deg"].iloc[0]
    ax.axhline(baseline, color="#101A2E", linestyle="--", linewidth=1.5, label=f"Baseline ({baseline:.1f} deg)")
    ax.set_xlabel("Landing / session")
    ax.set_ylabel("Valgus angle (degrees)")
    ax.set_title("ValgusWatch Phase 0 — real phone sensor data")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"\nSaved chart to {out_path}")


def main():
    parser = argparse.ArgumentParser(description="ValgusWatch Phase 0 phone-sensor analysis")
    parser.add_argument("accel_csv", help="Linear accelerometer CSV export")
    parser.add_argument("orientation_csv", help="Device orientation CSV export")
    parser.add_argument("--leg-b-accel", help="Optional: second leg's accelerometer CSV (separate recording)")
    parser.add_argument("--leg-b-orient", help="Optional: second leg's orientation CSV (separate recording)")
    parser.add_argument("--sway-window-start", type=float, default=None,
                         help="Seconds into the orientation file where the single-leg stance test starts "
                              "(default: assumes it's the last 10s of the file)")
    parser.add_argument("--out", default="valguswatch_phase0_report.png", help="Output chart path")
    args = parser.parse_args()

    accel_df = load_csv(args.accel_csv, "Leg A accel")
    orient_df = load_csv(args.orientation_csv, "Leg A orientation")

    landings = detect_landings(accel_df)
    if landings.empty:
        print("\nNo landings detected — try lowering LANDING_PEAK_FACTOR or re-check your recording.")
        sys.exit(1)

    landings = attach_valgus_angle(landings, orient_df)
    landings = score_against_baseline(landings)

    print("\n=== Leg A landing report ===")
    print(landings[["session", "time_s", "valgus_deg", "baseline_deg", "deviation_pct"]]
          .round(2).to_string(index=False))

    sway = compute_sway(orient_df, args.sway_window_start)
    if sway is not None:
        print(f"\nSingle-leg sway variance (last {10}s window): {sway:.3f}")
    else:
        print("\nNo sway window found — record a 10s single-leg stance and re-run, "
              "or pass --sway-window-start.")

    plot_report(landings, args.out)

    # Optional Leg B, for a rough (non-simultaneous) asymmetry comparison
    if args.leg_b_accel and args.leg_b_orient:
        accel_b = load_csv(args.leg_b_accel, "Leg B accel")
        orient_b = load_csv(args.leg_b_orient, "Leg B orientation")
        landings_b = detect_landings(accel_b)
        if not landings_b.empty:
            landings_b = attach_valgus_angle(landings_b, orient_b)
            landings_b = score_against_baseline(landings_b)
            print("\n=== Leg B landing report ===")
            print(landings_b[["session", "time_s", "valgus_deg", "baseline_deg", "deviation_pct"]]
                  .round(2).to_string(index=False))

            mean_a = landings["valgus_deg"].mean()
            mean_b = landings_b["valgus_deg"].mean()
            asymmetry_pct = abs(mean_a - mean_b) / ((mean_a + mean_b) / 2) * 100.0
            print(f"\nRough L-R asymmetry (mean valgus, separate sessions): {asymmetry_pct:.1f}%")
            print("NOTE: this is NOT the same as the simultaneous per-landing asymmetry the dual-IMU "
                  "hardware measures — treat it as a rough directional signal only.")

    print("\nDone. This is real data through the same pipeline the Arduino firmware implements — "
          "cite it in the Concept Note's Implementation Status as Phase 0 validation.")


if __name__ == "__main__":
    main()
