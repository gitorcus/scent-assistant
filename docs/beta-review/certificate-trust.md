# Certificate trust: secure compatibility without user certificate expertise

This is a research/design follow-up, **not approval to change trust stores or
build/deploy another integration**. No certificate or TLS setting was changed.

## What is known and unknown

The beta cloud client passes `ssl=False`, disabling server-certificate
verification. That is confirmed. Why this was originally necessary, whether a
vendor root/intermediate is missing in HA, and whether verification currently
works from the target HA runtime are **not established**. A valid connection
from a developer's laptop would not answer the HA-runtime question.

The goal is secure, working cloud access without asking typical users to obtain
or install CA files. It is not simply removal of a flag, nor automatic acceptance
of whichever certificate an unverified server supplies.

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
   wrong-host certificates. Include routine certificate renewal and legitimate
   CA rotation without manual intervention, and a comprehensible repair message
   when automatic authenticated recovery is not possible.

For private/local trust, any one-click approval must clearly identify what trust
is being granted and its scope. Do not learn a new CA from the same unverified
connection and silently trust it: that can authorize an impostor. Preserve the
distinction between downloading an intermediate to complete an already rooted
chain and installing a new trust anchor. No globally trusted root installation,
silent fallback to disabled verification, or real account login is authorized
by these validation prompts.
