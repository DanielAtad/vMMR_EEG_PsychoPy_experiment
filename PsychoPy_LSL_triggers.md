# PsychoPy and LSL Triggers in the vMMR Experiment

Last verified against the current source code: 2026-07-14.

## Purpose and scope

This document explains the repository layout and the complete trigger path used
by the current PsychoPy vMMR experiment. It covers:

- which files control the experiment, timing, LSL stream, diagnostics, and EEG
  acquisition;
- how a trial-table row becomes a face-event marker;
- how PsychoPy schedules the visual flip and marker callback;
- how `LSLTrigger` represents markers as a continuous latched state channel;
- which clock supplies each saved timestamp;
- how markers reach Simulink and the g.HIamp recording;
- how the photodiode path complements LSL;
- how startup, abort, and shutdown are handled;
- which files should be used for offline event interpretation;
- how to test and troubleshoot the implementation.

The executable source code is the authority for the behavior described here.
Some older repository notes describe a planned or previous marker protocol; the
differences are listed explicitly near the end of this document.

## Repository layout

```text
vMMR_EEG_PsychoPy_experiment/
├── run_vMMR_experiment_v0.py
├── lsl_trigger.py
├── timing_utils.py
├── run_timing_decomposition_v0.py
├── run_vMMR_experiment_20260526.py
├── run_vMMR_experiment_20260609.py
├── HIamp_record_LSL_DD_vMMR.slx
├── HIamp_record_LSL_DD_photodiode_delay_test.slx
├── environment.yml
├── README.md
├── AGENTS.md
├── ToDo.md
├── PsychoPy_LSL_triggers.md
├── conditions/
│   ├── practice_trials.csv
│   ├── main_trials.csv
│   └── generate_trials.ipynb
├── stimuli/
│   ├── faces/
│   │   ├── self.png
│   │   ├── other.png
│   │   ├── morph50.png
│   │   ├── self_target.png
│   │   ├── other_target.png
│   │   └── morph50_target.png
│   ├── words/
│   └── triggers.md
├── notebooks/
├── tests/
│   ├── conftest.py
│   ├── test_lsl_trigger.py
│   ├── test_timing_utils.py
│   └── test_trigger_backends_static.py
└── data/
    └── .gitkeep
```

### Active experiment files

#### `run_vMMR_experiment_v0.py`

This is the active PsychoPy Coder experiment. It is responsible for:

- showing the startup dialog;
- selecting the LSL or no-op parallel-port backend;
- opening the PsychoPy window with `waitBlanking=True`;
- validating the configured and measured monitor refresh rates;
- loading practice and main condition tables;
- preloading all face images before trials begin;
- presenting fixation, Hebrew prime text, faces, blanks, instructions, and
  breaks;
- drawing the optional photodiode square;
- mapping each face event to an integer marker code;
- scheduling face-onset timestamps and trigger delivery on the display flip;
- collecting keyboard responses;
- writing event, trial, frame-interval, run-information, and PsychoPy log files;
- running the photodiode and LSL-buffer diagnostic modes;
- sending the final marker and closing the trigger backend safely.

#### `lsl_trigger.py`

This file implements `LSLTrigger`, the continuous LSL marker outlet used by the
experiment and the timing diagnostic. It owns:

- LSL stream metadata;
- the marker state and expiry time;
- the keepalive thread;
- locking around every outlet push;
- exact event-sample timestamps;
- consumer detection;
- marker clearing;
- idempotent final-marker shutdown.

#### `timing_utils.py`

This file contains pure timing helpers shared by the main experiment and timing
diagnostic:

- `seconds_to_frames(seconds, refresh_hz)`;
- validation of the operator-entered `expected_refresh_hz`;
- comparison of the measured and expected refresh rates;
- calculation of refresh-rate diagnostic metadata.

The supported nominal display rates are 60 and 120 Hz. Monitor refresh affects
display frame counts only. It does not control the LSL keepalive rate or LSL
nominal sampling rate.

#### `run_timing_decomposition_v0.py`

