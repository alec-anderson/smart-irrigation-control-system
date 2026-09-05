
#include <Wire.h>
#include <stdlib.h>
#include <string.h>

// ============================================================
// NANO-OWNED PRODUCTION CONTROL (SRAM-OPTIMIZED)
// Same behavior as v1, but with:
// - no Arduino String usage
// - F() macro on serial literals
// - smaller integer types where practical
// ============================================================

// ---------------- MOTOR DRIVER PINS ----------------
const uint8_t M1_RPWM = 5;
const uint8_t M1_LPWM = 6;
const uint8_t M1_REN  = 7;
const uint8_t M1_LEN  = 8;

const uint8_t M2_RPWM = 9;
const uint8_t M2_LPWM = 10;
const uint8_t M2_REN  = 11;
const uint8_t M2_LEN  = 12;

// ---------------- LIMIT SWITCHES ----------------
const uint8_t LIM1_PIN = 2;   // active LOW with INPUT_PULLUP
const uint8_t LIM2_PIN = 3;   // active LOW with INPUT_PULLUP

// ---------------- WATER RELAY PINS ----------------
const uint8_t RELAY_OPEN_PIN  = 4;
const uint8_t RELAY_CLOSE_PIN = A1;
const uint8_t RELAY_PUMP_PIN  = A2;

const bool PUMP_RELAY_ACTIVE_HIGH  = false;
const bool VALVE_RELAY_ACTIVE_HIGH = false;

// ---------------- AS5600 ----------------
const uint8_t AS5600_ADDR    = 0x36;
const uint8_t ANGLE_HIGH_REG = 0x0C;

// ---------------- CONTROL SETTINGS ----------------
uint8_t travelPwm = 120;      // user-adjustable PWM command
int8_t travelDirection = 1;   // +1 forward, -1 reverse
float targetAngleDeg = 0.0f;
bool targetAngleValid = false;

float alignEngageDeg = 1.2f;     // start correcting once error exceeds this
float alignReleaseDeg = 0.4f;    // stop correcting only after error settles below this
float alignKp = 12.0f;
uint8_t alignMinPwm = 90;
uint8_t alignMaxPwm = 210;
int8_t alignSign = -1;
float angleFilterAlpha = 0.40f;  // 0..1, lower = smoother but slower
uint8_t alignRampStep = 20;      // max PWM change per control update

const unsigned long DRIVE_CONTROL_MS = 50UL;
const unsigned long TELEMETRY_MS = 100UL;

// ---------------- DEBUG / SAFETY ----------------
const unsigned long MANUAL_COMMAND_TIMEOUT_MS = 1500UL;
unsigned long lastManualCommandMs = 0UL;

// ---------------- WATER CONTROL ----------------
const unsigned long FULL_OPEN_TIME_MS = 2600UL;
const unsigned long STEP_TIME_MS = 260UL;
const unsigned long VALVE_DEADTIME_MS = 300UL;
const float STEP_PERCENT = 10.0f;    // estimated position change per step
float valvePosition = 0.0f;          // 0=open, 100=closed (estimated)
bool pumpRunning = false;

// ---------------- DEMO MODE ----------------
// Soil moisture is measured on the Pi, so the Pi decides when the threshold
// is crossed and sends DEMO_START. The Nano owns the actual sequence.
const float DEMO_TARGET_OPEN_PCT = 60.0f;        // requested final valve openness
const float DEMO_TARGET_CLOSED_PCT = 40.0f;      // internal position scale: 0=open, 100=closed
const unsigned long DEMO_PUMP_SETTLE_MS = 1200UL;
const unsigned long DEMO_VALVE_STEP_INTERVAL_MS = 1500UL;

enum MotionProfile : uint8_t {
  MOTION_SPEED = 0,        // continuous motion (user's normal/speed mode)
  MOTION_TRADITIONAL = 1   // 5s move, 7.5s pause irrigation crawl
};

const unsigned long TRADITIONAL_MOVE_MS = 5000UL;
const unsigned long TRADITIONAL_PAUSE_MS = 7500UL;
MotionProfile motionProfile = MOTION_SPEED;
bool traditionalMovePhase = true;
unsigned long motionPhaseStartMs = 0UL;

// ---------------- STATE ----------------
enum MotorMode : uint8_t {
  MOTOR_MODE_IDLE = 0,
  MOTOR_MODE_MANUAL = 1,
  MOTOR_MODE_AUTO = 2
};

MotorMode motorMode = MOTOR_MODE_IDLE;

int16_t m1Cmd = 0;
int16_t m2Cmd = 0;
bool motorsEnabled = false;
float lastAngleErrorDeg = 0.0f;
int16_t lastTravelCmd = 0;
int16_t lastAlignCmd = 0;
bool alignActive = false;
float filteredAngleErrorDeg = 0.0f;

