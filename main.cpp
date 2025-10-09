#include <Arduino.h>
#include <math.h>
#include <ADS126X.h>
#include <SPI.h>
#include <EEPROM.h>

// Global variables
ADS126X adc;
const int chip_select = 1;
const int drdy_pin = 2;
const int reset_pin = 3;

// ADC settings
uint8_t current_adc_rate = ADS126X_RATE_19200;
uint8_t current_adc_gain = ADS126X_GAIN_1;
uint8_t current_adc_filter = ADS126X_SINC3;  // Default to SINC3 filter
uint8_t current_dithering = 4;               // Default to 4x oversampling
int num_channels = 3;

// ADC throughput verification
struct ADCThroughputMonitor {
  uint32_t deadline_misses;
  uint32_t max_conversion_time_us;
  uint32_t min_conversion_time_us;
  uint32_t total_conversions;
  bool throughput_warning_sent;
} adc_monitor;

// Streaming settings
volatile bool streaming = false;
float stream_rate = 100.0;
uint16_t sequence = 0;  // 16-bit sequence (0-65535)

// Session tracking for stitching
struct SessionTracker {
  uint32_t boot_id;      // Unique ID for this MCU boot cycle
  uint32_t stream_id;    // Unique ID for this streaming session
  bool session_header_sent;
} session_tracker;

// Serial buffer overflow protection with backpressure signaling
struct SerialBufferMonitor {
  uint32_t buffer_overflows;
  uint32_t last_overflow_time;
  uint32_t bytes_sent;
  uint32_t samples_skipped_due_to_overflow;
  bool overflow_warning_sent;
  uint32_t oflow_message_count;
  uint32_t last_oflow_message_time;
  uint32_t oflow_report_interval_ms;  // Report OFLOW every N ms
} serial_monitor;

// Output format options
bool compact_output = false;  // Use compact format to reduce buffer usage

// Sequence validation and recovery
struct SequenceValidator {
  uint16_t expected_sequence;
  uint32_t sequence_gaps_detected;
  uint32_t sequence_resets_detected;
  uint32_t last_validation_time;
  bool validation_enabled;
} seq_validator;

// Advanced timing system with PPS support
struct AdvancedTiming {
    // PPS Management
    const int PPS_PIN = 4;  // PPS input pin
    volatile bool pps_received;
    volatile unsigned long pps_micros;
    unsigned long last_pps_time;
    uint32_t pps_count;
    bool pps_valid;
    unsigned long pps_timeout_ms;
    
    // Timing Sources
    enum TimingSource {
        TIMING_PPS_ACTIVE = 0,      // GPS PPS working (±1μs)
        TIMING_PPS_HOLDOVER = 1,    // Recent PPS, using prediction (±10μs)
        TIMING_INTERNAL_CAL = 2,    // Internal osc with PPS calibration (±100μs)
        TIMING_INTERNAL_RAW = 3     // Raw internal (±1ms, emergency)
    } current_source;
    
    // Calibration Data
    float oscillator_calibration_ppm;   // PPM correction from PPS
    uint64_t cal_base_micros;          // MCU micros() when calibration established (64-bit)
    unsigned long cal_base_millis;      // millis() when calibration established
    uint32_t cal_sample_count;          // Samples since calibration
    bool calibration_valid;
    
    // Clock Reset Detection and Handling
    unsigned long last_micros;          // Last micros() reading for reset detection
    unsigned long last_millis;          // Last millis() reading
    uint32_t micros_wraparound_count;   // Count of micros() wraparounds
    uint64_t virtual_micros_offset;     // Offset to create continuous virtual time
    bool clock_reset_detected;          // Flag for recent reset
    unsigned long reset_detection_time; // When reset was detected
    
    // Enhanced Reset Recovery
    uint64_t pre_reset_virtual_time;    // Virtual time before reset
    unsigned long reset_recovery_samples; // Samples since reset
    bool timing_continuity_maintained;  // Whether we maintained timing through reset
    
    // Overflow Protection - NEW
    uint64_t reference_update_interval; // How often to update timing reference (samples)
    uint64_t last_reference_update_sample; // Sample index of last reference update
    uint64_t timing_base_virtual_micros; // Virtual micros when timing was established
    uint32_t reference_updates_count;    // Number of reference updates performed
    
    // Precision State (Modified for overflow protection)
  uint64_t sample_interval_us;        // Sample interval in microseconds
  double   effective_interval_us;     // PPS-disciplined effective interval (fractional)
  double   phase_acc_us;              // Fractional microsecond accumulator
  uint64_t next_sample_micros;        // Next scheduled sample time (virtual micros)
    uint64_t timing_base_micros;        // Timing base for sampling (now 64-bit)
  bool timing_established;
    unsigned long samples_generated;
    uint64_t sample_index;
    
    // Phase alignment (gentle nudge) to PPS after start
    bool started_on_pps;                 // Whether streaming started exactly at a PPS edge
    bool phase_nudge_applied;            // Whether we've already nudged once after PPS became available
    bool phase_alignment_active;         // Currently applying per-sample phase adjustment
    double phase_error_us;               // Total phase error to correct (signed)
    double per_sample_phase_adjust_us;   // Adjustment added per sample (signed)
    uint32_t phase_adjust_samples_remaining; // How many samples left to apply adjustment
    bool pps_phase_lock_enabled;          // Continuously lock phase to PPS when available
    
    // Synchronized start support
    bool sync_start_enabled;
    unsigned long sync_delay_ms;
    unsigned long sync_start_time;
    bool waiting_for_sync_start;
    uint64_t sync_start_target_us;   // Absolute virtual micros target for start
    // PPS-locked start support
    bool sync_on_pps;
    uint8_t pps_countdown;
    
    // Quality Metrics
    float timing_accuracy_us;       // Current estimated accuracy
    uint32_t pps_miss_count;       // Consecutive missed PPS
    unsigned long last_sync_time;   // Last successful sync
    uint32_t clock_resets_detected; // Total clock resets detected
    
    // Health beacon (1 Hz STAT line)
    unsigned long last_stat_time;   // Last STAT line sent
    uint32_t stat_interval_ms;      // STAT line interval (1000ms = 1Hz)
    
    // Temperature-aware calibration
    float temp_coefficient_ppm_per_c;  // PPM change per degree C
    float reference_temp_c;            // Reference temperature for calibration
    float current_temp_c;              // Current temperature
    bool temp_compensation_enabled;    // Enable temperature compensation
} advanced_timing;

// Channel definitions
int pos_pin1 = 0, neg_pin1 = 1;
int pos_pin2 = 2, neg_pin2 = 3;
int pos_pin3 = 4, neg_pin3 = 5;

// Command buffer
String cmdBuffer = "";

// Function declarations
void processLine(String line);
long readADC(int pos_pin, int neg_pin);
void setupAdvancedTiming();
void pps_interrupt();
void updateTimingSource();
void processPPS();
uint64_t getPreciseTimestamp();
uint64_t calculateCalibratedTimestamp(uint64_t current_micros);
void establishSamplingTiming();
void generatePreciseSample();
bool checkSyncStartTime();
const char* getTimingSourceName(int source);
bool detectClockReset();  // NEW: Clock reset detection
uint64_t getVirtualMicros();  // NEW: Continuous virtual time
void handleClockReset();  // NEW: Clock reset recovery
void updateTimingReference();
bool checkSerialBufferOverflow();
void outputDataWithOverflowProtection(uint16_t seq, uint64_t timestamp, int timing_source, float accuracy, long v1, long v2, long v3);
bool validateAndCorrectSequence(uint16_t& seq);
bool verifyADCThroughput();
void sendSessionHeader();
void clampOscillatorCalibration();
void sendHealthBeacon();
bool isRateChangeAllowed(float new_rate);
void saveOscillatorCalibration();
void loadOscillatorCalibration();
float readInternalTemperature();
void updateTemperatureCompensation();

void setup() {
  Serial1.begin(921600);  // INCREASED from 115200 to prevent buffer overflow (8x faster)
  Serial1.println("DEBUG:Starting Advanced ADS1263 with PPS Timing...");
  
  // Initialize serial buffer monitor
  serial_monitor.buffer_overflows = 0;
  serial_monitor.last_overflow_time = 0;
  serial_monitor.bytes_sent = 0;
  serial_monitor.samples_skipped_due_to_overflow = 0;
  serial_monitor.overflow_warning_sent = false;
  serial_monitor.oflow_message_count = 0;
  serial_monitor.last_oflow_message_time = 0;
  serial_monitor.oflow_report_interval_ms = 1000;  // Report OFLOW every 1 second
  
  // Initialize sequence validator
  seq_validator.expected_sequence = 0;
  seq_validator.sequence_gaps_detected = 0;
  seq_validator.sequence_resets_detected = 0;
  seq_validator.last_validation_time = 0;
  seq_validator.validation_enabled = true;
  
  // Initialize ADC throughput monitor
  adc_monitor.deadline_misses = 0;
  adc_monitor.max_conversion_time_us = 0;
  adc_monitor.min_conversion_time_us = 0;
  adc_monitor.total_conversions = 0;
  adc_monitor.throughput_warning_sent = false;
  
  // Initialize session tracker
  session_tracker.boot_id = millis();  // Use boot time as boot_id
  session_tracker.stream_id = 0;
  session_tracker.session_header_sent = false;
  
  setupAdvancedTiming();
  
  // Load stored oscillator calibration from EEPROM
  loadOscillatorCalibration();
  
  // Initialize SPI and ADC
  SPI.begin();
  SPI.beginTransaction(SPISettings(8000000, MSBFIRST, SPI_MODE1));
  
  pinMode(drdy_pin, INPUT_PULLUP);
  pinMode(reset_pin, OUTPUT);
  pinMode(chip_select, OUTPUT);
  
  // Reset ADC
  digitalWrite(reset_pin, HIGH);
  delay(100);
  digitalWrite(reset_pin, LOW);
  delay(100);
  digitalWrite(reset_pin, HIGH);
  delay(100);
  
  // Initialize ADC
  adc.begin(chip_select);
  adc.setRate(current_adc_rate);
  adc.setGain(current_adc_gain);
  adc.setFilter(current_adc_filter);  // Set default SINC3 filter
  adc.startADC1();
  
  Serial1.println("READY:Advanced ADS1263 with PPS timing ready");
  Serial1.println("DEBUG:PPS on pin 4, scientific-grade timing when GPS available");
}

