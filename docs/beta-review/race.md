# Concurrency, lifecycle and response-proof review

Reviewed exact upstream `v1.2.3-beta.1`, commit `ac928a73c3bed22cd00d5e5d875c6ff72445ab06`. Source paths below are relative to that tree. Read-only review; no integration changes, Home Assistant calls, device operation, BLE/network access, credentials or private identifiers. Findings are confirmed from control flow, not physical reproduction. **No offline runtime probes were executed by this reviewer.** Proposed tests below are recipes for a deterministic harness, not passing safety tests. `git diff v1.2.2..v1.2.3-beta.1` was inspected to distinguish inherited behavior from beta additions.

## Source-confirmed findings

### R1 — P1: the connection lock does not serialize operations or protect the handshake

`custom_components/scent_assistant/device.py:283–308,327–345,575–617,1144–1172`.

The connection is marked connected at line 333 before notification subscription and protocol login complete. A second call takes the connected fast path at 287–289 without acquiring `_ble_lock`, and can issue its command while the first connection is still subscribing or logging in. On an established connection, `_ble_send` also writes outside the lock. Two commands can interleave their chunks; AK V3 command-plus-commit pairs (`protocol_ble.py:1289–1313`) and GW chunked frames are not operation-atomic. A refresh can likewise overlap command execution. GATT writes alone cannot establish that an interleaved protocol command was applied.

Inherited from v1.2.2; the beta's new periodic refresh adds another concurrent producer. Its `_momentary_task` check at 1137 is not serialization: a refresh may start before a run is registered, and a run may start after a refresh passes the check. The starting run has no timer handle until its ON operation returns at 825–831.

Minimal direction: one per-device operation owner spanning connect, handshake completion, command construction, all wire chunks, response handling and teardown. Separate transport-connected from protocol-ready. Do not introduce a non-reentrant lock around calls that recursively acquire it. Contention should queue with explicit cancellation, rather than look like a device failure.

Fake test: block `start_notify` using an event, launch a second real `set_power`, and record whether any state-changing write happens while the handshake is blocked. Separately gate two `write_gatt_char` calls and demonstrate overlapping writes or interleaved real protocol chunks. A characterization test asserting the overlap demonstrates the defect; a future regression test must require no overlap.

### R2 — P1: AK commands are constructed before reconnect establishes their protocol and state

`device.py:790–793,847–850`; `protocol_ble.py:954–972,988–1031,1330–1362`; `device.py:362–415`.

`set_power` and `set_fan` build immutable command bytes before `_ble_execute` connects. AK reconnect subsequently resets protocol detection and reads device control state. An initially unknown AK device selects the V2 fan encoding before a successful handshake identifies V3. A power command also captures the previous control-bit cache before reconnect receives current values; the already-built bytes can overwrite unrelated bits. Builders themselves optimistically mutate `_ctrl_bits` before any write succeeds. This is an inherited sequencing defect, not a beta regression.

Minimal direction: submit a command intent, connect and validate protocol readiness under the operation owner, then construct from validated current state. Track requested fields separately from reported fields so failed writes do not become authoritative cache input. Do not use a power request as authority to change unrelated controls.

Fake test: start a real AK device with unknown version, invoke `set_fan`, inject a V3 login reply from the fake transport during connection, and inspect the eventual write opcode. For power, inject changed unrelated control bits during handshake and compare emitted bytes with the requested field and current report.

### R3 — P1: momentary retrigger can discard its existing cutoff, and concurrent starts can create unowned timers

`device.py:810–841`.

The existing task is canceled and the sole reference cleared at 821–823 before replacement ON succeeds. If a new ON fails, the method returns at 826 with no replacement cutoff, even if the device remains on from its earlier successful run. A transport failure does not prove stopped state. Two concurrent starts can both pass this cancellation section before either awaited ON completes; both then create `_momentary_off_later` tasks, and only the last task is retained. The older task can stop the newer run early and cannot be found by the normal shutdown path. This violates the documented behavior that pressing again restarts the countdown.

Inherited behavior. The same task remains after direct `set_power(False)`/`set_power(True)` calls; whether later manual commands supersede timed-run ownership needs an explicit policy rather than accidental scheduling. Duration is read after ON finishes, so a configuration edit during connection also changes the in-progress request's cutoff.

Minimal direction: serialize run creation, capture requested duration at submission, associate each run and deadline with an identity, and replace ownership atomically. Preserve or explicitly reconcile an existing cutoff when replacement startup fails. A stale timer must check its ownership before sending OFF. Manual supersession rules are reviewer recommendations for decision, not already approved user policy.

Fake tests: (1) establish one successful run, fail the second ON and assert the former cutoff is lost; (2) hold two ON writes until both callers have entered, release both and count pending real `_momentary_off_later` coroutines versus stored handles; (3) manually toggle power within a run and advance a fake monotonic clock to characterize the old timer's effect. None requires actual elapsed waiting or a device.