This is a standalone timing diagnostic, not the scientific vMMR task. It can
compare PRE_FLIP, ON_FLIP, and POST_FLIP marker scheduling, photodiode position,
luminance, and display-independent marker cadence. It uses `LSLTrigger` and the
same refresh-rate helpers, but it has its own diagnostic marker namespace and
output files.

#### Historical dated scripts

`run_vMMR_experiment_20260526.py` and
`run_vMMR_experiment_20260609.py` are historical snapshots. They retain older
parallel-port pulse behavior and must not be assumed to have the same LSL latch,
timestamp, shutdown, or refresh-rate behavior as
`run_vMMR_experiment_v0.py`.

### Conditions and stimuli

`conditions/practice_trials.csv` and `conditions/main_trials.csv` define the
trial rows. The trigger-relevant columns are:

```text
primeType
identity
nStandards
isTarget
targetPosition
standardImage
deviantImage
standardTargetImage
deviantTargetImage
```

The trial builder creates `nStandards` standard events followed by one deviant
event. A target trial replaces exactly one standard or deviant image with its
sunglasses version and changes the event role to `TARGET_STD` or `TARGET_DEV`.

The face images under `stimuli/faces/` are loaded into PsychoPy `ImageStim`
objects before practice or main trials begin. Image files are never loaded in a
face-event loop, which avoids disk I/O during timing-critical presentation.

### Simulink and acquisition files

- `HIamp_record_LSL_DD_vMMR.slx` is the Simulink model for the experiment.
- `HIamp_record_LSL_DD_photodiode_delay_test.slx` is the model for optical/LSL
  timing validation.

The intended acquisition arrangement is:

```text
Condition identity path
PsychoPy -> pylsl outlet -> network -> Simulink LSL inlet -> saved EEG record

Physical visual-onset path
Monitor white square -> GTEC-0270 optical sensor -> g.TRIGbox
    -> GTEC-0274TR adapter -> g.HIamp DIGITAL IN -> saved EEG record
```

These paths answer different questions:

- LSL says which experimental event PsychoPy intended to present.
- The photodiode channel says when the monitor physically emitted light.

The photodiode/g.TRIGbox signal is therefore the authoritative measurement of
actual photon onset. LSL is the event label and software-timing channel.

### Tests

The `tests/` directory contains hardware-free tests:

- `test_lsl_trigger.py` uses a fake LSL outlet to verify explicit timestamps,
  latch expiry, zero intervals, repeated rising edges, final marker duration,
  and idempotent shutdown;
- `test_timing_utils.py` verifies frame counts and refresh validation at 60 and
  120 Hz;
- `test_trigger_backends_static.py` verifies that LSL does not require manual
  clearing and that frame-two clearing is conditional on the active backend.

Run them from the repository root with:

```bash
pytest -q
```

These tests do not replace a PsychoPy, Simulink, g.HIamp, or photodiode hardware
test.

## End-to-end trigger architecture

The main face-onset path is:

```text
trial CSV row
    -> build_face_sequence()
    -> event role: STD / DEV / TARGET_STD / TARGET_DEV
    -> TRIGGER_MAP[(primeType, identity, role)]
    -> present_face_event()
    -> draw prime + face + optional photodiode square
    -> win.timeOnFlip(): save PsychoPy flip time
    -> win.callOnFlip(): save target time on keyboard clock, when applicable
    -> win.callOnFlip(): call LSLTrigger.set_with_timestamp(code)
    -> win.flip()
    -> explicit int32 event sample enters the LSL stream
    -> keepalive thread repeats the latched code for approximately 100 ms
    -> keepalive thread returns the stream state to zero
    -> Simulink samples the state channel and records it with EEG
```

The ordering of the flip callbacks is intentional. PsychoPy records the flip
time first, records the target onset on the response clock second, and performs
the LSL outlet operation third. This prevents the saved PsychoPy onset from
including time spent waiting for the LSL lock or pushing the network sample.

## Startup and trigger-backend selection

The startup dialog includes:

```text
participant
session
fullscreen
expected_refresh_hz
send_LSL_triggers
parallel_port_address
photodiode_square
photodiode_test_mode
lsl_buffer_test_mode
lsl_keepalive_hz
lsl_nominal_srate
```

