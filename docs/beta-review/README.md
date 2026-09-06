# Scent Assistant beta: review and validation handoff

Status: **imported for review; HOLD for the proposed Ready to Serve deployment.**

Upstream: `mr-sparks/scent-assistant`, tag `v1.2.3-beta.1`, commit
`ac928a73c3bed22cd00d5e5d875c6ff72445ab06`. Stable comparison: `v1.2.2`,
`e377ed477eb5490d2e911cda471805cad33285ea`. Review date: 2026-09-05.

The exact beta is preserved on `codex/upstream-v1.2.3-beta.1` in
`gitorcus/scent-assistant`. `codex/beta-1.2.3-review` adds these reports,
offline evidence scripts and validation-workflow hardening. The integration
under `custom_components/scent_assistant` is byte-for-byte unchanged from the
beta. Neither branch changes the fork's main branch or an installed Home
Assistant instance. No device operation, credential change, upstream PR or
maintainer message is part of this review.

Three independent reviewers used **GPT-6 Astra with Ultra reasoning** for
architecture, concurrency/lifecycle, and security. The coordinating reviewer
reran the architecture/security probes, added four deterministic concurrency
checks and positive beta parser checks, and consolidated the results. This is
an AI-assisted source review, not third-party certification or physical testing.

## Read these together