### R4 — P1: shutdown neither joins in-flight work nor prevents a connection from appearing after unload

`device.py:327–333,416–428,481–485,1274–1287`; `__init__.py:200–210`.

Shutdown cancels only the two stored timer handles, does not await them, and does not track current refresh/control/connection operations or set a closing flag. If shutdown runs while `establish_connection` is awaiting, it sees no client; when connection later returns, the old manager can continue the handshake and schedule a disconnect after unload. Canceling a connection after a client is acquired has no cancellation-safe cleanup: `CancelledError` is not caught by these ordinary exception handlers. Shutdown also bypasses `_teardown_ble_client`, so it omits the `stop_notify` sequence that this code explicitly documents as necessary for some firmware (`device.py:499–525`). These lifecycle issues are inherited.

Minimal direction: close admission, stop interval producers, cancel/join owned operations, and serialize cancellation-safe transport release. Use one idempotent teardown path. Avoid canceling an idle-disconnect task in the middle of teardown without completing or reconciling that teardown.

Fake tests: hold connection establishment, call real shutdown, release establishment, and detect any surviving client/write/task; cancel after a fake client is acquired and verify whether it is released; start a subscribed fake client then inspect whether shutdown calls `stop_notify` before disconnect. Use event barriers and bounded waits, not timing guesses.

### R5 — P2: command success can contradict fresh replies; delayed replies can overwrite later commands

`device.py:603–617,619–637,790–806,847–853`.

`_ble_execute` returns the GATT send result after a fixed one-second sleep, regardless of receiving any valid reply. If a real contradictory reply arrives during the sleep, the caller then overwrites that report with optimistic state at 794–795 or 851. Conversely, a delayed pre-command reply arriving after command completion overwrites the optimistic state at 632/635. There is no operation identity, session-bound notification callback, response correlation or per-field freshness fence. Inherited behavior; beta refresh increases exposure to delayed read replies.

Minimal direction: separate transport acceptance, command intent and valid device reports. A result claiming verification needs supported, valid, field-specific evidence with a documented freshness model. Do not let optimism replace a contradictory report. Do not silently turn a GATT success into an application-success result.

Fake tests: emit an OFF notification during a successful ON write and observe final cached power; emit an older ON reply after a later OFF operation and observe overwrite; send no notifications and observe that the command still reports success. Use the real parser and synthetic protocol frames.

### R6 — P2: manual clock sync can succeed without any clock write

`device.py:287–289,455–464,1260–1264`; `button.py:84–88`.

`sync_time` clears `_ble_has_synced_time`, then calls `_ble_connect`. An already-connected client takes the early return before clock-sync construction and sending. The button logs “Time synced” despite no clock write. The flag can remain false while an actively reused connection keeps taking that path. Inherited defect. There is also no eight-hour scheduler in this beta; ordinary Aroma-Link initial-connect sync is guarded by a lifetime flag, while AK/Aromely have their own session prerequisites. Existing behavior does not implement the proposed eight-hour requirement.

Minimal direction: implement explicit clock-write work through the operation owner; connection reuse must not skip the write. Keep connection/authentication prerequisites distinct from scheduled synchronization. Report sent-unverified where a protocol has no readback instead of claiming verified success.

Fake test: supply an already-connected fake client with a write recorder, call real `sync_time`, and assert its current result is true while the recorder stays empty. A future safety regression should require an actual supported clock frame.

### R7 — P2: oil age is freshened by unrelated notifications

`device.py:630–717,725–729`; `sensor.py:166–175`.

The beta adds a single `_ble_last_update` timestamp and exposes it on Oil remaining. Any recognized power/fan/phase/schedule/etc. report refreshes that timestamp, even without oil data; the assignments set `changed=True` even for identical values. A responsive diffuser whose oil query is unanswered therefore makes its old oil number appear recently read. This is a **beta-added attribute that does not meet the proposed oil-specific contract**. Its name, `last_device_update`, correctly describes a general device timestamp; do not classify the general timestamp itself as internally incorrect. Consumers must not treat it as oil-specific evidence.

Minimal direction: retain an oil-specific valid-response timestamp, advancing on a valid oil reply even when the value is unchanged. General device response time can remain separate. Restored values must retain their actual recorded timestamp and provenance.

Fake test: inject valid oil, save its exposed timestamp, inject power only later, and observe that the Oil remaining attribute changes although the oil field never received another response. Then repeat oil with the same value to require freshness to advance legitimately.

## Related validation defects and limits

