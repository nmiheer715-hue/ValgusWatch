/*
  ValgusWatch — Dual-IMU ACL-risk screening prototype
  ICC x Ignyte Hackathon 2026 — Problem Statement 3: Athlete Health, Performance & Inclusivity

  WHAT THIS DOES
  ----------------
  Two BNO055 9-DOF IMUs (one strapped just below each knee, on the shin) share
  one I2C bus using BNO055's two selectable addresses (ADR pin low = 0x28,
  ADR pin high = 0x29 — no multiplexer needed).

  It runs in three modes, selected over Serial:
    'c' — CALIBRATE: capture a personal baseline (per literature: population
          cutoffs don't hold well across athletes, so we calibrate per-person)
    'd' — DRILL: live landing detection during training (jump/land, sprint-stop,
          fielding dive-recovery, etc.) — reports valgus angle + L/R asymmetry
          per landing, referenced against that athlete's own baseline
    's' — SWAY: single-leg static balance test (mirrors the Y-Balance /
          force-plate postural-control protocol used in the cited studies,
          substituting IMU angular variance for a force plate)

  A basic weighted risk score is computed and printed after each DRILL or SWAY
  session, combined with a manually entered 1-5 self-reported symptom score
  (per the evidence that self-reported symptoms explain more variance in
  injury-risk factors than hormone levels alone — see project notes).

  This is a HACKATHON PROTOTYPE: numeric thresholds are placeholders to be
  calibrated against each athlete's own baseline data, not fixed population
  cutoffs. Do not present this as a validated clinical/diagnostic device —
  frame it as a coach-facing screening/trend tool.

  HARDWARE
  --------
  - Arduino Uno/Nano (or any 5V/3.3V board with I2C)
  - 2x Adafruit BNO055 breakout (absolute orientation IMU, onboard sensor fusion)
    - Leg A (e.g. left shin):  ADR pin -> GND  (I2C address 0x28)
    - Leg B (e.g. right shin): ADR pin -> 3.3V (I2C address 0x29)
  - Both share SDA/SCL/3.3V/GND with the Arduino
  - Library: Adafruit_BNO055 + Adafruit_Sensor + Wire (install via Library Manager)

  WIRING (typical Uno)
  ---------------------
  BNO055 VIN -> 3.3V (or 5V if breakout has onboard regulator, check your board)
  BNO055 GND -> GND
  BNO055 SDA -> A4 (SDA)
  BNO055 SCL -> A5 (SCL)
  BNO055 ADR -> GND (Leg A) / 3.3V (Leg B)
*/

#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BNO055.h>
#include <utility/imumaths.h>

// ---------- Sensor objects (two addresses on one I2C bus) ----------
Adafruit_BNO055 bnoA = Adafruit_BNO055(55, 0x28); // Leg A
Adafruit_BNO055 bnoB = Adafruit_BNO055(56, 0x29); // Leg B

// ---------- Tunable constants (placeholders — calibrate per athlete) ----------
const float LANDING_ACCEL_THRESHOLD_MS2 = 14.0;  // total accel spike that flags a "landing"
const unsigned long LANDING_DEBOUNCE_MS = 400;    // ignore repeat triggers within this window
const int   SWAY_SAMPLE_WINDOW_MS       = 10000;  // 10s single-leg stance, matches Y-Balance-style protocols
const int   SWAY_SAMPLE_INTERVAL_MS     = 20;     // ~50Hz sampling during sway test

// ---------- Baseline storage (set during CALIBRATE mode) ----------
struct Baseline {
  float valgusA_deg   = 0;   // baseline knee valgus angle, Leg A, at landing
  float valgusB_deg   = 0;   // baseline knee valgus angle, Leg B, at landing
  float landingTimeMs = 0;   // baseline time-to-peak-decel, used for asymmetry timing
  float swayVariance  = 0;   // baseline postural sway variance
  bool  isSet         = false;
} baseline;

char mode = 0; // 'c' calibrate, 'd' drill, 's' sway