When `send_LSL_triggers` is checked, the experiment constructs:

```python
LSLTrigger(
    enabled=True,
    keepalive_hz=lsl_keepalive_hz,
    nominal_srate=lsl_nominal_srate,
)
```

The outlet is created before the PsychoPy window. When the installed `pylsl`
supports `StreamOutlet.wait_for_consumers`, the experiment waits up to 15
seconds for the Simulink inlet. If no consumer connects, the run aborts before
participant data collection. If the method is unavailable, the script retains
the manual workflow: start Simulink and press Enter to continue.

When `send_LSL_triggers` is unchecked, the current main script constructs an
`EEGTrigger` with `enabled=False`, because `send_eeg_triggers` is hard-coded to
`False`. In this configuration, all marker calls are no-ops. Although the
parallel-port wrapper remains in the source for compatibility, the startup
dialog does not currently enable it.

## LSL stream definition

The default stream metadata in `lsl_trigger.py` is:

| Property | Current value |
|---|---|
| Stream name | `experiment_markers` |
| Stream type | `Markers` |
| Source ID | `vmmr_exp` |
| Channel count | `1` |
| Channel format | `int32` |
| Nominal sampling rate | `1200` Hz |
| Keepalive rate | `1200` Hz |
| Marker hold duration | `0.100` s |
| Manual display-frame clear | `False` |

`lsl_keepalive_hz` and `lsl_nominal_srate` can be changed in the startup dialog,
but both must be positive. The 100 ms hold duration is currently a code default,
not a dialog field.

## Why the stream is latched

The Simulink receiver expects a continuously sampled marker channel. A marker
that is nonzero for only one display frame can occur between two Simulink inlet
samples and be missed. The current implementation therefore does not treat a
marker as a single isolated packet. It treats it as the current value of a
continuous state channel.

The idle state is zero:

```text
..., 0, 0, 0, 0, 0, ...
```

Calling `set(12)` changes the current state to 12. The keepalive thread repeats
that value until the hold duration expires:

```text
..., 0, 0, 12, 12, 12, 12, ..., 12, 0, 0, 0, ...
```

The precise number of repeated samples depends on scheduling and receiver
sampling, but the intended nonzero duration is 100 ms. At a 1200 Hz keepalive
rate, the thread wakes approximately every 0.833 ms. Once the expiry time has
passed, the next keepalive iteration changes the state to zero.

The face SOA is 600 ms, so a 100 ms latch leaves a substantial zero interval
before the next face marker. This matters when two successive faces use the
same code: the zero interval creates a new rising edge for the second event.

### Correct offline event detection

Do not count every nonzero sample as a separate event. Detect the transition
from idle to a nonzero state:

```text
previous marker == 0 and current marker != 0
```

The value reached on that transition is the event code. Repeated nonzero
samples during the 100 ms latch are copies of the same event.

If the recording system resamples or filters the marker channel, event
detection should be performed on the original discrete marker values whenever
possible. Do not apply ordinary analog filtering to the integer marker channel.

## Threading and outlet safety

`LSLTrigger` has two possible producers:

1. PsychoPy's main thread pushes event samples.
2. The keepalive thread repeatedly pushes the current state.

Both use the same `threading.Lock`. Every outlet push occurs while this lock is
held. This prevents the keepalive thread and a face-onset callback from calling
`StreamOutlet.push_sample()` simultaneously or updating `_current_value` and
`_expiry` inconsistently.

The keepalive loop performs the following operations:

1. acquire the outlet lock;
2. compare `pylsl.local_clock()` with `_expiry`;
3. change `_current_value` to zero when the latch has expired;
4. push the current state;
5. release the lock;
6. wait for the next keepalive interval without busy-spinning.

## Exact event-sample timestamp

`set_with_timestamp(code)` is the authoritative event push method. Its sequence
is:

1. convert `code` to an integer;
2. acquire the outlet lock;
3. obtain `timestamp = pylsl.local_clock()`;
4. store the new current marker value;
5. calculate `_expiry = timestamp + hold_duration`;
6. push `[value]` with that exact timestamp and `pushthrough=True`;
7. release the lock;
8. return the same timestamp to the caller.

The returned timestamp is therefore exactly the timestamp attached to the
explicit event sample. It is not a timestamp obtained before waiting for the
lock, and it is not wall-clock time from `datetime`.

Keepalive samples do not need this returned event timestamp. Their timestamps
are assigned by pylsl when the repeated state sample is pushed.

## PsychoPy flip scheduling

During each face-on period, `present_face_event()` draws:

- the Hebrew prime word;
- the selected face image;
- the optional white photodiode square.

On the first face frame, callbacks are queued in this order:

1. `win.timeOnFlip(onset, "global")` records the PsychoPy flip timestamp;
2. for target events, `kb.clock.getTime()` records the target onset in the same
   clock domain as response key times;
3. `_send_marker_and_store_lsl_timestamp()` calls
   `trigger.set_with_timestamp(code)`.

All three actions are associated with the same `win.flip()` that first presents
the face and photodiode square. The LSL operation occurs after the PsychoPy and
keyboard timing values have been captured.

### Backend-specific clearing

The main script supports two trigger semantics:

| Backend | `requires_manual_clear` | Clearing behavior |
|---|---:|---|
| `LSLTrigger` | `False` | Automatically expires after 100 ms |
| Active `EEGTrigger` parallel port | `True` | Clears on the second display frame |
| Disabled/no-op backend | `False` on the instance | No clear callback is scheduled |

The helper `_schedule_manual_clear_if_required()` is called from:

- real face presentation;
- photodiode test flashes;
- LSL buffer test flashes.

It schedules `win.callOnFlip(trigger.clear)` only when the backend explicitly
requires manual clearing. Clearing LSL one frame after onset would defeat the
latch and recreate the missing-marker failure mode.

## Current experimental marker codes

The face code is selected from `(primeType, identity, eventRole)`.

| Prime | Identity | Standard | Deviant | Target standard | Target deviant |
|---|---|---:|---:|---:|---:|
| DEATH | SELF | 11 | 12 | 13 | 14 |
| DEATH | OTHER | 21 | 22 | 23 | 24 |
| NEGATIVE | SELF | 31 | 32 | 33 | 34 |
| NEGATIVE | OTHER | 41 | 42 | 43 | 44 |

The ordinary `STD` marker is the same for all standard positions in a given
condition. The LSL code alone does not identify whether a standard was first,
second, or third. Use `eventIndex` and `isAnalysisStandard` from the events CSV
to select the third standard used in the principal vMMR comparison.

Target events have distinct LSL codes, but target-trial exclusion should also
use `isTargetTrial`, `eventRole`, `isAnalysisStandard`, and
`isAnalysisDeviant` from the events file.

### System and diagnostic markers in the main script

| Code | Current use |
|---:|---|
| 0 | Idle marker state |
| 9 | Experiment start; also LSL-buffer-test start |
| 11-44 | Experimental face onsets, according to the table above |
| 99 | Experiment end or abort |
| 99 | Also each photodiode-test flash marker in photodiode-test mode |
| 101-200 | Unique flash markers in LSL-buffer-test mode |

Marker 99 has two meanings only because the photodiode test is a separate mode:
it labels each calibration flash there and is also sent during final shutdown.
Interpret it using the run mode and sequence context.

### Markers not emitted by the current main script

The active `run_vMMR_experiment_v0.py` does not currently send separate markers
for:

- prime-word onset;
- trial fixation onset;
- practice start or end;
- main-experiment start;
- block start or end;
- rest start or end;
- participant button presses.

Those events may appear in older planning documentation, but there are no
corresponding `trigger.set()` or `win.callOnFlip()` calls for them in the active
main script. Adding them would be a marker-protocol change and should not be
done silently.

### Timing-decomposition marker namespace

`run_timing_decomposition_v0.py` is separate from the scientific experiment and
uses context-specific diagnostic markers:

| Code/range | Diagnostic use |
|---:|---|
| 9 | Diagnostic start |
| 10-18 | Scheduling × luminance flash conditions |
| 20 | Latency-only flashes |
| 60 | Threshold-tuning flash onset |
| 200-202 | Position-block boundaries |
| 250 | Cadence-block start |
| 101-220 | Cadence markers |
| 255 | Diagnostic end or abort |

Some diagnostic ranges overlap by value, but they occur in distinct blocks and
are disambiguated by the preceding block marker and diagnostic output files.

## Timestamp domains

The experiment records several different notions of time:

| Timestamp | Source | Meaning |
|---|---|---|
| PsychoPy flip timestamp | `win.timeOnFlip()` | Software timestamp assigned to the display flip |
| Target onset | `kb.clock.getTime()` | Target time in the same clock domain as response times |
| LSL event timestamp | `pylsl.local_clock()` | Exact timestamp attached to the explicit event sample |
| Photodiode edge | Recorded optical channel | Physical luminance onset detected from the monitor |

Do not directly subtract a PsychoPy timestamp from an LSL timestamp unless the
two clocks have first been mapped to a common origin. Being scheduled on the
same flip does not guarantee identical clock epochs.

Likewise, neither software timestamp proves when photons appeared. Monitor scan
out, pixel response, optical-sensor threshold, and amplifier acquisition all
occur after the software submits the display frame. Use the recorded photodiode
edge for actual visual-onset alignment.

## Refresh-rate handling and trigger independence

The operator selects `expected_refresh_hz` as either 60 or 120. PsychoPy then
measures the actual display rate:

- a measurement within 2% of the expected rate is accepted;
- a larger mismatch aborts before practice or experimental trials;
- if no measurement is available, the run logs a warning and uses the expected
  rate for frame conversion and the dropped-frame threshold.

Every display duration is converted through `seconds_to_frames()`. For example:

| Duration | 60 Hz | 120 Hz |
|---|---:|---:|
| Face on, 250 ms | 15 frames | 30 frames |
| Blank, 350 ms | 21 frames | 42 frames |
| Face SOA, 600 ms | 36 frames | 72 frames |

The script explicitly verifies:

```text
face_on frames + blank frames == face_soa frames
```

The display rate and LSL stream rates are independent. Selecting a 120 Hz
monitor does not change the 1200 Hz keepalive or nominal LSL rate, and lowering
an LSL diagnostic rate must not change stimulus frame counts.

## Final marker and shutdown

The main experiment does not send marker 99 in the normal body and then
immediately clear it. Instead, every exit path reaches the `finally` block and
calls:

```python
trigger.finish(final_code=99)
```

For an enabled LSL outlet, `finish()`:

1. returns immediately if it already finished or stopped;
2. pushes the final marker;
3. keeps the outlet and keepalive thread active;
4. waits for `hold_duration + margin`, currently 100 ms + 50 ms;
5. explicitly clears the state to zero;
6. stops and joins the keepalive thread.

The wait uses a threading event rather than a busy loop. Normal completion,
Escape aborts, and unexpected exceptions all use this cleanup path. The final
marker is therefore given enough time to reach the consumer before the outlet
stops.

The parallel-port backend retains pulse-style cleanup rather than inheriting
the LSL wait behavior.

## Output files and their relation to triggers

Each ordinary experiment run creates files under `data/` using a base name such
as:

```text
<participant>_ses-<session>_<timestamp>
```

### `*_events.csv`

This is the primary event-description file. It contains one row per face event:

```text
participant, session, phase, block, trial_global, trial_in_block,
primeType, identity, condCode, word, nStandards,
isTargetTrial, targetPosition,
eventIndex, eventRole, eventImage,
isAnalysisStandard, isAnalysisDeviant,
triggerCode, onsetTime
```

`triggerCode` is the intended LSL/EEG condition code. `onsetTime` is the
PsychoPy flip timestamp, not the LSL timestamp and not the photodiode time.

### `*_trials.csv`

This contains one row per behavioral trial, including target onset, response
type, response time, number of presses, and correctness. It is not a sample-by-
sample record of the LSL stream.