Protocol validation cannot be supplied by the caller. Examples visible in the real beta: Tuya indexes declared-length payloads without ensuring those bytes exist (`protocol_ble.py:315–346`), Scentiment copies arbitrary parsed JSON directly into accepted state keys (`833–852`), Aroma-Link accepts raw impossible clock values (`562–566,595–598`) and clamps invalid oil bytes to apparently valid 100% (`624–628`), while device notification handling does no type/range validation (`device.py:626–717`). An impossible clock reaches `datetime.time` in `time.py:56,99` and raises. AK readback also masks arbitrary hours/minutes to bytes rather than rejecting them (`protocol_ble.py:1599–1617`). These are source-backed examples for the broader parser reviewer; they should be consolidated with that review, not counted twice.

Recommended fake parser probes: a Tuya power report declaring one byte but carrying none; Scentiment JSON with a string power, negative battery and invalid hour; Aroma-Link oil byte 255; AK schedule hour 255. Check last-valid-state retention, explicit invalid indication and no successful verification credit. Characterization tests that assert exceptions or invalid acceptance merely demonstrate current defects.

## Reevaluation of provisional decisions

- **Freshness generations:** incrementing a generation when a packet arrives proves receipt order, not when the device sampled state or which request caused it. A delayed old reply can receive a new generation and falsely satisfy verification. Binding callbacks to a transport session filters obsolete-session callbacks but does not solve delayed replies within the same session. Require protocol-specific correlation where available; otherwise document the limitations of serialized request/readback and classify irreducibly ambiguous proof honestly. Do not claim a generic counter eliminates the race.
- **AK/V3 post-stop reconnect:** a fresh session after requested stop writes can improve the proof boundary if supported by actual protocol behavior. Arm the new-session observation before connection/handshake readback begins; taking the response baseline only after reconnect returns can discard valid handshake replies and cause a false timeout, particularly if a redundant query receives no reply. Match valid stopped-state fields and operation identity. The software review establishes neither device stop semantics nor physical acceptance. Do not apply the reconnect rule to every protocol.
- **Visible operation monitor:** include accepted queued and running work, publish a correlated result before the operation exits, and keep active true while another operation is already queued. A caller checking idle still has a check/use race; admission and execution need internal serialization. Coalesce redundant refreshes so the beta's new polling producer cannot grow the queue. Priority/preemption, fairness bounds, stop supersession, cancellation results and stale timer policy require decisions; a simple mutex alone does not specify them.
- **Eight-hour clock writes:** “next usable connection once due” can defer indefinitely and is not equivalent to explicit scheduled attempts every eight hours. The scheduler should initiate due work; unreachable/offline conditions must appear in attempt/result state. Exact physical execution while HA/BLE is unavailable cannot be promised. Retry cadence and user alert routing remain undecided. A clock-only fault should not override otherwise demonstrated reachability.
- **Timed runs and restart:** Aroma-Link's existing momentary command is controller-timed (`device.py:813–840`), so a proposal limited to device-timed runs omits current functionality. Unload cancels its cutoff with no OFF and startup restores no deadline (`1270–1287`, constructor `138–141`). Recommend persisted deadline, run identity and recovery/reconciliation; this is a strong maintainer recommendation, not an approved new implementation requirement. A local deadline expiry, lost timer, restart or successful OFF write does not establish physical stop. Preserve device-reported activity separately from an estimated deadline and known controller origin; do not invent vendor-app/physical/external origin after restart.

## Independent Claude validation checks

1. Import the exact beta's real device and protocol modules with HA/BLE stubbed only at their external boundary. With deterministic event barriers, independently test connect-ready ordering, concurrent command chunks and refresh/command overlap. Identify any case where an apparently held connection lock permits a write.
2. Test AK first-use fan and reconnect power construction with synthetic V2/V3 login and control responses. Determine whether bytes are built before the response supplying their required protocol/state, and whether unrelated control bits can be carried from stale cache.
3. Independently characterize successful run followed by failed retrigger, simultaneous starts, manual supersession and shutdown during a run. Record timer count, ownership and attempted OFF operations; do not equate a software timer or write with physical cutoff.
4. Cancel at connection establishment, notification subscription, protocol handshake, idle teardown and shutdown. Check task joining, stop-notify ordering and writes or live clients after unload; do not hide orphan tasks by relying on the test runner's final cancellation.
5. Inject an old pre-command reply after a newer command, a contradictory fresh reply during the fixed response wait, and no reply at all. Also test proposed generation logic with a delayed old reply assigned a new receive generation and reconnect handshake replies arriving before a post-reconnect baseline. State exactly which observations establish causality and which cannot.
6. On a connected fake client, verify whether Sync Time actually writes; examine eight-hour scheduling independently of connect prerequisites. For telemetry, inject oil then power-only and invalid values; verify oil-specific freshness, valid-state retention and invalid-response result behavior. Distinguish existing defects, beta regressions and unimplemented approved proposals.

All six checks should use synthetic identifiers and offline boundaries, publish reproducible commands and exact source lines, and explicitly distinguish defect-characterization tests from future safety regression tests.