- [Architecture and all 12 provisional decisions](architecture.md)
- [Concurrency and lifecycle review](race.md)
- [Security and untrusted-input review](security.md)
- [Copyable Claude validation prompts](claude-validation.md)
- [Item #10: active certificate-trust and automatic-renewal requirement](certificate-trust.md)

The detailed reports overlap; do not sum their finding counts as unique bugs.
Their line references point to the pinned, unchanged integration source.

## Main conclusions

| Finding | Classification | Evidence and consequence |
|---|---|---|
| Schedule targeting and preservation | Inherited defect | Ordinary entity targets reach no device; omitted target broadcasts. Duration-only AK edits and cloud disable requests can enable a program. Reproduced offline. |
| Operation and timer ownership | Inherited defects, more concurrency from beta refresh | Connected fast path bypasses the connection lock; failed retrigger discards an existing cutoff; two simultaneous starts leave two timers with one stored handle. Reproduced offline. Wider handshake/chunk/unload interleavings are source-reviewed, not all reproduced. |
| Explicit clock sync | Inherited defect plus proposed feature gap | Connected Sync Time returns success with no write. Reproduced. Eight-hour maintenance/result reporting is not implemented in this beta. |
| Cloud certificate verification (#10 / SEC-1) | Inherited defect; active approved remediation requirement, not implemented | HTTPS is encrypted but certificate verification is unconditionally bypassed. Add verified trust-once/automatic-renewal handling, separate reload/re-pin actions, and a persistent explicit option to continue without certificate verification. No silent downgrade; see certificate trust requirement. |
| Sensitive diagnostics/logging | Inherited defects | A synthetic GW password survives as encoded raw command data; a synthetic cloud token appears in DEBUG logs. No real credentials accessed. |
| Invalid response/state handling | Inherited semantic-validation gaps plus new beta status path | A checksum-valid beta response with invalid power/status bytes becomes off. GW assembly is unbounded; several JSON fields are not semantically validated. Synthetic probes only. |
| Oil freshness | Proposed contract gap, not a broken general timestamp | The beta's `last_device_update` is device-wide; it cannot prove when oil was read. Keep it if useful and add oil-specific evidence rather than silently changing its meaning. |
| RTS recipe and monitor | Proposed features absent | Caller-controlled persistent recipe, correlated verified result, and operation activity are not implemented. Their absence is not an upstream regression. |

Preserve the beta's useful changes: protocol-opt-in periodic refresh,
bounded Aroma-Link reassembly/checksum handling, the corrected work-info query,
separation of configured durations from remaining time, and retention of valid
last-known oil without an arbitrary age-to-unavailable rule. The 600-second
public limit is accepted. Do not restore the old dedicated refresh state machine
or fold household outlet/HVAC/alert logic into a public integration.

## Design decisions requiring reevaluation

The approved direction remains provisional; these reports do not implement it.
Receive counters do not prove which request caused a reply. Arm AK fresh-session
verification before its handshake responses arrive. An idle monitor is not a
lock; internal operation ownership and per-call results are necessary. Eight-hour
maintenance must initiate due work, not wait indefinitely for a future user
connection. Timed-run provenance must cover HA-timed runs too. Queue priority,
stop supersession, cancellation and restart recovery need explicit policy.
Durable automatic shutoff remains a strong maintainer recommendation, not a
new implementation approval. Device-password changes remain deferred.

Certificate item **#10 is no longer deferred**. Its active approved requirement
is to approve additional CA trust once when needed, persist it for the intended
endpoint, accept normal valid renewals automatically, support authenticated CA
transitions, and request approval only for genuinely new untrusted authority.
Provide separate Reload trust and Review and re-pin actions. This requirement
also preserves an explicit, persistent "Continue without certificate verification"
choice (`ssl=False`, still HTTPS), distinct from Cancel. Users do not need to
approve a CA or justify that choice. Verified-mode failures must not silently
switch modes, and deliberately unverified connections must not be labeled
verified. This does not mark the defect fixed or authorize a production change.

## Executed validation

- Exact imported beta: fork HACS and Hassfest succeeded at the pinned hash:
  [HACS](https://github.com/gitorcus/scent-assistant/actions/runs/34006361713),
  [Hassfest](https://github.com/gitorcus/scent-assistant/actions/runs/34006361670).
- Python 3.14.6 compilation: passed for all integration modules.
- Four offline scripts: seven architecture categories, seven security categories,
  four concurrency categories, and five parser/refresh/freshness categories.
  **Characterization assertions deliberately reproduce defects. Their passing
  does not mean those defects are fixed.** Positive parser assertions are marked
  separately. These are bounded examples, not coverage claims.
- Ruff 0.16.6 (`E9,F`): 20 unused-import findings; no other selected-rule errors.
  No automatic formatting or runtime source cleanup performed.
- Bandit 1.9.4: 11 raw findings (nine low, two high). High results concern
  vendor-required MD5 authentication, not proof of an integration-selected new
  algorithm. Key-name/endpoint-string warnings are not actual embedded secrets.
  Manual review found TLS/logging/diagnostic issues the scanner did not.
- Zizmor 1.30.0: baseline workflow findings for mutable actions, inherited
  permissions and checkout credential persistence. Review branch pins actions,
  explicitly uses read-only contents access and disables checkout persistence.
- pip-audit 2.10.1: no known advisories returned for the isolated macOS manifest
  dependency resolution: bleak 3.0.2, bleak-retry-connector 4.7.0 and four
  pyobjc packages at 12.2.2. This does **not** audit HA's full dependency graph,
  the Linux Bluetooth stack, a lockfile or every version allowed by the manifest.

The review workflow reruns offline evidence on Python 3.12 and 3.14. Refer to
Actions for its actual outcome at the review commit; this document does not
declare a future CI run successful.

## Reproduce locally

Use a disposable checkout and virtual environment, not the production HA host.

```sh
git rev-parse HEAD
git diff --exit-code ac928a73c3bed22cd00d5e5d875c6ff72445ab06 -- custom_components/scent_assistant
python3 -m venv .venv-review
.venv-review/bin/python -m pip install -r tools/beta-review/requirements.txt
.venv-review/bin/python -B tools/beta-review/architecture.py
.venv-review/bin/python -B tools/beta-review/security.py
.venv-review/bin/python -B tools/beta-review/concurrency.py
.venv-review/bin/python -B tools/beta-review/parser.py
git diff --check
```

The scripts load real integration modules while replacing external boundaries.
They do not discover Bluetooth devices or call a real cloud endpoint. The
requirements file is for review tools only, not an alternative integration
manifest. Record the exact resolved environment when reproducing it. Delete or
exclude the disposable environment before publishing source work.

## Remaining release gates

1. Independently validate these findings; agree scoped fixes and the corrected
   public RTS contract before implementation. Keep unrelated fixes separable
   for upstream review. Reverse defect-characterization assertions into intended
   regression assertions only when the corresponding fix is under test.
2. Test real HA minimum/current supported versions, setup/unload/reload, reauth,
   entry/recipe migration, entity identity, abort cleanup and remote-proxy-only
   onboarding. Stub imports and Hassfest do not establish runtime compatibility.
3. Validate protocol capability/alias matrices, all weekday mappings, complete
   schedule preservation, invalid frames and cancellation/failure interleavings.
4. Complete active item #10 using the [approved certificate-trust acceptance
   checks](certificate-trust.md#acceptance-checks-for-item-10): diagnose actual
   HA compatibility, initial approval, persistent scoped trust, automatic normal
   renewal, authenticated transitions, reload and explicit re-pin recovery.
   Include explicit verification-off selection, persistence and switching back
   to verification. Confirm users need neither manual CA files nor renewal
   reapproval and are not forced to approve a CA to use the opt-out mode.
5. Inventory installed custom changes and downstream interfaces, including
   saved durations and clock/run ownership. This review did not inspect them.
6. Prepare exact candidate/source hashes, data migration and rollback, obtain
   change-specific production approval, and then separately verify fresh device
   responses and physical behavior. No offline result substitutes for these gates.