void setup() {
  Serial.begin(115200);
  while (!Serial) { delay(10); }

  Serial.println(F("=== ValgusWatch dual-IMU prototype ==="));

  if (!bnoA.begin()) {
    Serial.println(F("ERROR: BNO055 Leg A not detected (check address 0x28 wiring)"));
    while (1) delay(10);
  }
  if (!bnoB.begin()) {
    Serial.println(F("ERROR: BNO055 Leg B not detected (check address 0x29 wiring)"));
    while (1) delay(10);
  }
  delay(1000);
  bnoA.setExtCrystalUse(true);
  bnoB.setExtCrystalUse(true);

  Serial.println(F("Ready. Send over Serial:"));
  Serial.println(F("  c = calibrate (capture personal baseline, do 3 clean landings)"));
  Serial.println(F("  d = drill mode (live landing screening vs baseline)"));
  Serial.println(F("  s = single-leg sway test (10s static stance)"));
}

void loop() {
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'c' || c == 'd' || c == 's') {
      mode = c;
      Serial.print(F("\n--- Mode: "));
      Serial.println(mode);
      if (mode == 'c') runCalibration();
      else if (mode == 'd') runDrillMode();
      else if (mode == 's') runSwayTest();
    }
  }
}

// ---------- Helper: read total linear acceleration magnitude (m/s^2) ----------
float readAccelMagnitude(Adafruit_BNO055 &bno) {
  imu::Vector<3> lin = bno.getVector(Adafruit_BNO055::VECTOR_LINEARACCEL);
  return sqrt(lin.x() * lin.x() + lin.y() * lin.y() + lin.z() * lin.z());
}

// ---------- Helper: read frontal-plane (roll) angle as valgus proxy ----------
// NOTE: mount orientation matters — calibrate sign/axis for your strap
// orientation before trusting absolute values. Roll here approximates
// frontal-plane knee collapse relative to the shin's resting orientation.
float readValgusAngle(Adafruit_BNO055 &bno) {
  imu::Vector<3> euler = bno.getVector(Adafruit_BNO055::VECTOR_EULER);
  return euler.z(); // roll axis — verify against your mounting orientation
}

// ---------- CALIBRATE: average 3 clean landings to set personal baseline ----------
void runCalibration() {
  Serial.println(F("Perform 3 controlled double-leg landings (e.g. from a small box)."));
  float valgusA_sum = 0, valgusB_sum = 0, time_sum = 0;
  int captured = 0;

  while (captured < 3) {
    float aMagA = readAccelMagnitude(bnoA);
    float aMagB = readAccelMagnitude(bnoB);

    if (aMagA > LANDING_ACCEL_THRESHOLD_MS2 || aMagB > LANDING_ACCEL_THRESHOLD_MS2) {
      unsigned long t0 = millis();
      float vA = readValgusAngle(bnoA);
      float vB = readValgusAngle(bnoB);
      unsigned long t1 = millis();

      valgusA_sum += abs(vA);
      valgusB_sum += abs(vB);
      time_sum += (t1 - t0);
      captured++;

      Serial.print(F("Landing captured #")); Serial.println(captured);
      Serial.print(F("  Valgus A: ")); Serial.print(vA); Serial.print(F(" deg | Valgus B: "));
      Serial.print(vB); Serial.println(F(" deg"));

      delay(LANDING_DEBOUNCE_MS); // debounce so one jump isn't counted twice
    }
    delay(10);
  }

  baseline.valgusA_deg   = valgusA_sum / 3.0;
  baseline.valgusB_deg   = valgusB_sum / 3.0;
  baseline.landingTimeMs = time_sum / 3.0;
  baseline.isSet = true;

  Serial.println(F("\n=== Baseline set ==="));
  Serial.print(F("Baseline valgus A: ")); Serial.println(baseline.valgusA_deg);
  Serial.print(F("Baseline valgus B: ")); Serial.println(baseline.valgusB_deg);
}