// ---------------- VALVE STATE MACHINE ----------------
enum ValveAction : uint8_t {
  VALVE_IDLE,
  VALVE_WAIT_OPEN,
  VALVE_WAIT_CLOSE,
  VALVE_OPENING,
  VALVE_CLOSING
};

ValveAction valveAction = VALVE_IDLE;
unsigned long valveActionStartMs = 0UL;
unsigned long valveMoveDurationMs = 0UL;


enum DemoState : uint8_t {
  DEMO_IDLE = 0,
  DEMO_FORCE_OPEN = 1,
  DEMO_PUMP_SETTLE = 2,
  DEMO_THROTTLE = 3,
  DEMO_DRIVE = 4
};

DemoState demoState = DEMO_IDLE;
bool demoActive = false;
int8_t demoNextDirection = 1;   // +1 FWD, -1 REV
unsigned long demoStateStartMs = 0UL;
unsigned long demoLastStepMs = 0UL;

// ---------------- SERIAL CMD BUFFER ----------------
char cmdBuf[64];
uint8_t cmdPos = 0;

// ============================================================
// LOW LEVEL HELPERS
// ============================================================
static inline void setRelayPin(uint8_t pin, bool on, bool activeHigh) {
  digitalWrite(pin, on ? (activeHigh ? HIGH : LOW) : (activeHigh ? LOW : HIGH));
}

void allValveOff() {
  setRelayPin(RELAY_OPEN_PIN, false, VALVE_RELAY_ACTIVE_HIGH);
  setRelayPin(RELAY_CLOSE_PIN, false, VALVE_RELAY_ACTIVE_HIGH);
}

void pumpOff() {
  setRelayPin(RELAY_PUMP_PIN, false, PUMP_RELAY_ACTIVE_HIGH);
  pumpRunning = false;
}

void pumpOn() {
  setRelayPin(RELAY_PUMP_PIN, true, PUMP_RELAY_ACTIVE_HIGH);
  pumpRunning = true;
}

void enableDrivers() {
  digitalWrite(M1_REN, HIGH);
  digitalWrite(M1_LEN, HIGH);
  digitalWrite(M2_REN, HIGH);
  digitalWrite(M2_LEN, HIGH);
}

void stopBothMotors() {
  analogWrite(M1_RPWM, 0);
  analogWrite(M1_LPWM, 0);
  analogWrite(M2_RPWM, 0);
  analogWrite(M2_LPWM, 0);
}

void setMotorSigned(uint8_t rpwmPin, uint8_t lpwmPin, int16_t cmd) {
  cmd = constrain(cmd, -255, 255);

  if (cmd > 0) {
    analogWrite(rpwmPin, cmd);
    analogWrite(lpwmPin, 0);
  } else if (cmd < 0) {
    analogWrite(rpwmPin, 0);
    analogWrite(lpwmPin, -cmd);
  } else {
    analogWrite(rpwmPin, 0);
    analogWrite(lpwmPin, 0);
  }
}

void applyMotorCommands() {
  if (!motorsEnabled) {
    stopBothMotors();
    return;
  }
  setMotorSigned(M1_RPWM, M1_LPWM, m1Cmd);
  setMotorSigned(M2_RPWM, M2_LPWM, m2Cmd);
}

void stopMotion() {
  motorsEnabled = false;
  m1Cmd = 0;
  m2Cmd = 0;
  lastTravelCmd = 0;
  lastAlignCmd = 0;
  lastAngleErrorDeg = 0.0f;
  alignActive = false;
  filteredAngleErrorDeg = 0.0f;
  resetMotionProfileCycle();
  applyMotorCommands();
}

static inline uint8_t lim1Hit() { return digitalRead(LIM1_PIN) == LOW ? 1 : 0; }
static inline uint8_t lim2Hit() { return digitalRead(LIM2_PIN) == LOW ? 1 : 0; }

void printMode(MotorMode mode) {
  switch (mode) {
    case MOTOR_MODE_MANUAL: Serial.print(F("MANUAL")); break;
    case MOTOR_MODE_AUTO:   Serial.print(F("AUTO"));   break;
    default:                Serial.print(F("IDLE"));   break;
  }
}

void printMotionProfile(MotionProfile profile) {
  switch (profile) {
    case MOTION_TRADITIONAL: Serial.print(F("TRADITIONAL")); break;
    default:                 Serial.print(F("SPEED")); break;
  }
}

void resetMotionProfileCycle() {
  traditionalMovePhase = true;
  motionPhaseStartMs = 0UL;
}

bool motionWindowActive(unsigned long now) {
  if (motionProfile == MOTION_SPEED) return true;

  if (motionPhaseStartMs == 0UL) {
    motionPhaseStartMs = now;
    traditionalMovePhase = true;
  }

  if (traditionalMovePhase) {
    if (now - motionPhaseStartMs >= TRADITIONAL_MOVE_MS) {
      traditionalMovePhase = false;
      motionPhaseStartMs = now;
    }
  } else {
    if (now - motionPhaseStartMs >= TRADITIONAL_PAUSE_MS) {
      traditionalMovePhase = true;
      motionPhaseStartMs = now;
    }
  }

  return traditionalMovePhase;
}