void loop() {
  unsigned long current_micros = micros();
  
  // Update timing source status
  updateTimingSource();
  
  // Send health beacon (1 Hz STAT line)
  sendHealthBeacon();
  
  // Update temperature compensation (if enabled)
  updateTemperatureCompensation();
  
  // Process serial commands
  while (Serial1.available()) {
    char inChar = (char)Serial1.read();
    
    if (inChar == '\n') {
      processLine(cmdBuffer);
      cmdBuffer = "";
    } else if (inChar != '\r') {
      cmdBuffer += inChar;
    }
  }
  
  // Handle synchronized start waiting
  if (advanced_timing.waiting_for_sync_start) {
    // If we're waiting to start on PPS, do NOT use strict target; just yield
    if (advanced_timing.sync_on_pps) {
      delayMicroseconds(200);
      return;
    }
    // Otherwise, strict microsecond target start
    uint64_t now_us = getVirtualMicros();
    if ((long long)(now_us - advanced_timing.sync_start_target_us) >= 0) {
      advanced_timing.timing_base_micros = now_us;
      advanced_timing.next_sample_micros = advanced_timing.timing_base_micros; // align scheduler
      advanced_timing.timing_established = true;
      advanced_timing.waiting_for_sync_start = false;
      advanced_timing.samples_generated = 0;
      advanced_timing.sample_index = 0;

      Serial1.print("OK:Streaming started at ");
      Serial1.print(stream_rate);
      Serial1.print("Hz with ");
      Serial1.print(getTimingSourceName(advanced_timing.current_source));
      Serial1.println(" timing (strict target)");
    } else {
      long long early = (long long)advanced_timing.sync_start_target_us - (long long)now_us;
      if (early > 3000) {
        delayMicroseconds(200);
      } else if (early > 50) {
        delayMicroseconds(early - 50);
      }
    }
    return;
  }
  
  // Handle precision streaming (PPS-disciplined fractional scheduler)
  if (streaming && advanced_timing.timing_established) {
    // Initialize next_sample_micros on first entry
    if (advanced_timing.next_sample_micros == 0) {
      advanced_timing.next_sample_micros = advanced_timing.timing_base_micros;
    }

    // Update effective interval using PPS-derived calibration (fractional)
    // effective = nominal * (1 + ppm/1e6)
    // Convert calibration (ppm) into a scaling from micros-domain to real time.
    // If micros() runs fast (error_ppm > 0), calibration_ppm is negative.
    // We need more micros ticks per real 10 ms, so multiply by (1 - calibration_ppm/1e6).
    advanced_timing.effective_interval_us = (double)advanced_timing.sample_interval_us *
      (1.0 - (advanced_timing.oscillator_calibration_ppm / 1e6));

    // Single-shot scheduler: emit max 1 sample per loop, skip over missed slots
    uint64_t now_virtual = getVirtualMicros();
    if ((long long)now_virtual - (long long)advanced_timing.next_sample_micros >= 0) {
      generatePreciseSample();

      // Skip-ahead: calculate how many slots we missed and jump over them
      long long missed_slots = ((long long)now_virtual - (long long)advanced_timing.next_sample_micros) / 
                               (long long)advanced_timing.effective_interval_us;
      
      if (missed_slots > 0) {
        // Jump over missed slots to prevent burst catch-up
        advanced_timing.next_sample_micros += (uint64_t)(missed_slots * (long long)advanced_timing.effective_interval_us);
        Serial1.print("DEBUG:Skipped ");
        Serial1.print(missed_slots);
        Serial1.println(" missed slots");
      }

      // Advance next time with fractional accumulator to keep long-term average exact
      double step = advanced_timing.effective_interval_us + advanced_timing.phase_acc_us;
      // Apply gentle phase alignment if active
      if (advanced_timing.phase_alignment_active && advanced_timing.phase_adjust_samples_remaining > 0) {
        step += advanced_timing.per_sample_phase_adjust_us;
        if (advanced_timing.phase_adjust_samples_remaining > 0) {
          advanced_timing.phase_adjust_samples_remaining--;
        }
        if (advanced_timing.phase_adjust_samples_remaining == 0) {
          advanced_timing.phase_alignment_active = false;
          advanced_timing.per_sample_phase_adjust_us = 0.0;
          advanced_timing.phase_error_us = 0.0;
          Serial1.println("DEBUG:Phase alignment completed");
        }
      }
      long long whole_us = (long long)step;
      advanced_timing.phase_acc_us = step - (double)whole_us; // keep fractional part
      advanced_timing.next_sample_micros += (uint64_t)whole_us;
    }
  }
  
  // Minimal delay when not streaming
  if (!streaming) {
    delayMicroseconds(100);
  }
}

void setupAdvancedTiming() {
  // Initialize PPS interrupt
  pinMode(advanced_timing.PPS_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(advanced_timing.PPS_PIN), pps_interrupt, RISING);
  
  // Initialize timing state
  advanced_timing.pps_received = false;
  advanced_timing.pps_valid = false;
  advanced_timing.pps_timeout_ms = 2000;  // 2 second PPS timeout
  advanced_timing.current_source = AdvancedTiming::TIMING_INTERNAL_RAW;
  advanced_timing.oscillator_calibration_ppm = 0.0;
  advanced_timing.timing_accuracy_us = 1000.0;   // 1ms initial accuracy
  advanced_timing.pps_miss_count = 0;
  advanced_timing.pps_count = 0;
  advanced_timing.calibration_valid = false;
  
  // Initialize clock reset detection
  advanced_timing.last_micros = micros();
  advanced_timing.last_millis = millis();
  advanced_timing.micros_wraparound_count = 0;
  advanced_timing.virtual_micros_offset = 0;
  advanced_timing.clock_reset_detected = false;
  advanced_timing.reset_detection_time = 0;
  advanced_timing.pre_reset_virtual_time = 0;
  advanced_timing.reset_recovery_samples = 0;
  advanced_timing.timing_continuity_maintained = false;
  advanced_timing.clock_resets_detected = 0;
  
  // Initialize overflow protection - NEW
  advanced_timing.reference_update_interval = 1000000ULL;  // Update every 1M samples (~2.8 hours at 100Hz)
  advanced_timing.last_reference_update_sample = 0;
  advanced_timing.timing_base_virtual_micros = 0;
  advanced_timing.reference_updates_count = 0;
  
  // Initialize precision timing
  advanced_timing.sample_interval_us = 10000; // 100Hz default
  advanced_timing.effective_interval_us = (double)advanced_timing.sample_interval_us;
  advanced_timing.phase_acc_us = 0.0;
  advanced_timing.timing_base_micros = 0;
  advanced_timing.timing_established = false;
  advanced_timing.samples_generated = 0;
  advanced_timing.sample_index = 0;
  advanced_timing.next_sample_micros = 0;
  
  // Initialize synchronized start
  advanced_timing.sync_start_enabled = false;
  advanced_timing.sync_delay_ms = 0;
  advanced_timing.sync_start_time = 0;
  advanced_timing.waiting_for_sync_start = false;
  advanced_timing.sync_start_target_us = 0;
  advanced_timing.sync_on_pps = false;
  advanced_timing.pps_countdown = 0;
  
  // Initialize PPS alignment state
  advanced_timing.started_on_pps = false;
  advanced_timing.phase_nudge_applied = false;
  advanced_timing.phase_alignment_active = false;
  advanced_timing.phase_error_us = 0.0;
  advanced_timing.per_sample_phase_adjust_us = 0.0;
  advanced_timing.phase_adjust_samples_remaining = 0;
  advanced_timing.pps_phase_lock_enabled = true;
  
  // Initialize health beacon
  advanced_timing.last_stat_time = 0;
  advanced_timing.stat_interval_ms = 1000;  // 1 Hz
  
  // Initialize temperature-aware calibration
  advanced_timing.temp_coefficient_ppm_per_c = 0.0;  // Will be learned from PPS
  advanced_timing.reference_temp_c = 25.0;            // Reference temperature
  advanced_timing.current_temp_c = 25.0;              // Current temperature
  advanced_timing.temp_compensation_enabled = false;  // Disabled until learned
  
  Serial1.println("DEBUG:Advanced timing system initialized with overflow protection");
}

void pps_interrupt() {
  advanced_timing.pps_received = true;
  advanced_timing.pps_micros = micros();
  advanced_timing.last_pps_time = millis();
}