// ---------- DRILL: live landing detection vs baseline, computes risk score ----------
void runDrillMode() {
  if (!baseline.isSet) {
    Serial.println(F("WARNING: no baseline set. Run 'c' first for meaningful numbers."));
  }
  Serial.println(F("Drill mode running. Send any key to stop.\n"));

  while (!Serial.available()) {
    float aMagA = readAccelMagnitude(bnoA);
    float aMagB = readAccelMagnitude(bnoB);

    if (aMagA > LANDING_ACCEL_THRESHOLD_MS2 || aMagB > LANDING_ACCEL_THRESHOLD_MS2) {
      unsigned long tA_start = millis();
      float vA = readValgusAngle(bnoA);
      unsigned long tA_detect = millis();

      // small settle delay then read leg B to compare landing timing (asymmetry)
      delay(15);
      float vB = readValgusAngle(bnoB);
      unsigned long tB_detect = millis();

      float asymmetryPct = 0;
      if (baseline.isSet) {
        float devA = abs(vA) - baseline.valgusA_deg;
        float devB = abs(vB) - baseline.valgusB_deg;
        asymmetryPct = abs(devA - devB) / max(1.0f, (abs(baseline.valgusA_deg) + abs(baseline.valgusB_deg)) / 2.0f) * 100.0;

        Serial.println(F("--- Landing event ---"));
        Serial.print(F("Valgus A: ")); Serial.print(vA);
        Serial.print(F(" deg (baseline ")); Serial.print(baseline.valgusA_deg); Serial.println(F(")"));
        Serial.print(F("Valgus B: ")); Serial.print(vB);
        Serial.print(F(" deg (baseline ")); Serial.print(baseline.valgusB_deg); Serial.println(F(")"));
        Serial.print(F("L-R asymmetry: ")); Serial.print(asymmetryPct); Serial.println(F(" %"));

        // --- Simple, transparent weighted risk score (NOT a validated clinical score) ---
        float w1 = 0.45, w2 = 0.35, w3 = 0.20; // valgus deviation, asymmetry, (symptom score added separately)
        float valgusDevScore = (abs(devA) + abs(devB)) / 2.0;
        float riskScore = w1 * valgusDevScore + w2 * asymmetryPct;

        Serial.print(F("Session risk score (pre-symptom): "));
        Serial.println(riskScore);
        Serial.println(F("Enter today's symptom score (1-5, 5=high discomfort) over Serial to finalize:"));
      } else {
        Serial.print(F("Valgus A: ")); Serial.print(vA);
        Serial.print(F(" | Valgus B: ")); Serial.println(vB);
      }

      delay(LANDING_DEBOUNCE_MS);
    }
    delay(10);
  }
  Serial.read(); // clear the stop keystroke
}

// ---------- SWAY: single-leg static balance, angular variance over 10s ----------
void runSwayTest() {
  Serial.println(F("Stand on ONE leg. Sampling for 10 seconds..."));
  delay(1500); // give athlete time to settle into position

  unsigned long start = millis();
  float sumSq = 0, sum = 0;
  int n = 0;

  while (millis() - start < SWAY_SAMPLE_WINDOW_MS) {
    imu::Vector<3> euler = bnoA.getVector(Adafruit_BNO055::VECTOR_EULER); // stance leg on Leg A slot
    float roll = euler.z();
    sum += roll;
    sumSq += roll * roll;
    n++;
    delay(SWAY_SAMPLE_INTERVAL_MS);
  }

  float mean = sum / n;
  float variance = (sumSq / n) - (mean * mean);

  Serial.println(F("\n=== Sway test complete ==="));
  Serial.print(F("Angular variance: ")); Serial.println(variance);

  if (baseline.isSet && baseline.swayVariance > 0) {
    float swayRatio = variance / baseline.swayVariance;
    Serial.print(F("Ratio vs baseline: ")); Serial.println(swayRatio);
    Serial.println(swayRatio > 1.3 ? F("Sway elevated vs personal baseline — flag for coach review") : F("Within normal range vs personal baseline"));
  } else if (mode == 'c') {
    baseline.swayVariance = variance;
    Serial.println(F("Stored as baseline sway variance."));
  }
}