// ============================================================
// AS5600
// ============================================================
bool readAS5600Raw(uint16_t &raw) {
  Wire.beginTransmission(AS5600_ADDR);
  Wire.write(ANGLE_HIGH_REG);
  if (Wire.endTransmission(false) != 0) return false;

  uint8_t got = Wire.requestFrom(AS5600_ADDR, (uint8_t)2);
  if (got < 2) return false;

  uint8_t hi = Wire.read();
  uint8_t lo = Wire.read();
  raw = (((uint16_t)hi << 8) | lo) & 0x0FFF;
  return true;
}

float readAngleDeg() {
  uint16_t raw = 0;
  if (!readAS5600Raw(raw)) return -1.0f;
  return (raw * 360.0f) / 4096.0f;
}

float normalizeAngle(float angle) {
  while (angle >= 360.0f) angle -= 360.0f;
  while (angle < 0.0f) angle += 360.0f;
  return angle;
}

float shortestAngleError(float target, float current) {
  float error = target - current;
  while (error >= 180.0f) error -= 360.0f;
  while (error < -180.0f) error += 360.0f;
  return error;
}

int16_t computeTravelCmd() {
  // Directional limits only:
  // LIM1 stops forward travel, LIM2 stops reverse travel.
  if (travelDirection > 0 && lim1Hit()) return 0;
  if (travelDirection < 0 && lim2Hit()) return 0;
  return (travelDirection > 0) ? travelPwm : -travelPwm;
}

int16_t rampToward(int16_t currentCmd, int16_t targetCmd, uint8_t step) {
  if (targetCmd > currentCmd + step) return currentCmd + step;
  if (targetCmd < currentCmd - step) return currentCmd - step;
  return targetCmd;
}

int16_t computeAlignCmd(float errorDeg) {
  float absErr = fabs(errorDeg);

  if (alignActive) {
    if (absErr <= alignReleaseDeg) alignActive = false;
  } else {
    if (absErr >= alignEngageDeg) alignActive = true;
  }

  if (!alignActive) return 0;

  int16_t pwm = (int16_t)(alignKp * absErr);
  if (pwm < alignMinPwm) pwm = alignMinPwm;
  if (pwm > alignMaxPwm) pwm = alignMaxPwm;

  return (errorDeg > 0.0f) ? (alignSign * pwm) : (alignSign * -pwm);
}

void captureTargetFromCurrentAngle() {
  float angle = readAngleDeg();
  if (angle < 0.0f) {
    Serial.println(F("ERR,ANGLE_UNAVAILABLE"));
    return;
  }
  targetAngleDeg = normalizeAngle(angle);
  targetAngleValid = true;
  Serial.print(F("STATUS,TARGET_CAPTURED,"));
  Serial.println(targetAngleDeg, 2);
}

void updateAutoDrive() {
  static unsigned long lastDriveMs = 0UL;
  unsigned long now = millis();
  if (now - lastDriveMs < DRIVE_CONTROL_MS) return;
  lastDriveMs = now;

  if (motorMode != MOTOR_MODE_AUTO) return;

  if (!motionWindowActive(now)) {
    m1Cmd = 0;
    m2Cmd = 0;
    lastTravelCmd = 0;
    lastAlignCmd = 0;
    motorsEnabled = false;
    applyMotorCommands();
    return;
  }

  float angle = readAngleDeg();
  if (angle < 0.0f) {
    motorMode = MOTOR_MODE_IDLE;
    stopMotion();
    Serial.println(F("ERR,ANGLE_LOST_AUTO_STOP"));
    return;
  }

  if (!targetAngleValid) {
    targetAngleDeg = normalizeAngle(angle);
    targetAngleValid = true;
  }

  float rawErrorDeg = shortestAngleError(targetAngleDeg, angle);
  filteredAngleErrorDeg = (angleFilterAlpha * rawErrorDeg) + ((1.0f - angleFilterAlpha) * filteredAngleErrorDeg);
  lastAngleErrorDeg = rawErrorDeg;
  lastTravelCmd = computeTravelCmd();
  int16_t targetAlignCmd = computeAlignCmd(filteredAngleErrorDeg);
  lastAlignCmd = rampToward(lastAlignCmd, targetAlignCmd, alignRampStep);

  m1Cmd = lastTravelCmd;
  m2Cmd = lastAlignCmd;
  motorsEnabled = (m1Cmd != 0 || m2Cmd != 0);
  applyMotorCommands();
}


void failSafeCheck() {
  if (motorMode == MOTOR_MODE_MANUAL && motorsEnabled &&
      (millis() - lastManualCommandMs > MANUAL_COMMAND_TIMEOUT_MS)) {
    motorMode = MOTOR_MODE_IDLE;
    stopMotion();
    Serial.println(F("STATUS,TIMEOUT_STOP"));
  }
}