void updateTimingSource() {
  unsigned long current_millis = millis();
  
  // FIRST: Check for clock reset
  if (detectClockReset()) {
    handleClockReset();
  }
  
  // Check for new PPS
  if (advanced_timing.pps_received) {
    processPPS();
    advanced_timing.pps_received = false;
  }
  
  // If we recently detected a reset, be more conservative
  unsigned long time_since_reset = current_millis - advanced_timing.reset_detection_time;
  bool recent_reset = advanced_timing.clock_reset_detected && (time_since_reset < 30000); // 30 seconds
  
  // Determine current timing source based on explicit thresholds
  unsigned long time_since_pps = current_millis - advanced_timing.last_pps_time;
  
  // Explicit state machine thresholds as specified
  if (advanced_timing.pps_valid && time_since_pps < 1500 && !recent_reset) {
    // ACTIVE: last_pps_age < 1.5s
    advanced_timing.current_source = AdvancedTiming::TIMING_PPS_ACTIVE;
    advanced_timing.timing_accuracy_us = 1.0;  // ±1μs with active PPS
    advanced_timing.pps_miss_count = 0;
  }
  else if (advanced_timing.pps_valid && time_since_pps < 60000 && !recent_reset) {
    // HOLDOVER: 1.5s < last_pps_age < 60s (no PPS but have oscillator_calibration_ppm)
    advanced_timing.current_source = AdvancedTiming::TIMING_PPS_HOLDOVER;
    // Freeze ppm in holdover, slowly increase accuracy_us
    // oscillator_calibration_ppm remains frozen at last good value
    advanced_timing.timing_accuracy_us = 1.0 + (time_since_pps / 1000.0) * 0.1;  // +0.1μs per second
    advanced_timing.pps_miss_count++;
  }
  else if (advanced_timing.calibration_valid && time_since_pps < 300000 && !recent_reset) {
    // CAL: 60s < last_pps_age < 300s (or if temp change > threshold)
    advanced_timing.current_source = AdvancedTiming::TIMING_INTERNAL_CAL;
    // Keep the last ppm and slowly increase accuracy_us
    advanced_timing.timing_accuracy_us = 10.0 + (time_since_pps / 1000.0) * 0.3;  // +0.3μs per second
  }
  else {
    // RAW: last_pps_age > 300s (or if temp change > threshold)
    advanced_timing.current_source = AdvancedTiming::TIMING_INTERNAL_RAW;
    advanced_timing.timing_accuracy_us = recent_reset ? 2000.0 : 1000.0;  // Worse accuracy after reset
    
    // Alert about timing degradation (only once per event)
    static bool degradation_warned = false;
    static bool reset_warned = false;
    
    if (recent_reset && !reset_warned) {
      Serial1.println("WARNING:Using raw timing due to recent clock reset");
      reset_warned = true;
      degradation_warned = false;  // Reset PPS warning
    } else if (advanced_timing.pps_valid && !degradation_warned && !recent_reset) {
      Serial1.print("WARNING:GPS PPS lost for ");
      Serial1.print(time_since_pps / 1000);
      Serial1.println("s - timing accuracy degraded");
      advanced_timing.pps_valid = false;
      degradation_warned = true;
      reset_warned = false;  // Reset reset warning
    }
  }
  
  // Clear reset flag after recovery period
  if (recent_reset && time_since_reset > 30000) {
    advanced_timing.clock_reset_detected = false;
    Serial1.println("DEBUG:Clock reset recovery period completed");
  }
}

bool detectClockReset() {
  unsigned long current_micros = micros();
  unsigned long current_millis = millis();
  
  // Check for micros() going backward (reset or wraparound)
  if (current_micros < advanced_timing.last_micros) {
    // First, check if this was the regular 32-bit wraparound (expected every ~71.6 min)
    if (advanced_timing.last_micros > 4000000000UL && current_micros < 300000000UL) {
      advanced_timing.micros_wraparound_count++;
      advanced_timing.virtual_micros_offset += 4294967296ULL;  // Add 2^32
      Serial1.print("DEBUG:micros() wraparound detected (#");
      Serial1.print(advanced_timing.micros_wraparound_count);
      Serial1.println(")");
      
      // Update last readings and continue without flagging a reset
      advanced_timing.last_micros = current_micros;
      advanced_timing.last_millis = current_millis;
      return false;
    }
    
    // Otherwise, calculate how much it went backward and treat as reset only if substantial
    unsigned long backward_jump = advanced_timing.last_micros - current_micros;
    if (backward_jump > 1000000) {  // > 1 second backward = likely reset
      Serial1.print("WARNING:Large backward micros() jump detected: ");
      Serial1.print(backward_jump);
      Serial1.println("us - MCU reset suspected");
      return true;
    }
  }
  
  // Check for millis() going backward (definite reset)
  if (current_millis < advanced_timing.last_millis) {
    unsigned long millis_backward = advanced_timing.last_millis - current_millis;
    
    if (millis_backward > 1000) {  // > 1 second backward
      Serial1.print("WARNING:millis() went backward by ");
      Serial1.print(millis_backward);
      Serial1.println("ms - MCU reset detected");
      return true;
    }
  }
  
  // Check for both micros() and millis() being very small (recent reset)
  if (current_micros < 5000000 && current_millis < 5000) {  // < 5 seconds since boot
    if (advanced_timing.last_micros > 10000000 || advanced_timing.last_millis > 10000) {
      Serial1.println("WARNING:Clock values suggest recent MCU reset");
      return true;
    }
  }
  
  // Update last readings
  advanced_timing.last_micros = current_micros;
  advanced_timing.last_millis = current_millis;
  
  return false;
}

uint64_t getVirtualMicros() {
  // Get current micros() and add offset for continuous time
  unsigned long current_micros = micros();
  
  // Handle case where micros() wrapped but we haven't detected it yet
  if (current_micros < advanced_timing.last_micros) {
    unsigned long backward_jump = advanced_timing.last_micros - current_micros;
    
    // If it's a large backward jump, it's likely a wraparound we missed
    if (backward_jump > 1000000000UL) {  // > 1 billion microseconds
      advanced_timing.micros_wraparound_count++;
      advanced_timing.virtual_micros_offset += 4294967296ULL;
      Serial1.println("DEBUG:Late wraparound detection in getVirtualMicros()");
    }
  }
  
  advanced_timing.last_micros = current_micros;
  return advanced_timing.virtual_micros_offset + current_micros;
}

void handleClockReset() {
  Serial1.println("DEBUG:Handling clock reset - attempting to maintain timing continuity");
  
  advanced_timing.clock_reset_detected = true;
  advanced_timing.reset_detection_time = millis();
  advanced_timing.clock_resets_detected++;
  advanced_timing.reset_recovery_samples = 0;
  
  // Store virtual time before reset for continuity
  advanced_timing.pre_reset_virtual_time = advanced_timing.virtual_micros_offset + advanced_timing.last_micros;
  
  // Reset virtual time tracking
  advanced_timing.virtual_micros_offset = advanced_timing.pre_reset_virtual_time;
  advanced_timing.last_micros = micros();
  advanced_timing.last_millis = millis();
  
  // Invalidate calibration temporarily
  advanced_timing.calibration_valid = false;
  
  // Increase timing uncertainty
  advanced_timing.timing_accuracy_us = 1000.0;  // Back to 1ms accuracy
  advanced_timing.current_source = AdvancedTiming::TIMING_INTERNAL_RAW;
  
  // Try to maintain timing continuity for sampling
  if (advanced_timing.timing_established && streaming) {
    // Calculate where we should be in the sampling sequence
    uint64_t virtual_time = getVirtualMicros();
    uint64_t time_since_start = virtual_time - (advanced_timing.timing_base_micros + advanced_timing.virtual_micros_offset);
    uint64_t expected_sample_index = time_since_start / advanced_timing.sample_interval_us;
    
    // Update sample index to maintain continuity
    advanced_timing.sample_index = expected_sample_index;
    advanced_timing.timing_continuity_maintained = true;
    
    Serial1.print("DEBUG:Timing continuity maintained - adjusted to sample index ");
    Serial1.println((unsigned long)expected_sample_index);
  }
  
  Serial1.print("DEBUG:Clock reset #");
  Serial1.print(advanced_timing.clock_resets_detected);
  Serial1.println(" handled");
}

uint64_t getPreciseTimestamp() {
  // Use virtual micros for continuous time across resets
  uint64_t virtual_micros = getVirtualMicros();
  
  switch (advanced_timing.current_source) {
    case AdvancedTiming::TIMING_PPS_ACTIVE:
    case AdvancedTiming::TIMING_PPS_HOLDOVER:
    case AdvancedTiming::TIMING_INTERNAL_CAL:
      // Use calibrated timestamp with virtual time
      return calculateCalibratedTimestamp(virtual_micros);
      
    case AdvancedTiming::TIMING_INTERNAL_RAW:
    default:
      // Return virtual micros for continuity
      return virtual_micros;
  }
}