### `*_frame_intervals.csv`

This stores PsychoPy frame intervals recorded during trials. Use it to find
dropped or delayed display frames. It does not prove LSL delivery or photon
onset.

### `*_run_info.txt`

This records session configuration and timing metadata, including:

- expected and measured refresh rate;
- whether refresh measurement succeeded;
- refresh-rate differences and dropped-frame threshold;
- intended, frame-count, and realized durations;
- whether LSL was enabled;
- LSL keepalive rate, nominal rate, and hold duration;
- whether the active backend requires manual clearing;
- LSL consumer-check availability and result;
- photodiode-square configuration;
- active diagnostic mode and diagnostic marker range.

### PsychoPy `.log`

The PsychoPy log contains warnings and exceptions, including refresh-measurement
failure, refresh mismatch, and trigger-shutdown errors.

### `*_photodiode_test.csv`

Photodiode-test mode flashes the white square 100 times, sends marker 99 on each
flash onset, writes the PsychoPy onset and intended durations, and exits before
practice. This file does not currently store the LSL timestamp for each flash.

### `*_lsl_buffer_test.csv`

LSL-buffer-test mode starts with marker 9, presents 100 flashes with codes
101-200, and records:

```text
flash_index
marker_code
psychopy_flip_timestamp
psychopy_global_onset_time
lsl_event_timestamp
lsl_push_timestamp
expected_refresh_hz
measured_refresh_hz
intended_on_duration
intended_off_duration
intended_initial_black_duration
frame_rate
on_frames
off_frames
initial_black_frames
notes
```

`psychopy_flip_timestamp` and `lsl_event_timestamp` should be inspected as
separate clock-domain measurements unless an explicit clock mapping is applied.

## Recommended offline event workflow

1. Load the integer marker channel saved by Simulink.
2. Detect zero-to-nonzero transitions rather than counting nonzero samples.
3. Read the marker value at each transition.
4. Match the code and event order to `*_events.csv`.
5. Use `eventIndex` and the analysis flags to select the third standard and
   final deviant on non-target trials.
6. Exclude target trials from the principal vMMR analysis.
7. Detect photodiode rising edges independently.
8. Match each optical edge to its corresponding face marker using event order,
   condition code, and the diagnostic protocol where applicable.
9. Use the optical edge for physical visual onset and the marker/events CSV for
   condition identity.
10. Review `*_frame_intervals.csv` and `*_run_info.txt` as timing-quality
    metadata.

## Operational checklist

### Ordinary experiment

1. Set the operating-system monitor mode to 60 or 120 Hz.
2. Start the appropriate Simulink model and EEG acquisition path.
3. Run `run_vMMR_experiment_v0.py` in PsychoPy Coder.
4. Set `expected_refresh_hz` to match the monitor mode.
5. Check `send_LSL_triggers` for an EEG run.
6. Enable `photodiode_square` only when optical validation is intended.
7. Leave both diagnostic modes unchecked.
8. Confirm that the LSL consumer is detected within 15 seconds, or complete the
   manual confirmation on older pylsl.
9. Confirm that the measured refresh rate passes validation.
10. After the run, verify start marker 9, face markers, final marker 99, zero
    intervals, frame intervals, and output-row counts.

### LSL buffer test

1. Place the optical sensor over the bottom-right white-square location.
2. Start the Simulink LSL inlet and EEG recording.
3. Select the correct `expected_refresh_hz`.
4. Check `send_LSL_triggers` and `lsl_buffer_test_mode`.
5. Leave `photodiode_test_mode` unchecked.
6. Confirm marker 9, markers 101-200, approximately 100 ms latches, zero
   intervals, optical edges, and final marker 99.
7. Compare the generated buffer-test CSV with the Simulink and optical data.

### Photodiode test

1. Place the GTEC-0270 sensor over the square.
2. Select the correct `expected_refresh_hz`.
3. Check `photodiode_test_mode`.
4. Check `send_LSL_triggers` when comparing software marker 99 with the optical
   edge.
