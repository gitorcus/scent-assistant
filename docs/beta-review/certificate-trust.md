# Certificate trust: secure compatibility without user certificate expertise

Status: **ACTIVE — approved requirement for planned remediation of item #10
(SEC-1); no longer deferred. Not yet implemented.**

Here, item #10 refers to the numbered unresolved-defects summary, not item 10
(oil freshness) in the separate RTS decision matrix.

This records the approved design direction. This documentation update does not
change integration code, production trust stores, or TLS behavior, and does not
authorize building/deploying a separate trust-management integration.

## Approved requirement: trust once, renew automatically

Ordinary users must not need to obtain CA files or repeatedly approve routine
certificate renewals. They must also be able to explicitly choose HTTPS without
certificate verification for their own environment. Preserve these requirements
together:

1. **Normal public trust first.** A valid vendor connection already trusted by
   HA requires no custom pin or extra approval.
2. **Explicit choice when additional CA trust is needed.** During cloud setup,
   identify the intended endpoint and proposed authority, present its
   identity/fingerprint and trust scope, and offer distinct actions: approve the
   CA and continue with verification; continue without certificate verification;
   or cancel setup. Store no new CA without approval. In CA-verified mode,
   establish the CA's identity through a documented trustworthy process before
   credential-bearing requests; a confirmation dialog alone does not
   authenticate whatever an unverified endpoint supplies.
3. **Persist narrowly scoped CA trust.** Save the approved authority for the
   intended Scent Assistant cloud endpoint, surviving integration reloads and
   HA restarts. Do not add it to HA's global trust store. BLE-only setup is not
   subject to this cloud trust flow.
4. **Accept ordinary renewals automatically.** Renewed server certificates
   that validate for the intended hostname through the approved CA continue
   working without reapproval or manual re-pinning. Do not pin a short-lived
   server certificate in a way that breaks this requirement. The vendor issues
   and renews its certificates; Scent Assistant validates the renewed chain.
5. **Support authenticated CA transitions.** A cryptographically validated
   rollover or cross-signed path rooted in existing approved trust may proceed
   automatically under a documented, tested policy preserving that trust's
   constraints. Merely receiving a new CA from an authenticated server is not
   permission to promote it to an independent trust anchor. The policy must
   explicitly define any persistent successor-anchor promotion. A genuinely
   new untrusted authority requires explicit
   approval; silently accepting any replacement is not renewal handling.
6. **Provide Reload trust.** Rebuild the scoped connection context and reconnect
   using the saved approval. Reload must not replace the approved authority.
7. **Provide Review and re-pin.** Show the saved and proposed authority and what
   changed; require approval before atomically replacing trust and reconnecting.
   Cancellation or a failed replacement test must not erase the saved approval
   or silently fall back to disabled verification.
8. **Keep verified-mode validation and recovery honest.** Continue hostname/chain validation;
   reject invalid connections rather than treating initial approval as a
   permanent exception for expired or wrong-host certificates. An unexpected
   trust change raises a clear repair action for the affected cloud connection,
   not routine renewal prompts or a failure of unrelated BLE entries. Offer
   re-pin or an explicit switch to verification-off mode; do not switch modes
   automatically when verification fails.
9. **Allow a persistent, user-selected verification-off mode.** Expose
   "Continue without certificate verification" during setup and an equivalent
   setting in later reconfiguration. The user need not approve a CA or justify
   the choice. Explain once that HTTPS remains encrypted but does not verify
   the server's identity, which permits interception by an impersonator. After
   that explicit choice, credential-bearing cloud requests may use `ssl=False`.
   Persist the selected mode for the intended connection across reload/restart;
   do not block it solely on CA validation, repeatedly request trust approval,
   or display it as verified. Keep a visible verification-off indication in
   configuration/diagnostics, not recurring blocking prompts. Other network,
   authentication and protocol failures still apply. Do not change global HA
   behavior or unrelated connections. Switching back to a verified mode must
   validate the selected trust before presenting it as working/verified.

Reload preserves the selected verification mode and any saved trust; it never
enrolls a new authority or silently changes verification policy. Re-pin is an
explicit trust-management action, not a prerequisite for verification-off mode.
Cancel means no enrollment and no new credential-bearing setup request. It is
not the same action as deliberately continuing without verification.

The approval/trust bootstrap mechanism, exact CA-pin representation and
authenticated rotation mechanism remain implementation design details to
validate. They must satisfy the user-facing continuity and approval rules above.

## Acceptance checks for item #10

- An already trusted public chain connects without a custom trust prompt.
- Initial CA-verified setup requires trust approval before credentials are sent.
  Cancel leaves no new stored approval and no credential-bearing setup request.
