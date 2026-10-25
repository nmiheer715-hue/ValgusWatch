# ValgusWatch

**A low-cost, dual-IMU wearable that screens athletes for the knee-valgus landing pattern linked to ACL injuries — built to be affordable at the grassroots level, not just in elite sports-science labs.**

Built for the **ICC x Ignyte Hackathon 2026** · Problem Statement 3: *Athlete Health, Performance & Inclusivity* · Idea Track.

> 🏏 Shortlisted for the next round of the hackathon. Full write-up and research notes: **[NotebookLM project notebook](https://notebooklm.link.google/2ISOGxU8BQwp)**

---

## The problem

Female athletes tear their ACL at **2–8x** the rate of male athletes, face a **4x** higher risk of a second ACL injury after return to play, and a **6x** higher risk of injuring the *other* knee. The dominant cause is a measurable landing pattern — not chance.

A quadriceps-dominant landing strategy causes **knee valgus collapse**: the frontal-plane knee cave that puts direct shear force on the ACL. This is physically measurable, well established in the sports-medicine literature, and is exactly what ValgusWatch screens for — without needing a $50,000+ force-plate lab.

## The solution

| Stage | What it does |
|---|---|
| **Dual IMU node** | Two BNO055 9-DOF sensors, one strapped below each knee (shin-worn), sharing a single I2C bus |
| **Signal processing** | Extracts valgus angle, left–right landing asymmetry, and postural sway variance from raw IMU data |
| **Personal baseline** | Calibrated per athlete (population cutoffs don't hold up across individuals — see project notes), not a fixed threshold |
| **Coach dashboard** | Live web dashboard showing trend data per athlete, flags deviation from that athlete's own baseline |

A daily 30-second self-reported symptom check-in (energy, discomfort, sleep) feeds into the same risk trend, since self-reported symptoms explain meaningful variance in injury-risk factors on their own.

**This is a hackathon prototype.** Numeric thresholds are placeholders meant to be calibrated against each athlete's own data — this is a coach-facing *screening and trend tool*, not a validated clinical or diagnostic device.

## Repo structure

```
ValgusWatch/
├── ValgusWatch_dualIMU.ino        # Arduino firmware — dual BNO055 IMU, calibrate/drill/sway modes
├── valguswatch_phone_analysis.py  # Phase 0 validation: same pipeline, run on free smartphone sensor data
└── index.html                     # Live web app — athlete self check-in + coach/medical dashboard (Firebase-backed)
```

### 1. `ValgusWatch_dualIMU.ino` — firmware

Runs on an Arduino Uno/Nano with two Adafruit BNO055 breakouts (one per shin, using the sensor's two selectable I2C addresses — no multiplexer needed). Three serial-selected modes:

- `c` — **Calibrate**: capture a 3-landing personal baseline
- `d` — **Drill**: live landing detection during training, reports valgus angle + L/R asymmetry against that athlete's baseline, computes a transparent weighted risk score
- `s` — **Sway**: 10-second single-leg static balance test (mirrors Y-Balance / force-plate postural-control protocols)

See the file header for full wiring and library requirements (`Adafruit_BNO055`, `Adafruit_Sensor`, `Wire`).

### 2. `valguswatch_phone_analysis.py` — Phase 0 validation

Runs the *same* landing-detection, valgus-angle, baseline-calibration, and risk-scoring logic as the Arduino firmware — but on real motion data logged from a free smartphone sensor app, at zero hardware cost. Used to validate the signal-processing pipeline on real human movement before any IMU hardware purchase.

```bash
pip install pandas numpy matplotlib
python valguswatch_phone_analysis.py linear_accel.csv orientation.csv
```

Full data-collection instructions (which free apps to use, how to strap the phone, what to export) are in the script's header docstring.

### 3. `index.html` — live web app

A single self-contained page covering both sides of the product:

- **Athlete view** — join once, then a 30-second daily check-in (energy / discomfort / sleep sliders)
- **Coach & medical view** — live roster with per-athlete risk flags, and a detail view with a discomfort trend chart

Backed by Firebase Firestore for real-time sync between athletes and coaches. To run your own copy, create a Firebase project (Firestore in production mode), lock down the `athletes` collection (and its `checkins` subcollection) with security rules, and drop your project's config into the `firebaseConfig` block near the top of the script. Then open `index.html` directly, or deploy it anywhere that serves static files (Netlify, Vercel, GitHub Pages, etc.).

## Tech stack

Arduino C++ · Python (pandas / numpy / matplotlib) · HTML/CSS/JS · Firebase Firestore

## Team

Built by a BMS College of Engineering (BMSCE), Bangalore team for ICC x Ignyte Hackathon 2026.

## License

MIT — see [LICENSE](LICENSE).