void processPPS() {
  unsigned long pps_micros = advanced_timing.pps_micros;
  unsigned long current_millis = millis();
  
  advanced_timing.pps_count++;

  // If we're explicitly armed to start on PPS, handle countdown FIRST (unconditionally)
  if (advanced_timing.sync_on_pps && advanced_timing.pps_countdown > 0) {
    if (--advanced_timing.pps_countdown == 0) {
      // Begin streaming exactly at this PPS edge
      advanced_timing.timing_base_micros = pps_micros;
      advanced_timing.next_sample_micros = pps_micros;
      advanced_timing.timing_established = true;
      advanced_timing.waiting_for_sync_start = false;
      advanced_timing.sync_on_pps = false;
      advanced_timing.started_on_pps = true;
      sequence = 0;
      streaming = true;
      sendSessionHeader();
      Serial1.print("OK:Streaming started at PPS with ");
      Serial1.print(stream_rate);
      Serial1.println("Hz");
      // Update last_pps_time for consistency
      advanced_timing.last_pps_time = current_millis;
      return;  // Done handling this PPS
    }
  }
  
  // Don't process PPS if we recently detected a clock reset
  if (advanced_timing.clock_reset_detected && 
      (current_millis - advanced_timing.reset_detection_time) < 5000) {
    Serial1.println("DEBUG:Ignoring PPS during reset recovery period");
    return;
  }
  
  // Validate PPS (should come every ~1 second)
  if (advanced_timing.pps_valid) {
    unsigned long pps_interval = current_millis - advanced_timing.last_pps_time;
    
    if (pps_interval < 900 || pps_interval > 1100) {
      Serial1.print("WARNING:Invalid PPS interval: ");
      Serial1.print(pps_interval);
      Serial1.println("ms - ignoring");
      return;  // Ignore invalid PPS
    }
  }
  
  // Calculate oscillator calibration (only if no recent reset)
  if (advanced_timing.pps_count > 1 && advanced_timing.calibration_valid && !advanced_timing.clock_reset_detected) {
    // Expected time since last PPS: 1,000,000 μs
    uint64_t actual_interval = pps_micros - advanced_timing.cal_base_micros;
    
    // No wraparound handling needed with 64-bit arithmetic
    float error_ppm = ((float)actual_interval - 1000000.0) / 1000000.0 * 1e6;
    
    // Only update calibration if error seems reasonable
    if (abs(error_ppm) < 1000) {  // Sanity check: < 1000ppm error
      // Update calibration with smoothing
      if (advanced_timing.pps_count < 10) {
        // Initial calibration - use direct measurement
        advanced_timing.oscillator_calibration_ppm = -error_ppm;
      } else {
        // Smooth calibration updates (10% new, 90% old)
        advanced_timing.oscillator_calibration_ppm = 
          0.9 * advanced_timing.oscillator_calibration_ppm + 0.1 * (-error_ppm);
        
        // Apply hard limits and sanity checks
        clampOscillatorCalibration();
        
        // Save calibration to EEPROM for future boots
        saveOscillatorCalibration();
        
        // Learn temperature coefficient if we have enough PPS data
        if (advanced_timing.pps_count > 100 && advanced_timing.pps_count % 50 == 0) {
          float current_temp = readInternalTemperature();
          float temp_change = current_temp - advanced_timing.reference_temp_c;
          
          if (abs(temp_change) > 1.0) {  // Only learn if temperature changed significantly
            // Simple linear learning: assume ppm change is proportional to temp change
            float ppm_change = advanced_timing.oscillator_calibration_ppm - 0.0; // Relative to reference
            advanced_timing.temp_coefficient_ppm_per_c = ppm_change / temp_change;
            advanced_timing.temp_compensation_enabled = true;
            
            Serial1.print("DEBUG:Learned temperature coefficient: ");
            Serial1.print(advanced_timing.temp_coefficient_ppm_per_c, 3);
            Serial1.println(" ppm/°C");
          }
        }
      }
      
      // Report calibration periodically
      if (advanced_timing.pps_count % 10 == 0) {
        Serial1.print("DEBUG:Oscillator cal: ");
        Serial1.print(advanced_timing.oscillator_calibration_ppm, 2);
        Serial1.print("ppm, interval: ");
        Serial1.print(actual_interval);
        Serial1.println("μs");
      }
    } else {
      Serial1.print("WARNING:PPS calibration error too large: ");
      Serial1.print(error_ppm, 1);
      Serial1.println("ppm - ignoring");
    }
  }
  
  // First PPS or reacquisition
  if (!advanced_timing.pps_valid) {
    Serial1.print("DEBUG:GPS PPS acquired - count: ");
    Serial1.println(advanced_timing.pps_count);
  }
  
  advanced_timing.pps_valid = true;
  advanced_timing.calibration_valid = true;
  advanced_timing.cal_base_micros = pps_micros;
  advanced_timing.cal_base_millis = current_millis;
  advanced_timing.last_pps_time = current_millis;

  // If we are already streaming (not started on PPS) and this is the first time PPS becomes valid,
  // gently nudge sampling phase to align with PPS without changing long-term rate.
  if (streaming && advanced_timing.timing_established && !advanced_timing.started_on_pps && !advanced_timing.phase_nudge_applied) {
    // Compute PPS time in virtual domain to compare with timing_base_micros
    uint64_t pps_virtual = advanced_timing.virtual_micros_offset + (uint64_t)pps_micros;
    uint64_t interval = advanced_timing.sample_interval_us;
    if (interval > 0) {
      // Calculate signed phase error in range [-interval/2, +interval/2]
      long long delta = (long long)pps_virtual - (long long)advanced_timing.timing_base_micros;
      long long imod = (long long)interval;
      long long phase_mod = ((delta % imod) + imod) % imod; // normalized to [0, interval)
      long long signed_phase = (phase_mod <= (long long)(interval / 2))
        ? phase_mod
        : (phase_mod - (long long)interval);

      // If small (< 20us), ignore
      if (signed_phase > 20 || signed_phase < -20) {
        // Spread correction over up to 200 samples, but cap per-sample adjust to +/-50us
        uint32_t planned_samples = 200;
        double per_sample = (double)signed_phase / (double)planned_samples;
        // Cap per-sample adjustment to ±20 μs/sample clamp
        if (per_sample > 20.0) per_sample = 20.0;
        if (per_sample < -20.0) per_sample = -20.0;
        // Recompute number of samples to achieve full correction with capped per-sample
        uint32_t samples_needed = (uint32_t)( (fabs((double)signed_phase) / (fabs(per_sample) > 0.0 ? fabs(per_sample) : 1.0)) + 0.5 );
        if (samples_needed == 0) samples_needed = 1;

        advanced_timing.phase_error_us = (double)signed_phase;
        advanced_timing.per_sample_phase_adjust_us = per_sample;
        advanced_timing.phase_adjust_samples_remaining = samples_needed;
        advanced_timing.phase_alignment_active = true;
        advanced_timing.phase_nudge_applied = true; // only once

        Serial1.print("DEBUG:Applying phase nudge to PPS: error=");
        Serial1.print((long)signed_phase);
        Serial1.print("us over ");
        Serial1.print((unsigned long)samples_needed);
        Serial1.print(" samples (~");
        Serial1.print( (double)samples_needed * (double)interval / 1000.0, 1);
        Serial1.println(" ms)");
      }
    }
  }

  // Continuous PPS phase lock: at each PPS, compute current phase error and correct it gradually
  if (streaming && advanced_timing.timing_established && advanced_timing.pps_phase_lock_enabled) {
    uint64_t pps_virtual2 = advanced_timing.virtual_micros_offset + (uint64_t)pps_micros;
    uint64_t interval2 = advanced_timing.sample_interval_us;
    if (interval2 > 0) {
      long long delta2 = (long long)pps_virtual2 - (long long)advanced_timing.timing_base_micros;
      long long imod2 = (long long)interval2;
      long long phase_mod2 = ((delta2 % imod2) + imod2) % imod2;
      long long signed_phase2 = (phase_mod2 <= (long long)(interval2 / 2)) ? phase_mod2 : (phase_mod2 - (long long)interval2);

      // Small hysteresis to avoid chattering
      if (signed_phase2 > 5 || signed_phase2 < -5) {
        // Spread over approximately one second worth of samples
        uint32_t samples_per_second = (uint32_t)(stream_rate + 0.5f);
        if (samples_per_second == 0) samples_per_second = 1;

        double per_sample2 = (double)signed_phase2 / (double)samples_per_second;
        // Tight clamp for continuous lock
        if (per_sample2 > 20.0) per_sample2 = 20.0;
        if (per_sample2 < -20.0) per_sample2 = -20.0;
        uint32_t samples_needed2 = (uint32_t)( (fabs((double)signed_phase2) / (fabs(per_sample2) > 0.0 ? fabs(per_sample2) : 1.0)) + 0.5 );
        if (samples_needed2 == 0) samples_needed2 = 1;

        advanced_timing.phase_error_us = (double)signed_phase2;
        advanced_timing.per_sample_phase_adjust_us = per_sample2;
        advanced_timing.phase_adjust_samples_remaining = samples_needed2;
        advanced_timing.phase_alignment_active = true;

        Serial1.print("DEBUG:PPS lock adjust: phase=");
        Serial1.print((long)signed_phase2);
        Serial1.print("us over ");
        Serial1.print((unsigned long)samples_needed2);
        Serial1.println(" samples");
      }
    }
  }

  // Handle PPS-locked start: if requested, start streaming exactly on this PPS
  if (advanced_timing.sync_on_pps && advanced_timing.pps_countdown > 0) {
    if (--advanced_timing.pps_countdown == 0) {
      // Start precisely at PPS edge
      advanced_timing.timing_base_micros = pps_micros;
      advanced_timing.next_sample_micros = pps_micros;
      advanced_timing.timing_established = true;
      advanced_timing.waiting_for_sync_start = false;
      advanced_timing.started_on_pps = true;
      sequence = 0;
      streaming = true;
      sendSessionHeader();
      Serial1.print("OK:Streaming started at PPS with ");
      Serial1.print(stream_rate);
      Serial1.println("Hz");
    }
  }
  
  // Clear reset flag if PPS is working again
  if (advanced_timing.clock_reset_detected) {
    Serial1.println("DEBUG:PPS reacquired after reset - timing stabilizing");
  }
}

