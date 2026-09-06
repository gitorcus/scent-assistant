# Claude validation prompts for the fork

Use the common instructions once, then run prompts 1–8 independently. Prompts
2–7 may run in parallel in separate disposable worktrees. This pack requests
review and offline validation, not production deployment or automatic fixes.

## Common instructions — paste first

```text
Independently validate gitorcus/scent-assistant, branch codex/beta-1.2.3-review.
Record the fetched full commit hash and use it for every citation/result.
Baseline beta is ac928a73c3bed22cd00d5e5d875c6ff72445ab06, preserved on
codex/upstream-v1.2.3-beta.1. Stable comparator is v1.2.2.

Do not assume the existing Astra review or its tests are correct. Read code
first, develop your own explanation/reproduction, then compare the reports in
docs/beta-review. Report agreements, disagreements and missing evidence.

Use a disposable checkout/environment. Do not edit or deploy Home Assistant,
operate diffusers/outlets/HVAC, change credentials or trust stores, contact a
maintainer, open a PR, or push changes. Do not access production secrets/logs.
Use synthetic fixtures and replace HA/BLE/cloud boundaries; test the actual
integration modules, not a copied implementation. No live device or vendor
login tests. If actual-HA evidence is needed, specify a separate authorized
test plan and mark it NOT TESTED unless an isolated HA test environment is used.

Return findings with severity, exact source lines, trigger/preconditions,
consequence, minimal remediation direction, runnable reproduction, actual
result, and confidence/limitations. Label each as inherited defect, beta
regression, proposed-feature gap, hardening suggestion, or unresolved question.
Do not count duplicate findings across reports. Distinguish PASS/FAIL/NOT TESTED.
Passing characterization tests means defects reproduced, not integration safe.
Never display real secrets. Use public official sources for HA/API assertions.
Report environment/dependency versions and leave the checkout unchanged.
```

## 1. Provenance, packaging and reproducibility

```text
Confirm this fork's upstream parent, exact beta/tag hashes and branch ancestry.
Verify custom_components/scent_assistant matches the pinned beta byte-for-byte.
Separate inherited source from review docs/probes/workflow-only changes. Review
the commit diff for accidental private data, binaries, logs and unrelated work.

Run all four tools/beta-review/*.py evidence scripts individually using the
requirements file. Inspect their stubs/assertions and identify blind spots;
do not summarize them as a full test suite. Count reproduced scenarios only
after verifying each executed assertion. Run compile checks, diff checks,
critical lint, JSON/YAML/manifest/translation validation, and action linting.
Review the exact commit's HACS/Hassfest/evidence workflow results and annotations.
Check dependency ranges, actual resolved versions, declared HA minimum version,
licenses, action pinning, token permissions and install/update behavior.

Deliver an evidence table, reproducible commands, immutable source references
and unresolved compatibility gates. No blanket production approval from CI.
```

## 2. RTS architecture and all approved decisions

```text
Evaluate the 12-item decision matrix in docs/beta-review/architecture.md against
the real beta. Do not implement missing proposals. RTS must serve general users:
caller-chosen Power/Fan/Program No change/On/Off, supported CONFIG controls on
the device page, persistent recipe, no actuation on edit, explicit execution,
per-request results and recipe-revision invalidation. No outlet, HVAC, dashboard,
schedule or alert dependency. 600 seconds is acceptable.

Challenge capability aliases (especially AK V2 Power/Program), unknown initial
state, partial full-schedule writes, unsupported readback and an all-No-change
recipe. Prove that omitted fields and unrelated slots/day masks stay unchanged.
Review eight-hour explicit clock attempts, failure reporting, optional readback,
visible queued/running operation activity, status race protection, timed-run
provenance, invalid-value boundaries and oil-specific freshness. Distinguish
user requirements from assistant-added mechanisms and unresolved policies.

Challenge arrival-generation proof: a delayed old response can receive a new
generation. Challenge a post-reconnect baseline that discards handshake replies.
Challenge an idle monitor as a lock. Explain what can actually be verified for
each protocol. Automatic durable shutoff is a strong maintainer recommendation,
not implementation approval; credential restoration is deferred.
```

## 3. Concurrency, command ordering and timer ownership

```text
Use asyncio event barriers and a fake clock, not long sleeps. Test the real
device manager with fake transport. Hold notification subscription/handshake
and issue another command. Hold two command writes, including a composite AK
command or GW chunks. Interleave periodic refresh, user writes and stop work.
Determine precisely which paths the connection lock does and does not protect.

Test command construction before AK V2/V3 identification and changed control
bits on reconnect. Test a successful timed run followed by failed retrigger,
two simultaneous starts, duration edit during connection, direct manual OFF/ON,
old timer firing after a newer run, and unload during each await. Count owned
and orphaned tasks before test cleanup cancels them. Record commanded OFF
separately from verified stopped state.

Inject contradictory fresh replies during a command wait, delayed pre-command
replies after newer commands, old-session callbacks and zero responses. Verify
whether optimistic state can override device evidence. Propose bounded queue,
coalescing, stop priority/supersession and cancellation alternatives with clear
tradeoffs; do not label those policy choices already approved.
```

## 4. Clock, telemetry and parser integrity