// ============================================================
// MANUAL WATER CONTROL
// ============================================================
static inline bool valveBusy() {
  return valveAction != VALVE_IDLE;
}

void startValveMoveOpen(unsigned long moveMs) {
  allValveOff();
  valveAction = VALVE_WAIT_OPEN;
  valveActionStartMs = millis();
  valveMoveDurationMs = moveMs;
}

void startValveMoveClose(unsigned long moveMs) {
  allValveOff();
  valveAction = VALVE_WAIT_CLOSE;
  valveActionStartMs = millis();
  valveMoveDurationMs = moveMs;
}

void updateValveMotion() {
  unsigned long now = millis();

  switch (valveAction) {
    case VALVE_IDLE:
      break;

    case VALVE_WAIT_OPEN:
      if (now - valveActionStartMs >= VALVE_DEADTIME_MS) {
        setRelayPin(RELAY_OPEN_PIN, true, VALVE_RELAY_ACTIVE_HIGH);
        valveAction = VALVE_OPENING;
        valveActionStartMs = now;
      }
      break;

    case VALVE_WAIT_CLOSE:
      if (now - valveActionStartMs >= VALVE_DEADTIME_MS) {
        setRelayPin(RELAY_CLOSE_PIN, true, VALVE_RELAY_ACTIVE_HIGH);
        valveAction = VALVE_CLOSING;
        valveActionStartMs = now;
      }
      break;

    case VALVE_OPENING:
      if (now - valveActionStartMs >= valveMoveDurationMs) {
        allValveOff();
        valveAction = VALVE_IDLE;
      }
      break;

    case VALVE_CLOSING:
      if (now - valveActionStartMs >= valveMoveDurationMs) {
        allValveOff();
        valveAction = VALVE_IDLE;
      }
      break;
  }
}

void openValveStep() {
  if (valveBusy()) return;
  startValveMoveOpen(STEP_TIME_MS);
  valvePosition -= STEP_PERCENT;
  if (valvePosition < 0.0f) valvePosition = 0.0f;
}

void closeValveStep() {
  if (valveBusy()) return;
  startValveMoveClose(STEP_TIME_MS);
  valvePosition += STEP_PERCENT;
  if (valvePosition > 100.0f) valvePosition = 100.0f;
}

void closeValveByPercent(float pct) {
  if (valveBusy() || pct <= 0.0f) return;
  unsigned long moveMs = (unsigned long)((pct * STEP_TIME_MS / STEP_PERCENT) + 0.5f);
  if (moveMs < 1UL) moveMs = 1UL;
  startValveMoveClose(moveMs);
  valvePosition += pct;
  if (valvePosition > 100.0f) valvePosition = 100.0f;
}

void forceOpenValve() {
  if (valveBusy()) return;
  startValveMoveOpen(FULL_OPEN_TIME_MS);
  valvePosition = 0.0f;
}

void stopValveMotion() {
  allValveOff();
  valveAction = VALVE_IDLE;
}

static inline void printDemoState(DemoState state) {
  switch (state) {
    case DEMO_FORCE_OPEN:  Serial.print(F("OPEN")); break;
    case DEMO_PUMP_SETTLE: Serial.print(F("PUMP")); break;
    case DEMO_THROTTLE:    Serial.print(F("VALVE")); break;
    case DEMO_DRIVE:       Serial.print(F("DRIVE")); break;
    default:               Serial.print(F("IDLE")); break;
  }
}

void resetDemoState() {
  demoActive = false;
  demoState = DEMO_IDLE;
  demoStateStartMs = 0UL;
  demoLastStepMs = 0UL;
  targetAngleValid = false;
}

void abortDemo(bool stopWater) {
  if (stopWater) {
    pumpOff();
    stopValveMotion();
  }
  motorMode = MOTOR_MODE_IDLE;
  stopMotion();
  resetDemoState();
}

void startDemoSequence() {
  abortDemo(true);

  float angle = readAngleDeg();
  if (angle >= 0.0f) {
    targetAngleDeg = normalizeAngle(angle);
    targetAngleValid = true;
  }

  travelDirection = demoNextDirection;
  resetMotionProfileCycle();
  forceOpenValve();
  demoActive = true;
  demoState = DEMO_FORCE_OPEN;
  demoStateStartMs = millis();
  demoLastStepMs = 0UL;
  Serial.println(F("STATUS,DEMO_START"));
}

void completeDemoFromLimit() {
  uint8_t hit1 = lim1Hit();
  uint8_t hit2 = lim2Hit();

  if (hit1) demoNextDirection = -1;
  if (hit2) demoNextDirection = 1;

  abortDemo(true);

  Serial.print(F("STATUS,DEMO_COMPLETE,"));
  if (hit1) Serial.print(F("L1"));
  else if (hit2) Serial.print(F("L2"));
  else Serial.print(F("NONE"));
  Serial.print(',');
  Serial.println(demoNextDirection > 0 ? F("FWD") : F("REV"));
}