uint64_t calculateCalibratedTimestamp(uint64_t current_micros) {
  if (!advanced_timing.calibration_valid) {
    return current_micros;
  }
  
  // Apply oscillator calibration - use 64-bit arithmetic throughout
  uint64_t elapsed_micros = current_micros - advanced_timing.cal_base_micros;
  
  // No wraparound handling needed with 64-bit arithmetic
  // Apply PPM correction using 64-bit math
  double corrected_elapsed = (double)elapsed_micros * (1.0 + advanced_timing.oscillator_calibration_ppm / 1e6);
  
  return advanced_timing.cal_base_micros + (uint64_t)corrected_elapsed;
}

void establishSamplingTiming() {
  // Establish timing base for precise sampling intervals using virtual time
  uint64_t current_virtual_micros = getVirtualMicros();
  
  // Start sampling at next interval boundary
  unsigned long offset_us = (unsigned long)(current_virtual_micros % advanced_timing.sample_interval_us);
  uint64_t next_boundary_micros = current_virtual_micros + (advanced_timing.sample_interval_us - offset_us);
  
  // Store both the 32-bit base and the full virtual time for overflow protection
  advanced_timing.timing_base_micros = next_boundary_micros;
  advanced_timing.timing_base_virtual_micros = next_boundary_micros;
  advanced_timing.timing_established = true;
  advanced_timing.samples_generated = 0;
  advanced_timing.sample_index = 0;
  advanced_timing.next_sample_micros = next_boundary_micros;
  advanced_timing.last_reference_update_sample = 0;
  
  Serial1.print("DEBUG:Sampling established at ");
  Serial1.print(stream_rate);
  Serial1.print("Hz with ");
  Serial1.print(getTimingSourceName(advanced_timing.current_source));
  Serial1.print(" timing (±");
  Serial1.print(advanced_timing.timing_accuracy_us, 1);
  Serial1.println("μs) - overflow protected");
}

void updateTimingReference() {
  // Periodic reference update to prevent overflow
  // This resets the sample_index and timing_base to prevent arithmetic overflow
  
  uint64_t current_virtual_micros = getVirtualMicros();
  
  // Calculate the new timing base (where we are now in the sampling grid)
  uint64_t samples_since_start = advanced_timing.sample_index;
  uint64_t expected_current_time = advanced_timing.timing_base_virtual_micros + 
                                   (samples_since_start * advanced_timing.sample_interval_us);
  
  // Update the timing base to current position
  advanced_timing.timing_base_micros = current_virtual_micros;
  advanced_timing.timing_base_virtual_micros = current_virtual_micros;
  advanced_timing.sample_index = 0;  // Reset sample index
  advanced_timing.next_sample_micros = current_virtual_micros; // keep scheduler aligned
  advanced_timing.last_reference_update_sample = samples_since_start;
  advanced_timing.reference_updates_count++;
  
  Serial1.print("DEBUG:Timing reference updated (#");
  Serial1.print(advanced_timing.reference_updates_count);
  Serial1.print(") after ");
  Serial1.print((unsigned long)samples_since_start);
  Serial1.println(" samples - overflow prevented");
}

bool checkSerialBufferOverflow() {
  // Check if serial buffer is getting full
  // On SAMD21, Serial1.availableForWrite() returns available space in TX buffer
  int available_space = Serial1.availableForWrite();
  
  // If buffer is more than 80% full, consider it at risk of overflow
  // Typical buffer size is 64-128 bytes, so 80% = ~50-100 bytes
  if (available_space < 20) {  // Less than 20 bytes available
    serial_monitor.buffer_overflows++;
    serial_monitor.last_overflow_time = millis();
    
    if (!serial_monitor.overflow_warning_sent) {
      Serial1.print("WARNING:Serial buffer near overflow - available: ");
      Serial1.print(available_space);
      Serial1.println(" bytes");
      serial_monitor.overflow_warning_sent = true;
    }
    return true;
  }
  
  // Reset warning flag if buffer is healthy
  if (available_space > 50) {
    serial_monitor.overflow_warning_sent = false;
  }
  
  return false;
}

void outputDataWithOverflowProtection(uint16_t seq, uint64_t timestamp, int timing_source, float accuracy, long v1, long v2, long v3) {
  // Check for buffer overflow before outputting
  if (checkSerialBufferOverflow()) {
    // Skip this sample to prevent buffer overflow
    serial_monitor.samples_skipped_due_to_overflow++;
    
    // Send OFLOW meta message periodically to signal backpressure
    uint32_t current_time = millis();
    if (current_time - serial_monitor.last_oflow_message_time >= serial_monitor.oflow_report_interval_ms) {
      Serial1.print("OFLOW:");
      Serial1.print(serial_monitor.samples_skipped_due_to_overflow);
      Serial1.print(",");
      Serial1.print(serial_monitor.buffer_overflows);
      Serial1.print(",");
      Serial1.print(Serial1.availableForWrite());
      Serial1.println();
      
      serial_monitor.oflow_message_count++;
      serial_monitor.last_oflow_message_time = current_time;
    }
    return;
  }
  
  if (compact_output) {
    // Compact format: seq,timestamp,v1,v2,v3 (reduces from ~40 to ~25 bytes)
    Serial1.print(seq);
    Serial1.print(",");
    Serial1.print((unsigned long)timestamp);
    Serial1.print(",");
    Serial1.print(v1);
    Serial1.print(",");
    Serial1.print(v2);
    Serial1.print(",");
    Serial1.print(v3);
    Serial1.println();
    serial_monitor.bytes_sent += 25; // Approximate bytes per line
  } else {
    // Full format: sequence,mcu_micros,timing_source,accuracy_us,value1,value2,value3
    Serial1.print(seq);
    Serial1.print(",");
    Serial1.print((unsigned long)timestamp);
    Serial1.print(",");
    Serial1.print(timing_source);
    Serial1.print(",");
    Serial1.print(accuracy, 1);
    Serial1.print(",");
    Serial1.print(v1);
    Serial1.print(",");
    Serial1.print(v2);
    Serial1.print(",");
    Serial1.print(v3);
    Serial1.println();
    serial_monitor.bytes_sent += 40; // Approximate bytes per line
  }
}

bool validateAndCorrectSequence(uint16_t& seq) {
  if (!seq_validator.validation_enabled) {
    return true; // Skip validation if disabled
  }
  
  // First sequence - initialize expected
  if (seq_validator.expected_sequence == 0 && seq == 0) {
    seq_validator.expected_sequence = 1;
    return true;
  }
  
  // Check if sequence matches expected
  if (seq == seq_validator.expected_sequence) {
    seq_validator.expected_sequence = (seq_validator.expected_sequence + 1) % 65536;
    return true;
  }
  
  // Handle sequence gap or reset
  uint16_t gap_size;
  if (seq > seq_validator.expected_sequence) {
    gap_size = seq - seq_validator.expected_sequence;
  } else {
    // Handle wraparound
    gap_size = (65536 - seq_validator.expected_sequence) + seq;
  }
  
  // Check if this is a large backward jump (likely reset)
  if (seq < seq_validator.expected_sequence && gap_size > 1000) {
    Serial1.print("SEQUENCE_RESET:Expected ");
    Serial1.print(seq_validator.expected_sequence);
    Serial1.print(", got ");
    Serial1.print(seq);
    Serial1.print(" (reset detected)");
    Serial1.println();
    
    seq_validator.sequence_resets_detected++;
    seq_validator.expected_sequence = (seq + 1) % 65536;
    return true;
  }
  
  // Report sequence gap
  Serial1.print("SEQUENCE_GAP:Expected ");
  Serial1.print(seq_validator.expected_sequence);
  Serial1.print(", got ");
  Serial1.print(seq);
  Serial1.print(" (gap: ");
  Serial1.print(gap_size);
  Serial1.print(" samples)");
  Serial1.println();
  
  seq_validator.sequence_gaps_detected++;
  seq_validator.expected_sequence = (seq + 1) % 65536;
  return true;
}

void generatePreciseSample() {
  uint64_t current_virtual_micros = getVirtualMicros();
  
  // Check if we need to update timing reference to prevent overflow
  if (advanced_timing.sample_index >= advanced_timing.reference_update_interval) {
    updateTimingReference();
  }
  
  // Verify ADC throughput margin before sampling
  verifyADCThroughput();
  
  // Ensure we are not early relative to the fractional scheduler
  long long wait = (long long)advanced_timing.next_sample_micros - (long long)current_virtual_micros;
  if (wait > 0 && wait < 10000) {
    delayMicroseconds((unsigned int)wait);
  }
  
  // Get precise timestamp
  uint64_t precise_timestamp = getPreciseTimestamp();
  
  // Implement dithering and oversampling
  long value1 = 0, value2 = 0, value3 = 0;
  
  if (current_dithering == 0) {
    // No dithering - single sample
    value1 = readADC(pos_pin1, neg_pin1);
    value2 = (num_channels > 1) ? readADC(pos_pin2, neg_pin2) : 0;
    value3 = (num_channels > 2) ? readADC(pos_pin3, neg_pin3) : 0;
  } else {
    // Dithering enabled - oversample and average
    int oversample_count = current_dithering;
    long sum1 = 0, sum2 = 0, sum3 = 0;
    
    for (int i = 0; i < oversample_count; i++) {
      sum1 += readADC(pos_pin1, neg_pin1);
      if (num_channels > 1) sum2 += readADC(pos_pin2, neg_pin2);
      if (num_channels > 2) sum3 += readADC(pos_pin3, neg_pin3);
      
      // Small delay between samples for dithering effect
      if (i < oversample_count - 1) {
        delayMicroseconds(50); // 50μs delay between oversamples
      }
    }
    
    // Average the oversampled values
    value1 = sum1 / oversample_count;
    value2 = (num_channels > 1) ? sum2 / oversample_count : 0;
    value3 = (num_channels > 2) ? sum3 / oversample_count : 0;
  }
  
  // Validate and correct sequence before output
  validateAndCorrectSequence(sequence);
  
  // Output with overflow protection
  outputDataWithOverflowProtection(sequence, precise_timestamp, (int)advanced_timing.current_source, 
                                   advanced_timing.timing_accuracy_us, value1, value2, value3);
  
  sequence = (sequence + 1) % 65536;
  advanced_timing.samples_generated++;
  advanced_timing.sample_index++;
  
  // Track recovery samples after reset
  if (advanced_timing.clock_reset_detected) {
    advanced_timing.reset_recovery_samples++;
  }
}