```text
Independently test connected Sync Time for an actual clock frame rather than a
True return. Examine clock encoding and HA timezone vs process timezone. For
the proposed eight-hour job use fake time: no user traffic, already connected,
offline, restart, DST, queued work and time jumps. Missing scheduler is a feature
gap; successful connect without a requested clock write is an existing defect.
Keep unsupported readback distinct from failure and from verified clock state.

Exercise valid Aroma-Link oil, work-info, configured duration, fragmented frames,
checksum failure, embedded markers, truncation, buffer limits and recovery. Test
all protocol families' invalid boolean/type/range/enum values before both
protocol and public-state mutation. Include legitimate zero oil and unchanged
oil responses. Inject oil once then power-only replies; identify whether the
timestamp is general device time or actual oil time. Do not rename a documented
generic timestamp into oil freshness by interpretation. State which parsers
were actually exercised and which require captured protocol evidence.
```

## 5. Security, privacy and certificate compatibility

```text
Review only this authorized source and isolated synthetic tests. Trace cloud
credentials/tokens, request destinations/redirects, TLS options, debug logs,
diagnostics and encoded raw frames. Use canary strings to test both structured
redaction and wire encodings. Distinguish public vendor-default PINs/protocol
obfuscation from new integration vulnerabilities. Review bounded parser resource
use and input-validation boundaries without contacting real devices or accounts.

IMPORTANT: ssl=False confirms a bypass, not why it exists. The correct CA may
be absent from HA. Do not recommend flipping the flag before checking the exact
HA runtime trust bundle/client context and the vendor's hostname, expiry, clock,
roots and intermediates. Distinguish missing CA, incomplete chain, private/local
trust and outdated bundle. A laptop/public-chain success does not establish HA
compatibility. If not tested in a suitable runtime, explicitly leave unresolved.

Item #10 / SEC-1 is ACTIVE approved remediation, no longer deferred, but is not
implemented. This prompt is still read-only validation, not approval to deploy.
Read certificate-trust.md and preserve the approved trust-once requirement:
normal public trust needs no extra prompt; additional CA trust needs explicit
initial approval before credential-bearing requests; persist trust only for the
intended endpoint. Valid server-certificate renewals under the approved CA must
work automatically without reapproval. Authenticated CA transitions may proceed
automatically; a genuinely new untrusted authority requires explicit approval.
Do not confuse a CA-trust decision with pinning each short-lived server certificate.

Validate separate Reload trust (reuse saved approval) and Review and re-pin
(show changes, explicitly approve replacement) paths. Test restart persistence,
ordinary renewal without prompts, authenticated/unproven CA transitions,
re-pin cancellation/failure retaining old approval, and unrelated BLE entries
remaining unaffected. No global trust changes or silent verification bypass.
If the feature is absent, report the missing approved requirement rather than
claiming its future acceptance tests passed.

Evaluate existing HA/Let's Encrypt/Certificate Expiry
facilities before proposing a new integration. Seek a secure normal-user path
without manual CA files: correct vendor chain, maintained HA trust, or a vetted
vendor-specific scoped context with rotation/revocation. Do not silently install
roots from an unverified endpoint or modify shared global trust. A generic
trust-manager concept needs separate design and authorization, not implementation
here. Define valid-chain success, invalid/wrong-host/expired rejection, renewal,
CA rotation and clear failure UX tests. Attribute actual evidence vs proposed tests.
```

## 6. Real Home Assistant lifecycle and compatibility

```text
In an isolated test environment only, test supported HA/Python versions, real
platform imports/setup, service registration/targeting and entry reload/unload.
Do not install in household HA. Identify versions from package metadata rather
than guessing. If runtime installation is unavailable, report NOT TESTED.

Fail each setup stage after resources exist; abort cloud selection; distinguish
bad auth from transient connectivity; test reauth, duplicate entries, entry
removal and cancellation during connection/refresh. Assert no retained callbacks,
timers, clients or writes from the old manager after unload. Verify HA shared HTTP
sessions are not closed. Check entity identity and migration/persistence needs
for future recipes, including unknown protocol capabilities on first connection.

Review proxy-only onboarding through HA Bluetooth APIs, no local adapter, first
device unavailable, multiple entries and asymmetric capabilities. Compare the
claimed minimum HA version with actual API imports and dependencies. Return a
versioned runtime matrix and a precise list of tests the stub harness cannot prove.
```

## 7. Schedule/API preservation and upgrade/rollback

```text
Test one explicit normal entity/device target, an unknown target, no target and
multiple devices. Ensure omitted target behavior is deliberate/documented rather
than accidental broadcast; reject silent no-ops. Test invalid clock strings,
boundary durations, 600 seconds, booleans and all day masks. For each protocol,
compare Monday/Sunday and weekdays/weekends/all-days read/write encodings.

Start with program disabled, then change only duration/intensity/time; compare
the complete outbound schedule and unrelated fields. Test cloud enabled=False
at the actual client boundary. Characterize partial failures/cache optimism.

Prepare (do not execute) a deployment compatibility and rollback plan: installed
vs candidate source, private consumer interfaces, saved 610-to-600 values, config
entry and future recipe storage, entity identifiers, updater source selection and
control ownership. Do not read private configuration or operate devices. Mark
those environment-specific checks unverified and requiring specific authority.
```

## 8. Independent release verdict and reconciliation

```text
Reconcile the independent outputs. Deduplicate by root cause, challenge false
positives and identify untested claims. Separate benefits to preserve, inherited
defects, beta regressions, proposed RTS gaps, conditional cloud risks and policy
questions. Rank fixes by consequence, not scanner severity alone.

Return: (1) HOLD/READY for the exact requested release scope, (2) blocking findings
with minimal reproducible evidence, (3) nonblocking improvements, (4) missing
test evidence and explicit production gates, (5) small upstream-friendly change
groups with acceptance criteria. Do not claim to approve production on the user's
behalf. Do not turn successful defect-characterization tests into safety passes.
Keep all integration changes, certificate trust changes, credentials, real-device
tests, upstream publication and deployment pending separate authorization.
```