void updateDemoMode() {
  if (!demoActive) return;

  unsigned long now = millis();

  switch (demoState) {
    case DEMO_IDLE:
      break;

    case DEMO_FORCE_OPEN:
      if (!valveBusy()) {
        pumpOn();
        demoState = DEMO_PUMP_SETTLE;
        demoStateStartMs = now;
        Serial.println(F("STATUS,DEMO_PUMP_ON"));
      }
      break;

    case DEMO_PUMP_SETTLE:
      if (now - demoStateStartMs >= DEMO_PUMP_SETTLE_MS) {
        demoState = DEMO_THROTTLE;
        demoLastStepMs = 0UL;
        Serial.println(F("STATUS,DEMO_VALVE_STAGING"));
      }
      break;

    case DEMO_THROTTLE:
      if (valveBusy()) break;

      if (valvePosition + 0.1f < DEMO_TARGET_CLOSED_PCT) {
        if (demoLastStepMs == 0UL || (now - demoLastStepMs >= DEMO_VALVE_STEP_INTERVAL_MS)) {
          float remainingPct = DEMO_TARGET_CLOSED_PCT - valvePosition;
          if (remainingPct > STEP_PERCENT) closeValveStep();
          else closeValveByPercent(remainingPct);
          demoLastStepMs = now;
        }
      } else {
        float angle = readAngleDeg();
        if (angle < 0.0f) {
          Serial.println(F("ERR,DEMO_ANGLE_UNAVAILABLE"));
          abortDemo(true);
          return;
        }
        targetAngleDeg = normalizeAngle(angle);
        targetAngleValid = true;
        travelDirection = demoNextDirection;
        resetMotionProfileCycle();
        motorMode = MOTOR_MODE_AUTO;
        motorsEnabled = true;
        demoState = DEMO_DRIVE;
        Serial.println(F("STATUS,DEMO_DRIVE_ON"));
      }
      break;

    case DEMO_DRIVE:
      // Directional limit behavior in demo:
      // LIM1 ends a forward run, LIM2 ends a reverse run.
      if ((travelDirection > 0 && lim1Hit()) || (travelDirection < 0 && lim2Hit())) {
        completeDemoFromLimit();
      }
      break;
  }
}

void cancelDemoForManualControl() {
  if (demoActive) {
    abortDemo(true);
    Serial.println(F("STATUS,DEMO_ABORTED_MANUAL"));
  }
}

// ============================================================
// SERIAL / STATUS / TELEMETRY
// ============================================================
void sendStatusLine() {
  float angle = readAngleDeg();

  Serial.print(F("ANGLE:"));
  if (angle < 0.0f) Serial.print(F("N/A"));
  else Serial.print(angle, 1);

  Serial.print(F(",PSI:N/A"));
  Serial.print(F(",LIM1:")); Serial.print(lim1Hit());
  Serial.print(F(",LIM2:")); Serial.print(lim2Hit());
  Serial.print(F(",PUMP:")); Serial.print(pumpRunning ? 1 : 0);
  Serial.print(F(",PCTRL:0"));
  Serial.print(F(",VALVE:")); Serial.print(valvePosition, 1);
  Serial.print(F(",DRIVE:")); Serial.print(motorMode == MOTOR_MODE_AUTO ? 1 : 0);
  Serial.print(F(",DIR:")); Serial.print(travelDirection > 0 ? F("FWD") : F("REV"));
  Serial.print(F(",SPEED:")); Serial.print(travelPwm);
  Serial.print(F(",TARGET:"));
  if (targetAngleValid) Serial.print(targetAngleDeg, 2);
  else Serial.print(F("N/A"));
  Serial.print(F(",ERR:"));
  if (motorMode == MOTOR_MODE_AUTO && angle >= 0.0f && targetAngleValid) Serial.print(lastAngleErrorDeg, 2);
  else Serial.print(F("N/A"));
  Serial.print(F(",TRAVEL:")); Serial.print(lastTravelCmd);
  Serial.print(F(",ALIGN:")); Serial.print(lastAlignCmd);
  Serial.print(F(",MODE:")); printMode(motorMode);
  Serial.print(F(",MOTION:")); printMotionProfile(motionProfile);
  Serial.print(F(",MPHASE:")); Serial.print(motionProfile == MOTION_SPEED ? F("MOVE") : (traditionalMovePhase ? F("MOVE") : F("PAUSE")));
  Serial.print(F(",DEMO:")); printDemoState(demoState);
  Serial.print(F(",DEMONEXT:")); Serial.print(demoNextDirection > 0 ? F("FWD") : F("REV"));
  Serial.println();
}