const char* getTimingSourceName(int source) {
  switch (source) {
    case AdvancedTiming::TIMING_PPS_ACTIVE: return "PPS_ACTIVE";
    case AdvancedTiming::TIMING_PPS_HOLDOVER: return "PPS_HOLDOVER";
    case AdvancedTiming::TIMING_INTERNAL_CAL: return "INTERNAL_CAL";
    case AdvancedTiming::TIMING_INTERNAL_RAW: return "INTERNAL_RAW";
    default: return "UNKNOWN";
  }
}

bool checkSyncStartTime() {
  if (!advanced_timing.sync_start_enabled) {
    return false;
  }
  // Kept for backward compatibility if used elsewhere; actual start now decided in loop()
  unsigned long current_millis = millis();
  long time_diff = (long)(current_millis - advanced_timing.sync_start_time);
  if (time_diff > 5000) {
    Serial1.println("WARNING:Legacy sync window expired; enforcing strict start in loop()");
  }
  return false;
}

void processLine(String line) {
  line.trim();
  
  if (line.indexOf(':') > 0) {
    int colonIndex = line.indexOf(':');
    String command = line.substring(0, colonIndex);
    String params = line.substring(colonIndex + 1);
    
    if (command == "START_STREAM_SYNC") {
      if (!streaming) {
        int commaIndex = params.indexOf(',');
        if (commaIndex > 0) {
          float rate = params.substring(0, commaIndex).toFloat();
          unsigned long delay_ms = params.substring(commaIndex + 1).toInt();
          
          if (rate > 0 && rate <= 1000 && delay_ms < 10000) {
            stream_rate = rate;
            advanced_timing.sample_interval_us = (uint64_t)(1000000.0 / rate);
            advanced_timing.sync_delay_ms = delay_ms;
            advanced_timing.sync_start_time = millis() + delay_ms;
            // Compute strict absolute start target in virtual micros (works even if micros wraps)
            advanced_timing.sync_start_target_us = getVirtualMicros() + ((uint64_t)delay_ms * 1000ULL);
            advanced_timing.sync_start_enabled = true;
            advanced_timing.waiting_for_sync_start = true;
            
            sequence = 0;
            streaming = true;
            sendSessionHeader();
            
            Serial1.print("OK:Synchronized streaming prepared at ");
            Serial1.print(stream_rate);
            Serial1.print("Hz, delay: ");
            Serial1.print(delay_ms);
            Serial1.println("ms");
          } else {
            Serial1.println("ERROR:Invalid rate or delay");
          }
        } else {
          Serial1.println("ERROR:Invalid sync parameters");
        }
      } else {
        Serial1.println("ERROR:Already streaming");
      }
    }
    else if (command == "SET_ADC_RATE") {
      if (!streaming) {
        int rateIndex = params.toInt();
        if (rateIndex >= 1 && rateIndex <= 16) {
          uint8_t rates[] = {
            ADS126X_RATE_2_5, ADS126X_RATE_5, ADS126X_RATE_10, ADS126X_RATE_16_6, ADS126X_RATE_20,
            ADS126X_RATE_50, ADS126X_RATE_60, ADS126X_RATE_100, ADS126X_RATE_400, ADS126X_RATE_1200,
            ADS126X_RATE_2400, ADS126X_RATE_4800, ADS126X_RATE_7200, ADS126X_RATE_14400, ADS126X_RATE_19200,
            ADS126X_RATE_38400
          };
          current_adc_rate = rates[rateIndex - 1];
          adc.setRate(current_adc_rate);
          Serial1.println("OK:ADC rate set");
        } else {
          Serial1.println("ERROR:Invalid rate index");
        }
      } else {
        Serial1.println("ERROR:Cannot change while streaming");
      }
    }
    else if (command == "SET_GAIN") {
      if (!streaming) {
        int gainIndex = params.toInt();
        if (gainIndex >= 1 && gainIndex <= 6) {
          uint8_t gains[] = {ADS126X_GAIN_1, ADS126X_GAIN_2, ADS126X_GAIN_4, ADS126X_GAIN_8, ADS126X_GAIN_16, ADS126X_GAIN_32};
          current_adc_gain = gains[gainIndex - 1];
          adc.setGain(current_adc_gain);
          Serial1.println("OK:Gain set");
        } else {
          Serial1.println("ERROR:Invalid gain index");
        }
      } else {
        Serial1.println("ERROR:Cannot change while streaming");
      }
    }
    else if (command == "SET_FILTER") {
      if (!streaming) {
        int filterIndex = params.toInt();
        if (filterIndex >= 1 && filterIndex <= 5) {
          uint8_t filters[] = {ADS126X_SINC1, ADS126X_SINC2, ADS126X_SINC3, ADS126X_SINC4, ADS126X_FIR};
          uint8_t selectedFilter = filters[filterIndex - 1];
          current_adc_filter = selectedFilter;
          adc.setFilter(selectedFilter);
          Serial1.print("OK:Filter set to ");
          switch(selectedFilter) {
            case ADS126X_SINC1: Serial1.println("SINC1"); break;
            case ADS126X_SINC2: Serial1.println("SINC2"); break;
            case ADS126X_SINC3: Serial1.println("SINC3"); break;
            case ADS126X_SINC4: Serial1.println("SINC4"); break;
            case ADS126X_FIR: Serial1.println("FIR"); break;
          }
        } else {
          Serial1.println("ERROR:Invalid filter index (1-5)");
        }
      } else {
        Serial1.println("ERROR:Cannot change while streaming");
      }
    }
    else if (command == "SET_DITHERING") {
      if (!streaming) {
        int dithering = params.toInt();
        if (dithering == 0 || dithering == 2 || dithering == 3 || dithering == 4) {
          current_dithering = dithering;
          Serial1.print("OK:Dithering set to ");
          if (dithering == 0) {
            Serial1.println("OFF");
          } else {
            Serial1.print(dithering);
            Serial1.println("x oversampling");
          }
        } else {
          Serial1.println("ERROR:Invalid dithering value (0, 2, 3, or 4)");
        }
      } else {
        Serial1.println("ERROR:Cannot change while streaming");
      }
    }
    else if (command == "GET_DITHERING") {
      Serial1.print("DITHERING:");
      Serial1.print(current_dithering);
      Serial1.print(",");
      if (current_dithering == 0) {
        Serial1.println("OFF");
      } else {
        Serial1.print(current_dithering);
        Serial1.println("x oversampling");
      }
    }
    else if (command == "GET_FILTER") {
      Serial1.print("FILTER:");
      Serial1.print((int)current_adc_filter);
      Serial1.print(",");
      switch(current_adc_filter) {
        case ADS126X_SINC1: Serial1.println("SINC1"); break;
        case ADS126X_SINC2: Serial1.println("SINC2"); break;
        case ADS126X_SINC3: Serial1.println("SINC3"); break;
        case ADS126X_SINC4: Serial1.println("SINC4"); break;
        case ADS126X_FIR: Serial1.println("FIR"); break;
      }
    }
    else if (command == "SET_CHANNELS") {
      if (!streaming) {
        int channels = params.toInt();
        if (channels >= 1 && channels <= 3) {
          num_channels = channels;
          Serial1.println("OK:Channels set");
        } else {
          Serial1.println("ERROR:Invalid channel count");
        }
      } else {
        Serial1.println("ERROR:Cannot change while streaming");
      }
    }
    else if (command == "SET_PRECISE_INTERVAL") {
      unsigned long interval_us = params.toInt();
      if (interval_us >= 9900 && interval_us <= 10100) {
        float new_rate = 1000000.0 / interval_us;
        
        // Check if rate change is allowed (bounded host nudges)
        if (isRateChangeAllowed(new_rate)) {
          advanced_timing.sample_interval_us = interval_us;
          stream_rate = new_rate;
          
          Serial1.print("OK:Precise interval set to ");
          Serial1.print(interval_us);
          Serial1.print("μs (");
          Serial1.print(new_rate, 3);
          Serial1.println("Hz)");
        }
      } else {
        Serial1.println("ERROR:Invalid interval (9900-10100 μs)");
      }
    }
    else if (command == "START_STREAM") {
      if (!streaming) {
        float rate = params.toFloat();
        if (rate > 0 && rate <= 1000) {
          // Check if rate change is allowed (bounded host nudges)
          if (isRateChangeAllowed(rate)) {
            stream_rate = rate;
            advanced_timing.sample_interval_us = (uint64_t)(1000000.0 / rate);
          } else {
            return;  // Rate change rejected
          }
        }
        
        sequence = 0;
        establishSamplingTiming();
        streaming = true;
        sendSessionHeader();
        
        Serial1.print("OK:Streaming started at ");
        Serial1.print(stream_rate);
        Serial1.print("Hz with ");
        Serial1.print(getTimingSourceName(advanced_timing.current_source));
        Serial1.println(" timing");
      } else {
        Serial1.println("ERROR:Already streaming");
      }
    }
    else if (command == "START_STREAM_PPS") {
      if (!streaming) {
        int commaIndex = params.indexOf(',');
        if (commaIndex > 0) {
          float rate = params.substring(0, commaIndex).toFloat();
          int pps_wait = params.substring(commaIndex + 1).toInt();
          if (rate > 0 && rate <= 1000 && pps_wait >= 1 && pps_wait <= 5) {
            stream_rate = rate;
            advanced_timing.sample_interval_us = (uint64_t)(1000000.0 / rate);
            advanced_timing.sync_on_pps = true;
            advanced_timing.pps_countdown = (uint8_t)pps_wait;
            advanced_timing.waiting_for_sync_start = true;
            Serial1.print("OK:Waiting for ");
            Serial1.print(pps_wait);
            Serial1.println(" PPS edges to start");
          } else {
            Serial1.println("ERROR:Invalid rate or PPS wait count (1-5)");
          }
        } else {
          Serial1.println("ERROR:Invalid PPS start parameters");
        }
      } else {
        Serial1.println("ERROR:Already streaming");
      }
    }
    else if (command == "STOP_STREAM") {
      streaming = false;
      advanced_timing.timing_established = false;
      // Clear any pending sync states
      advanced_timing.sync_on_pps = false;
      advanced_timing.pps_countdown = 0;
      advanced_timing.waiting_for_sync_start = false;
      // Reset session header flag for next stream
      session_tracker.session_header_sent = false;
      Serial1.print("DEBUG:Generated ");
      Serial1.print(advanced_timing.samples_generated);
      Serial1.println(" samples");
      Serial1.println("OK:Streaming stopped");
    }
    else if (command == "GET_STATUS") {
      Serial1.print("STATUS:streaming=");
      Serial1.print(streaming ? 1 : 0);
      Serial1.print(",samples_generated=");
      Serial1.print(advanced_timing.samples_generated);
      Serial1.print(",stream_rate=");
      Serial1.print(stream_rate);
      Serial1.print(",channels=");
      Serial1.print(num_channels);
      Serial1.print(",filter=");
      Serial1.print((int)current_adc_filter);
      Serial1.print(",sequence=");
      Serial1.print(sequence);
      Serial1.print(",timing_source=");
      Serial1.print((int)advanced_timing.current_source);
      Serial1.print(",timing_accuracy_us=");
      Serial1.print(advanced_timing.timing_accuracy_us, 1);
      Serial1.print(",pps_valid=");
      Serial1.print(advanced_timing.pps_valid ? 1 : 0);
      Serial1.print(",pps_count=");
      Serial1.print(advanced_timing.pps_count);
      Serial1.print(",clock_resets=");
      Serial1.print(advanced_timing.clock_resets_detected);
      Serial1.print(",wraparounds=");
      Serial1.print(advanced_timing.micros_wraparound_count);
      Serial1.print(",ref_updates=");
      Serial1.print(advanced_timing.reference_updates_count);
      Serial1.print(",buffer_overflows=");
      Serial1.print(serial_monitor.buffer_overflows);
      Serial1.print(",samples_skipped=");
      Serial1.print(serial_monitor.samples_skipped_due_to_overflow);
      Serial1.print(",buffer_available=");
      Serial1.print(Serial1.availableForWrite());
      Serial1.print(",seq_gaps=");
      Serial1.print(seq_validator.sequence_gaps_detected);
      Serial1.print(",seq_resets=");
      Serial1.print(seq_validator.sequence_resets_detected);
      Serial1.println();
    }
    else if (command == "GET_TIMING_STATUS") {
      Serial1.print("TIMING:source=");
      Serial1.print(getTimingSourceName(advanced_timing.current_source));
      Serial1.print(",accuracy_us=");
      Serial1.print(advanced_timing.timing_accuracy_us, 1);
      Serial1.print(",pps_valid=");
      Serial1.print(advanced_timing.pps_valid ? 1 : 0);
      Serial1.print(",pps_count=");
      Serial1.print(advanced_timing.pps_count);
      Serial1.print(",calibration_ppm=");
      Serial1.print(advanced_timing.oscillator_calibration_ppm, 3);
      Serial1.print(",calibration_valid=");
      Serial1.print(advanced_timing.calibration_valid ? 1 : 0);
      Serial1.print(",clock_resets=");
      Serial1.print(advanced_timing.clock_resets_detected);
      Serial1.print(",wraparounds=");
      Serial1.print(advanced_timing.micros_wraparound_count);
      Serial1.print(",virtual_offset=");
      Serial1.print((unsigned long)(advanced_timing.virtual_micros_offset >> 20)); // Show in ~1M increments
      Serial1.print(",reset_detected=");
      Serial1.print(advanced_timing.clock_reset_detected ? 1 : 0);
      Serial1.print(",ref_updates=");
      Serial1.print(advanced_timing.reference_updates_count);
      Serial1.print(",sample_index=");
      Serial1.print((unsigned long)advanced_timing.sample_index);
      Serial1.print(",pps_phase_lock=");
      Serial1.print(advanced_timing.pps_phase_lock_enabled ? 1 : 0);
      Serial1.println();
    }
    else if (command == "SET_OUTPUT_FORMAT") {
      if (params == "COMPACT") {
        compact_output = true;
        Serial1.println("OK:Output format set to COMPACT");
      } else if (params == "FULL") {
        compact_output = false;
        Serial1.println("OK:Output format set to FULL");
      } else {
        Serial1.println("ERROR:Invalid format (COMPACT or FULL)");
      }
    }
    else if (command == "GET_OUTPUT_FORMAT") {
      Serial1.print("OUTPUT_FORMAT:");
      Serial1.print(compact_output ? "COMPACT" : "FULL");
      Serial1.print(",bytes_per_sample=");
      Serial1.print(compact_output ? 25 : 40);
      Serial1.println();
    }
    else if (command == "SET_SEQUENCE_VALIDATION") {
      if (params == "ON") {
        seq_validator.validation_enabled = true;
        Serial1.println("OK:Sequence validation enabled");
      } else if (params == "OFF") {
        seq_validator.validation_enabled = false;
        Serial1.println("OK:Sequence validation disabled");
      } else {
        Serial1.println("ERROR:Invalid parameter (ON or OFF)");
      }
    }
    else if (command == "GET_SEQUENCE_VALIDATION") {
      Serial1.print("SEQUENCE_VALIDATION:");
      Serial1.print(seq_validator.validation_enabled ? "ON" : "OFF");
      Serial1.print(",gaps_detected=");
      Serial1.print(seq_validator.sequence_gaps_detected);
      Serial1.print(",resets_detected=");
      Serial1.print(seq_validator.sequence_resets_detected);
      Serial1.print(",expected_seq=");
      Serial1.print(seq_validator.expected_sequence);
      Serial1.println();
    }
    else if (command == "RESET") {
      streaming = false;
      advanced_timing.timing_established = false;
      sequence = 0;
      // Reset session header flag for next stream
      session_tracker.session_header_sent = false;
      Serial1.println("OK:Device reset");
    }
    else if (command == "SET_CAL_PPM") {
      float ppm_value = params.toFloat();
      advanced_timing.oscillator_calibration_ppm = ppm_value;
      advanced_timing.calibration_valid = true;
      
      // Apply hard limits and sanity checks
      clampOscillatorCalibration();
      
      // Save calibration to EEPROM for future boots
      saveOscillatorCalibration();
      
      Serial1.print("OK:Manual calibration set to ");
      Serial1.print(advanced_timing.oscillator_calibration_ppm, 2);
      Serial1.println(" ppm");
    }
    else {
      Serial1.println("ERROR:Unknown command");
    }
  } else {
    Serial1.println("ERROR:Invalid command format");
  }
}