- Explicit Continue without certificate verification stores that mode and
  permits HTTPS credential-bearing requests with `ssl=False`, without approving
  or pinning a CA. No justification or recurring approval prompt is required.
- Verification-off persists across reload/restart, remains visibly unverified,
  and affects only the selected connection. Reconfiguration can switch modes;
  selecting a verified mode tests validation before claiming verified success.
- Restart and Reload trust retain the same approved authority.
- A renewed valid server certificate under that authority succeeds automatically,
  with no user prompt. A proven CA transition also follows its tested automatic
  path; an unproven replacement does not.
- Review and re-pin requires approval, updates only the intended connection,
  and preserves the old approval on cancellation or failed replacement.
- In verified modes, wrong-host, expired and untrusted chains fail clearly with
  no automatic downgrade. In explicitly selected verification-off mode, these
  certificate-validation failures do not block operation; encryption remains
  enabled and no verified-identity claim is made. Test the actual selected mode
  at the HTTP boundary. Unrelated entries and BLE operation remain unaffected.
- Trust setup, persistence, renewal, rotation and recovery tests run in an
  isolated supported HA runtime before production rollout. No current test
  result establishes this proposed behavior, because it is not implemented.

## What is known and unknown

The beta cloud client uses HTTPS with `ssl=False`, disabling server-certificate
verification, not HTTPS encryption. That is confirmed. Why this was originally
necessary, whether a
vendor root/intermediate is missing in HA, and whether verification currently
works from the target HA runtime are **not established**. A valid connection
from a developer's laptop would not answer the HA-runtime question.

The goal is usable verified cloud access without asking typical users to obtain
or install CA files, while preserving their explicit choice to run without
verification. This is not simply removal of a flag, silent enrollment of a CA,
or automatic downgrade after failed verification. The current unconditional
bypass is not evidence of an explicit user choice; this planned control and its
disclosure do not exist in the reviewed beta.

## Existing Home Assistant facilities

The official [Let's Encrypt app](https://github.com/home-assistant/addons/blob/master/letsencrypt/DOCS.md)
obtains and renews certificates for domains the user controls. Its HTTP/DNS
challenges and resulting certificate files concern serving HTTPS. It does not
issue a replacement certificate for a vendor domain the user does not control
or generally repair outbound integration trust.

[Certificate Expiry](https://www.home-assistant.io/integrations/cert_expiry/)
monitors a host certificate's expiry; it is not a trust-installation service.

The current [HA SSL helper](https://github.com/home-assistant/core/blob/dev/homeassistant/util/ssl.py)
constructs verifying contexts from `REQUESTS_CA_BUNDLE` when set, otherwise
`certifi`. It also caches shared contexts and exposes creation of independent
contexts. These are current development-source observations, not confirmation
of the target installation's exact code/version. This targeted review did not
establish that a supported general-purpose one-click CA trust integration exists;
do not turn that limited search into a claim that no such project exists.

## Recommended investigation and design order

1. Inspect the target HA runtime's version, clock, trust-bundle path/version and
   actual client context. Check the vendor chain's hostname, expiry, issuer and
   intermediates without sending user credentials. Distinguish missing root,
   missing intermediate, wrong hostname, expired certificate, old trust data and
   intentional local TLS inspection. Record only non-secret metadata.
2. Prefer a vendor-served complete chain to an already trusted public CA and
   HA's supported maintained trust bundle. Those require no user CA handling.
3. If a legitimate vendor-specific CA really is required, evaluate a supported
   per-integration trust context with authenticated, maintainer-vetted CA
   material and a documented rotation/revocation/update path. Do not mutate
   HA's shared context or global trust bundle to fix one vendor.
4. If several integrations have the same unmet need, evaluate an upstream HA
   trust-management facility before a new HACS integration. A separate UI alone
   cannot force every integration/library to use its trust decisions. Define
   API adoption, ownership, scope, authenticated trust bootstrap, updates,
   removal and rollback before building it.
5. Require working normal connections and rejection of untrusted, expired and
   wrong-host certificates in verified modes. Separately test explicit
   verification-off selection, its persistence and truthful diagnostics.
   Include routine certificate renewal and legitimate
   CA rotation without manual intervention, and a comprehensible repair message
   when automatic authenticated recovery is not possible.

For private/local trust, any one-click approval must clearly identify what trust
is being granted and its scope. Do not learn a new CA from the same unverified
connection and silently trust it: that can authorize an impostor. Preserve the
distinction between downloading an intermediate to complete an already rooted
chain and installing a new trust anchor. No globally trusted root installation,
silent fallback to disabled verification, or real account login is authorized
by these validation prompts.