void sendTelemetry() {
  float angle = readAngleDeg();

  Serial.print(F("TEL,"));
  Serial.print(millis());
  Serial.print(',');
  Serial.print(m1Cmd);
  Serial.print(',');
  Serial.print(m2Cmd);
  Serial.print(',');
  Serial.print(motorsEnabled ? 1 : 0);
  Serial.print(',');
  if (angle < 0.0f) Serial.print(-1.0f, 1);
  else Serial.print(angle, 1);
  Serial.print(',');
  Serial.print(lim1Hit());
  Serial.print(',');
  Serial.print(lim2Hit());
  Serial.print(F(",0,0,0.0,0.0,"));
  Serial.print(motorMode == MOTOR_MODE_AUTO ? 1 : 0);
  Serial.print(',');
  Serial.print(travelDirection);
  Serial.print(',');
  Serial.print(travelPwm);
  Serial.print(',');
  if (targetAngleValid) Serial.print(targetAngleDeg, 2);
  else Serial.print(-1.0f, 2);
  Serial.print(',');
  if (motorMode == MOTOR_MODE_AUTO && angle >= 0.0f && targetAngleValid) Serial.print(lastAngleErrorDeg, 2);
  else Serial.print(0.0f, 2);
  Serial.print(',');
  Serial.print(lastTravelCmd);
  Serial.print(',');
  Serial.print(lastAlignCmd);
  Serial.print(',');
  Serial.print(pumpRunning ? 1 : 0);
  Serial.print(F(",0,"));
  Serial.print(valvePosition, 1);
  Serial.print(',');
  printMode(motorMode);
  Serial.print(',');
  Serial.print(demoActive ? 1 : 0);
  Serial.print(',');
  Serial.print((int)demoState);
  Serial.print(',');
  Serial.print(demoNextDirection);
  Serial.print(',');
  printMotionProfile(motionProfile);
  Serial.print(',');
  Serial.print(motionProfile == MOTION_SPEED ? F("MOVE") : (traditionalMovePhase ? F("MOVE") : F("PAUSE")));
  Serial.println();
}

void printHelp() {
  Serial.println(F("STATUS,READY"));
  Serial.println(F("STATUS,CMDS: HELP STATUS ALL_STOP STOP ZERO DRIVE_ON DRIVE_OFF SPEED,<0-255> DIR,FWD|REV|TOGGLE CAPTURE_TARGET TARGET,<deg> DEMO_START DEMO_ABORT DEMO_DIR,FWD|REV|TOGGLE PUMP_ON PUMP_OFF OPEN_STEP CLOSE_STEP FORCE_OPEN VALVE_STOP OPEN_MS,<ms> CLOSE_MS,<ms> SET,m1,m2 MOTION,SPEED|TRADITIONAL|TOGGLE"));
  Serial.println(F("STATUS,MODE: MANUAL_WATER_ONLY"));
}

static inline bool startsWith(const char *s, const char *prefix) {
  while (*prefix) {
    if (*s++ != *prefix++) return false;
  }
  return true;
}