bool verifyADCThroughput() {
  // Calculate required throughput: channels × oversample × stream_rate × 2 (for filter + MUX overhead)
  uint32_t required_samples_per_sec = num_channels * max(1, current_dithering) * stream_rate * 2;
  
  // Get ADC rate in samples per second
  uint32_t adc_rate_sps;
  switch(current_adc_rate) {
    case ADS126X_RATE_2_5: adc_rate_sps = 2; break;
    case ADS126X_RATE_5: adc_rate_sps = 5; break;
    case ADS126X_RATE_10: adc_rate_sps = 10; break;
    case ADS126X_RATE_16_6: adc_rate_sps = 16; break;
    case ADS126X_RATE_20: adc_rate_sps = 20; break;
    case ADS126X_RATE_50: adc_rate_sps = 50; break;
    case ADS126X_RATE_60: adc_rate_sps = 60; break;
    case ADS126X_RATE_100: adc_rate_sps = 100; break;
    case ADS126X_RATE_400: adc_rate_sps = 400; break;
    case ADS126X_RATE_1200: adc_rate_sps = 1200; break;
    case ADS126X_RATE_2400: adc_rate_sps = 2400; break;
    case ADS126X_RATE_4800: adc_rate_sps = 4800; break;
    case ADS126X_RATE_7200: adc_rate_sps = 7200; break;
    case ADS126X_RATE_14400: adc_rate_sps = 14400; break;
    case ADS126X_RATE_19200: adc_rate_sps = 19200; break;
    case ADS126X_RATE_38400: adc_rate_sps = 38400; break;
    default: adc_rate_sps = 19200; break;
  }
  
  bool adequate = adc_rate_sps >= required_samples_per_sec;
  
  if (!adequate && !adc_monitor.throughput_warning_sent) {
    Serial1.print("WARNING:ADC throughput inadequate - required: ");
    Serial1.print(required_samples_per_sec);
    Serial1.print(" sps, available: ");
    Serial1.print(adc_rate_sps);
    Serial1.println(" sps");
    adc_monitor.throughput_warning_sent = true;
  } else if (adequate && adc_monitor.throughput_warning_sent) {
    adc_monitor.throughput_warning_sent = false;
  }
  
  return adequate;
}