5. Leave `lsl_buffer_test_mode` unchecked.
6. Confirm 100 optical flashes, corresponding markers, and the final shutdown
   marker.

## Troubleshooting

### No LSL consumer detected

- Start the correct Simulink model before or immediately after creating the
  outlet.
- Confirm that the Simulink inlet searches for stream name
  `experiment_markers` and type `Markers`.
- Check firewall and network configuration between the PsychoPy and acquisition
  computers.
- Confirm that both computers can discover LSL streams.
- Do not bypass the 15-second failure and collect participant data without
  confirming marker reception.

### Many apparent duplicate markers

This usually means the analysis is counting every nonzero keepalive sample.
Detect zero-to-nonzero transitions. Repeated values during the latch are one
event, not duplicates.

### Markers are missing

- Confirm that the analysis detects rising edges and that the marker channel
  was not filtered or converted incorrectly.
- Confirm that the active file is `run_vMMR_experiment_v0.py`, not a historical
  dated script.
- Confirm `send_LSL_triggers` was checked and the run-info file reports it as
  enabled.
- Verify the Simulink inlet was connected before trials began.
- Inspect the buffer diagnostic to separate LSL/Simulink loss from optical or
  event-matching errors.

### Final marker is missing

- Check the PsychoPy log for a shutdown error.
- Confirm the current `LSLTrigger.finish()` implementation is in use.
- Confirm the receiver continued recording for at least 150 ms after marker 99.
- Ensure acquisition was not stopped manually before PsychoPy finished cleanup.

### PsychoPy and LSL timestamps appear far apart

They may use different clock origins. Do not interpret their raw subtraction as
latency. Use an explicit clock mapping or compare both against markers recorded
within the same acquisition system.

### LSL and photodiode differ

A difference is expected because they measure different stages. Investigate:

- PsychoPy callback scheduling;
- monitor refresh and scan-out position;
- display pixel response;
- optical-sensor threshold;
- g.TRIGbox and amplifier timing;
- LSL transport and Simulink buffering;
- incorrect matching between a photodiode pulse and face-event code.

Use `run_timing_decomposition_v0.py` and the LSL-buffer test to separate these
components.

### Refresh-rate mismatch

If the configured expected rate is 60 but PsychoPy measures about 120, or vice
versa, change the operating-system display mode or the startup selection. Do
not continue with mismatched frame counts.

## Important documentation differences

`stimuli/triggers.md` describes an older or planned trigger implementation. It
currently contains details that do not match the active executable code,
including a 10 Hz zero-only keepalive, one-frame LSL pulses, start marker 1, and
prime/fixation/phase/response markers. The current implementation instead uses:

- a configurable keepalive defaulting to 1200 Hz;
- a continuous sample-and-hold state channel;
- a 100 ms nonzero latch;
- start marker 9;
- face markers 11-44;
- final marker 99;
- mode-specific diagnostic markers;
- no active prime, fixation, phase, or response-marker calls.

Parts of `AGENTS.md` may also describe the broader intended marker protocol.
Before adding any planned marker, decide whether the Simulink model and analysis
pipeline expect it, assign a non-conflicting code, schedule visual-onset markers
with `win.callOnFlip()`, document the change, and validate it with the acquisition
hardware.

## Safe modification rules

When changing trigger behavior:

- keep `LSLTrigger.requires_manual_clear = False`;
- never clear LSL on the second display frame;
- keep event-sample timestamp generation inside the outlet lock;
- pass the returned LSL timestamp explicitly to the event `push_sample()`;
- record PsychoPy flip and keyboard times before the LSL outlet callback;
- keep every outlet push protected by the same lock;
- preserve a zero interval between successive nonzero marker states;
- keep LSL rates independent of monitor refresh rate;
- keep the final marker alive through the configured hold duration;
- preserve the photodiode square on the same face-on frame;
- do not infer actual photon onset from LSL alone;
- do not change experimental marker codes or scientific event roles silently;
- update tests, run-info diagnostics, and documentation with every protocol
  change;
- validate the full path on the lab monitor, Simulink model, g.HIamp, and optical
  sensor before collecting participant data.