void processCommand(char *line) {
  if (line[0] == '\0') return;

  // -------- General commands --------
  if (strcmp(line, "HELP") == 0) {
    printHelp();
    return;
  }

  if (strcmp(line, "STATUS") == 0) {
    sendStatusLine();
    return;
  }

  cancelDemoForManualControl();

  if (strcmp(line, "ALL_STOP") == 0) {
    motorMode = MOTOR_MODE_IDLE;
    stopMotion();
    pumpOff();
    stopValveMotion();
    Serial.println(F("STATUS,ALL_STOPPED"));
    return;
  }

  cancelDemoForManualControl();

  if (strcmp(line, "STOP") == 0) {
    motorMode = MOTOR_MODE_IDLE;
    stopMotion();
    Serial.println(F("STATUS,MOTORS_STOPPED"));
    return;
  }

  if (strcmp(line, "ZERO") == 0) {
    Serial.println(F("STATUS,COUNTS_ZEROED"));
    return;
  }

  if (strcmp(line, "DEMO_START") == 0) {
    startDemoSequence();
    return;
  }

  if (strcmp(line, "DEMO_ABORT") == 0) {
    abortDemo(true);
    Serial.println(F("STATUS,DEMO_ABORT"));
    return;
  }

  if (startsWith(line, "DEMO_DIR,")) {
    char *which = line + 9;
    if (strcmp(which, "FWD") == 0 || strcmp(which, "FORWARD") == 0) {
      demoNextDirection = 1;
      Serial.println(F("STATUS,DEMO_DIR_FWD"));
      return;
    }
    if (strcmp(which, "REV") == 0 || strcmp(which, "REVERSE") == 0) {
      demoNextDirection = -1;
      Serial.println(F("STATUS,DEMO_DIR_REV"));
      return;
    }
    if (strcmp(which, "TOGGLE") == 0) {
      demoNextDirection = -demoNextDirection;
      Serial.print(F("STATUS,DEMO_DIR_"));
      Serial.println(demoNextDirection > 0 ? F("FWD") : F("REV"));
      return;
    }
    Serial.println(F("ERR,BAD_DEMO_DIR"));
    return;
  }

  // -------- Production drive commands --------
  cancelDemoForManualControl();

  if (strcmp(line, "DRIVE_ON") == 0) {
    if (!targetAngleValid) {
      float angle = readAngleDeg();
      if (angle < 0.0f) {
        Serial.println(F("ERR,ANGLE_UNAVAILABLE"));
        return;
      }
      targetAngleDeg = normalizeAngle(angle);
      targetAngleValid = true;
    }
    resetMotionProfileCycle();
    motorMode = MOTOR_MODE_AUTO;
    motorsEnabled = true;
    Serial.println(F("STATUS,DRIVE_ON"));
    return;
  }

  cancelDemoForManualControl();

  if (strcmp(line, "DRIVE_OFF") == 0) {
    motorMode = MOTOR_MODE_IDLE;
    stopMotion();
    Serial.println(F("STATUS,DRIVE_OFF"));
    return;
  }

  cancelDemoForManualControl();

  if (strcmp(line, "CAPTURE_TARGET") == 0) {
    captureTargetFromCurrentAngle();
    return;
  }

  cancelDemoForManualControl();

  if (startsWith(line, "TARGET,")) {
    float target = atof(line + 7);
    targetAngleDeg = normalizeAngle(target);
    targetAngleValid = true;
    Serial.print(F("STATUS,TARGET_SET,"));
    Serial.println(targetAngleDeg, 2);
    return;
  }

  cancelDemoForManualControl();

  if (startsWith(line, "SPEED,")) {
    int pwm = atoi(line + 6);
    travelPwm = constrain(pwm, 0, 255);
    Serial.print(F("STATUS,SPEED_SET,"));
    Serial.println(travelPwm);
    return;
  }

  cancelDemoForManualControl();

  if (startsWith(line, "DIR,")) {
    char *which = line + 4;
    if (strcmp(which, "FWD") == 0 || strcmp(which, "FORWARD") == 0) {
      travelDirection = 1;
      Serial.println(F("STATUS,DIR_FWD"));
      return;
    }
    if (strcmp(which, "REV") == 0 || strcmp(which, "REVERSE") == 0) {
      travelDirection = -1;
      Serial.println(F("STATUS,DIR_REV"));
      return;
    }
    if (strcmp(which, "TOGGLE") == 0) {
      travelDirection = -travelDirection;
      Serial.print(F("STATUS,DIR_"));
      Serial.println(travelDirection > 0 ? F("FWD") : F("REV"));
      return;
    }
    Serial.println(F("ERR,BAD_DIR"));
    return;
  }

  cancelDemoForManualControl();

  if (startsWith(line, "MOTION,")) {
    char *which = line + 7;
    if (strcmp(which, "SPEED") == 0 || strcmp(which, "NORMAL") == 0) {
      motionProfile = MOTION_SPEED;
      resetMotionProfileCycle();
      Serial.println(F("STATUS,MOTION_SPEED"));
      return;
    }
    if (strcmp(which, "TRADITIONAL") == 0 || strcmp(which, "TRAD") == 0 || strcmp(which, "CRAWL") == 0) {
      motionProfile = MOTION_TRADITIONAL;
      resetMotionProfileCycle();
      Serial.println(F("STATUS,MOTION_TRADITIONAL"));
      return;
    }
    if (strcmp(which, "TOGGLE") == 0) {
      motionProfile = (motionProfile == MOTION_SPEED) ? MOTION_TRADITIONAL : MOTION_SPEED;
      resetMotionProfileCycle();
      Serial.print(F("STATUS,MOTION_"));
      printMotionProfile(motionProfile);
      Serial.println();
      return;
    }
    Serial.println(F("ERR,BAD_MOTION"));
    return;
  }

  // -------- Manual water commands --------
  if (strcmp(line, "START_PCTRL") == 0 || strcmp(line, "STOP_PCTRL") == 0 || startsWith(line, "THRESH,")) {
    Serial.println(F("ERR,MANUAL_WATER_ONLY"));
    return;
  }

  cancelDemoForManualControl();

  if (strcmp(line, "PUMP_ON") == 0) {
    pumpOn();
    Serial.println(F("STATUS,PUMP_ON"));
    return;
  }

  cancelDemoForManualControl();

  if (strcmp(line, "PUMP_OFF") == 0) {
    pumpOff();
    Serial.println(F("STATUS,PUMP_OFF"));
    return;
  }

  cancelDemoForManualControl();

  if (strcmp(line, "OPEN_STEP") == 0) {
    openValveStep();
    Serial.println(F("STATUS,OPEN_STEP_CMD"));
    return;
  }

  cancelDemoForManualControl();

  if (strcmp(line, "CLOSE_STEP") == 0) {
    closeValveStep();
    Serial.println(F("STATUS,CLOSE_STEP_CMD"));
    return;
  }

  cancelDemoForManualControl();

  if (strcmp(line, "FORCE_OPEN") == 0) {
    forceOpenValve();
    Serial.println(F("STATUS,FORCE_OPEN_CMD"));
    return;
  }

  cancelDemoForManualControl();

  if (strcmp(line, "VALVE_STOP") == 0) {
    stopValveMotion();
    Serial.println(F("STATUS,VALVE_STOPPED"));
    return;
  }

  cancelDemoForManualControl();

  if (startsWith(line, "OPEN_MS,")) {
    unsigned long moveMs = strtoul(line + 8, NULL, 10);
    if (!valveBusy() && moveMs > 0UL) {
      startValveMoveOpen(moveMs);
      Serial.print(F("STATUS,OPEN_MS,"));
      Serial.println(moveMs);
      return;
    }
    Serial.println(F("ERR,VALVE_BUSY_OR_BAD_MS"));
    return;
  }

  cancelDemoForManualControl();

  if (startsWith(line, "CLOSE_MS,")) {
    unsigned long moveMs = strtoul(line + 9, NULL, 10);
    if (!valveBusy() && moveMs > 0UL) {
      startValveMoveClose(moveMs);
      Serial.print(F("STATUS,CLOSE_MS,"));
      Serial.println(moveMs);
      return;
    }
    Serial.println(F("ERR,VALVE_BUSY_OR_BAD_MS"));
    return;
  }

  // -------- Direct manual motor command (debug only) --------
  cancelDemoForManualControl();

  if (strcmp(line, "ENABLE") == 0) {
    motorMode = MOTOR_MODE_MANUAL;
    lastManualCommandMs = millis();
    motorsEnabled = (m1Cmd != 0 || m2Cmd != 0);
    applyMotorCommands();
    Serial.println(F("STATUS,MANUAL_ENABLED"));
    return;
  }

  cancelDemoForManualControl();

  if (startsWith(line, "SET,")) {
    char *p1 = strchr(line, ',');
    if (p1) {
      char *p2 = strchr(p1 + 1, ',');
      if (p2) {
        *p2 = '\0';
        int newM1 = atoi(p1 + 1);
        int newM2 = atoi(p2 + 1);
        m1Cmd = constrain(newM1, -255, 255);
        m2Cmd = constrain(newM2, -255, 255);
        motorMode = MOTOR_MODE_MANUAL;
        motorsEnabled = (m1Cmd != 0 || m2Cmd != 0);
        lastManualCommandMs = millis();
        lastTravelCmd = m1Cmd;
        lastAlignCmd = m2Cmd;
        applyMotorCommands();
        Serial.print(F("ACK,SET,"));
        Serial.print(m1Cmd);
        Serial.print(',');
        Serial.println(m2Cmd);
        return;
      }
    }
  }

  Serial.print(F("ERR,BAD_CMD,"));
  Serial.println(line);
}

void pollSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();

    if (c == '\r') continue;

    if (c == '\n') {
      cmdBuf[cmdPos] = '\0';
      processCommand(cmdBuf);
      cmdPos = 0;
      cmdBuf[0] = '\0';
      return;
    }

    if (cmdPos < sizeof(cmdBuf) - 1) {
      cmdBuf[cmdPos++] = c;
      cmdBuf[cmdPos] = '\0';
    } else {
      cmdPos = 0;
      cmdBuf[0] = '\0';
      Serial.println(F("ERR,CMD_TOO_LONG"));
      return;
    }
  }
}

// ============================================================
// SETUP / LOOP
// ============================================================
void setup() {
  pinMode(M1_RPWM, OUTPUT);
  pinMode(M1_LPWM, OUTPUT);
  pinMode(M1_REN, OUTPUT);
  pinMode(M1_LEN, OUTPUT);

  pinMode(M2_RPWM, OUTPUT);
  pinMode(M2_LPWM, OUTPUT);
  pinMode(M2_REN, OUTPUT);
  pinMode(M2_LEN, OUTPUT);

  pinMode(LIM1_PIN, INPUT_PULLUP);
  pinMode(LIM2_PIN, INPUT_PULLUP);

  pinMode(RELAY_OPEN_PIN, OUTPUT);
  pinMode(RELAY_CLOSE_PIN, OUTPUT);
  pinMode(RELAY_PUMP_PIN, OUTPUT);

  allValveOff();
  pumpOff();

  Wire.begin();      // Nano SDA=A4, SCL=A5
  enableDrivers();
  stopMotion();

  Serial.begin(115200);
  delay(300);

  printHelp();
}

void loop() {
  pollSerial();
  updateValveMotion();
  updateDemoMode();
  updateAutoDrive();
  failSafeCheck();

  static unsigned long lastTelemetryMs = 0UL;
  unsigned long now = millis();
  if (now - lastTelemetryMs >= TELEMETRY_MS) {
    lastTelemetryMs += TELEMETRY_MS;
    sendTelemetry();
  }
}