long readADC(int pos_pin, int neg_pin) {
  adc.setInputPins(pos_pin, neg_pin);
  
  uint32_t startTime = micros();
  uint32_t timeout_us = 10000; // 10ms timeout
  
  // Wait for DRDY with timeout
  while(digitalRead(drdy_pin) == HIGH) {
    if (micros() - startTime > timeout_us) {
      adc_monitor.deadline_misses++;
      return 0;
    }
  }
  
  uint32_t conversion_time = micros() - startTime;
  adc_monitor.total_conversions++;
  
  // Track conversion timing statistics
  if (adc_monitor.total_conversions == 1) {
    adc_monitor.min_conversion_time_us = conversion_time;
    adc_monitor.max_conversion_time_us = conversion_time;
  } else {
    if (conversion_time > adc_monitor.max_conversion_time_us) {
      adc_monitor.max_conversion_time_us = conversion_time;
    }
    if (conversion_time < adc_monitor.min_conversion_time_us) {
      adc_monitor.min_conversion_time_us = conversion_time;
    }
  }
  
  return adc.readADC1();
}

void sendSessionHeader() {
  if (session_tracker.session_header_sent) {
    return;  // Already sent for this session
  }
  
  // Generate new stream_id for this session
  session_tracker.stream_id = millis();
  
  // Send session header with metadata
  Serial1.print("SESSION:");
  Serial1.print(session_tracker.boot_id);
  Serial1.print(",");
  Serial1.print(session_tracker.stream_id);
  Serial1.print(",");
  Serial1.print(stream_rate);
  Serial1.print(",");
  Serial1.print(num_channels);
  Serial1.print(",");
  Serial1.print(current_adc_filter);
  Serial1.print(",");
  Serial1.print(current_adc_gain);
  Serial1.print(",");
  Serial1.print(current_dithering);
  Serial1.print(",");
  Serial1.print(getTimingSourceName(advanced_timing.current_source));
  Serial1.print(",");
  Serial1.print(advanced_timing.oscillator_calibration_ppm, 2);
  Serial1.println();
  
  session_tracker.session_header_sent = true;
}

void clampOscillatorCalibration() {
  // Hard limits and sanity checks: clamp oscillator_calibration_ppm to ±200 ppm
  if (advanced_timing.oscillator_calibration_ppm > 200.0) {
    Serial1.print("WARNING:Oscillator calibration clamped from ");
    Serial1.print(advanced_timing.oscillator_calibration_ppm, 2);
    Serial1.println(" ppm to 200 ppm");
    advanced_timing.oscillator_calibration_ppm = 200.0;
  } else if (advanced_timing.oscillator_calibration_ppm < -200.0) {
    Serial1.print("WARNING:Oscillator calibration clamped from ");
    Serial1.print(advanced_timing.oscillator_calibration_ppm, 2);
    Serial1.println(" ppm to -200 ppm");
    advanced_timing.oscillator_calibration_ppm = -200.0;
  }
}

void sendHealthBeacon() {
  unsigned long current_time = millis();
  
  // Check if it's time to send STAT line (1 Hz)
  if (current_time - advanced_timing.last_stat_time >= advanced_timing.stat_interval_ms) {
    unsigned long pps_age_ms = current_time - advanced_timing.last_pps_time;
    
    Serial1.print("STAT:");
    Serial1.print(getTimingSourceName(advanced_timing.current_source));
    Serial1.print(",");
    Serial1.print(advanced_timing.timing_accuracy_us, 1);
    Serial1.print(",");
    Serial1.print(advanced_timing.oscillator_calibration_ppm, 2);
    Serial1.print(",");
    Serial1.print(advanced_timing.pps_valid ? 1 : 0);
    Serial1.print(",");
    Serial1.print(pps_age_ms);
    Serial1.print(",");
    Serial1.print(advanced_timing.micros_wraparound_count);
    Serial1.print(",");
    Serial1.print(serial_monitor.buffer_overflows);
    Serial1.print(",");
    Serial1.print(serial_monitor.samples_skipped_due_to_overflow);
    Serial1.print(",");
    Serial1.print(session_tracker.boot_id);
    Serial1.print(",");
    Serial1.print(session_tracker.stream_id);
    Serial1.print(",");
    Serial1.print(adc_monitor.deadline_misses);
    Serial1.println();
    
    advanced_timing.last_stat_time = current_time;
  }
}

bool isRateChangeAllowed(float new_rate) {
  // Calculate rate change in ppm
  float rate_change_ppm = abs((new_rate - stream_rate) / stream_rate) * 1e6;
  
  // Check if we're PPS-locked
  bool pps_locked = (advanced_timing.current_source == AdvancedTiming::TIMING_PPS_ACTIVE);
  
  if (pps_locked && rate_change_ppm > 50) {
    // Reject large rate changes while PPS-locked
    Serial1.print("ERROR:Rate change too large while PPS locked (");
    Serial1.print(rate_change_ppm, 1);
    Serial1.println(" ppm > 50 ppm limit)");
    return false;
  }
  
  // Allow small changes (e.g., 0.1%) for intentional experiments
  if (rate_change_ppm > 1000) {  // 0.1% = 1000 ppm
    Serial1.print("WARNING:Large rate change detected (");
    Serial1.print(rate_change_ppm, 1);
    Serial1.println(" ppm)");
  }
  
  return true;
}

// EEPROM addresses for calibration storage
#define EEPROM_CAL_MAGIC_ADDR 0
#define EEPROM_CAL_PPM_ADDR 4
#define EEPROM_CAL_MAGIC 0x12345678

void saveOscillatorCalibration() {
  // Save oscillator calibration to EEPROM for boot without GPS
  EEPROM.put(EEPROM_CAL_MAGIC_ADDR, EEPROM_CAL_MAGIC);
  EEPROM.put(EEPROM_CAL_PPM_ADDR, advanced_timing.oscillator_calibration_ppm);
  
  Serial1.print("DEBUG:Saved oscillator calibration to EEPROM: ");
  Serial1.print(advanced_timing.oscillator_calibration_ppm, 2);
  Serial1.println(" ppm");
}

void loadOscillatorCalibration() {
  // Load oscillator calibration from EEPROM on boot
  uint32_t magic;
  float stored_ppm;
  
  EEPROM.get(EEPROM_CAL_MAGIC_ADDR, magic);
  EEPROM.get(EEPROM_CAL_PPM_ADDR, stored_ppm);
  
  if (magic == EEPROM_CAL_MAGIC && abs(stored_ppm) <= 200.0) {
    advanced_timing.oscillator_calibration_ppm = stored_ppm;
    advanced_timing.calibration_valid = true;
    
    Serial1.print("DEBUG:Loaded oscillator calibration from EEPROM: ");
    Serial1.print(stored_ppm, 2);
    Serial1.println(" ppm");
  } else {
    Serial1.println("DEBUG:No valid calibration found in EEPROM");
  }
}

float readInternalTemperature() {
  // Read internal temperature sensor (if available on the MCU)
  // This is a placeholder - actual implementation depends on MCU type
  // For SAMD21/SAMD51, you might use ADC to read internal temperature sensor
  
  // Placeholder: return a reasonable temperature
  // In a real implementation, you would:
  // 1. Enable internal temperature sensor
  // 2. Read ADC value
  // 3. Convert to temperature using MCU-specific formula
  
  return 25.0;  // Placeholder temperature
}

void updateTemperatureCompensation() {
  // Update temperature compensation for holdover mode
  if (!advanced_timing.temp_compensation_enabled) {
    return;
  }
  
  float new_temp = readInternalTemperature();
  float temp_change = new_temp - advanced_timing.reference_temp_c;
  
  // Apply temperature compensation to oscillator calibration
  float temp_correction = temp_change * advanced_timing.temp_coefficient_ppm_per_c;
  
  // Only apply if we're in CAL mode (holdover without PPS)
  if (advanced_timing.current_source == AdvancedTiming::TIMING_INTERNAL_CAL) {
    advanced_timing.oscillator_calibration_ppm += temp_correction;
    
    // Clamp the result
    clampOscillatorCalibration();
    
    Serial1.print("DEBUG:Temperature compensation applied: ");
    Serial1.print(temp_change, 1);
    Serial1.print("°C, correction: ");
    Serial1.print(temp_correction, 2);
    Serial1.println(" ppm");
  }
  
  advanced_timing.current_temp_c = new_temp;
}