# Permissioned offline first-decision research boundary

Version: `first-decision-learning-1`. Implementation: `learning_contract.py` and
`learning_dataset.py`. Run `tools/create_learning_example.py` for a complete
synthetic example. This is **not** a production endpoint or a trusted merchant
connector. No provider SDK, network access, automatic training or serving.

## Files and command

```bash
python tools/create_learning_example.py outputs/learning-example
python -m recoveryai_sim prepare-learning --input outputs/learning-example/episodes.jsonl --permission outputs/learning-example/permission.json --split outputs/learning-example/split.json --output outputs/learning-foundation
```

Input is JSONL, one immutable **first decision per recovery**, with exact fields.
Follow-up decision rows for the same recovery are rejected: a different trajectory
contract is required to avoid duplicate rewards and false per-action attribution.
Identical repeated rows are deduplicated; conflicting decision snapshots block the
entire dataset. Refreshing an outcome requires a new versioned export/artifact,
not appending a different label to an existing decision inside the same batch.

Permission manifest: explicit research permission, purpose, environment, origin,
tenant scope, source version, export time, permission expiry and retention deadline.
The synthetic example's long expiry is **not a real retention recommendation**.
Real retention and permission require separate review. The loader rechecks expiry;
automatic deletion, legal approval and access-control enforcement are not provided.

Split manifest: `train_before`, `test_from`, and preregistered `heldout_tenants`.
Training uses only nonheldout merchants with both decision and label availability
strictly before the cutoff. Test uses only heldout merchants at/after test_from.
Others are excluded with reasons. Unknown outcomes are never negative labels.

## Observable schema

Top-level: contract, pseudonymous tenant/customer/recovery/decision references,
environment, provider, first failure/decision times, amount_minor, currency,
decline_reason, attempt_count, policy/model versions, selected/eligible actions,
logging propensity, feature snapshot, execution evidence and outcome.

References use typed prefixes and 64 lowercase hex characters (`t_`, `c_`, `r_`,
`d_`, `x_`, `m_`, `p_`). Generate tenant-scoped opaque identifiers at the exporter;
**do not hash raw email/phone with an unkeyed predictable hash**. The example hashes
only fixed synthetic labels. Pseudonymization is not anonymization: linkage and
usage/financial features remain sensitive and must have restricted access.

Every feature key is present, either null or `{value, source, occurred_at,
available_at}`. Source is fixed by feature; event <= availability <= decision.
V1 rejects features older than 30 days (a conservative research freshness rule,
not a universal business standard). No model fills in absent inputs here.

Features: subscription age, previous failure count, active days7/30, usage bucket,
team size, feature count30, estimated LTV minor units, gross-margin bucket,
cost-to-serve30 minor units, support-ticket count30, support risk,
delivered/clicked counts30 and consent. All monetary feature values must already
be in the episode currency. No hidden FX conversion. LTV is an exporter-provided
point-in-time estimate, not future realized revenue disguised as an input.

Execution: status, execution time/ref, delivery status and optional message ref.
Known delivered/bounced needs a message ref and executed state. Observe/review
must have no dispatch. Executed contact requires explicit known consent. A Turkish
provider cannot declare native retry support through this contract. This does not
replace current-state consent, provider capability or dispatch-time authorization.

Outcome: provider-confirmed paid/unpaid or unresolved; fixed failure+30-day window,
evidence availability, provider event ref, payment time, gross, refund and follow-up
costs/service fees. Confirmed outcomes require mature availability and a reference;
unresolved payment values must be null. Partial confirmed recovery is allowed,
refund <= gross <= invoice amount. Provider event reuse across recoveries/tenants
is rejected inside a provider/environment namespace.

## Outputs and safety

- Any invalid row blocks **all** research files. Diagnostics contain line number
  and static error code only; raw rejected rows, secret values and PII are not copied.
- Exact allowlists reject unknown fields, message content and raw provider bodies.
  They cannot prove that an upstream exporter did not mislabel or encode sensitive
  content in an otherwise valid field; exporter review is still necessary.
- Features, labels and sensitive lineage are separate files, with artifact hashes.
  `load_learning_partition` verifies hashes/joins/expiry and enforces train/test
  merchant/time boundaries. It returns no raw tenant/customer identifiers as model
  features. Read through that loader, not arbitrary `research/*.jsonl` globs.
- Hashes detect accidental mutation, **not authenticity against an operator who
  can rewrite both files and manifest**. No cryptographic attestation is claimed.
- `evaluation_partition_ready` means only nonempty disjoint partitions, not
  adequate sample size, overlap, calibration, experimental validity or model readiness.
- Live, sandbox and synthetic are isolated by manifest; nothing is billable.
  Existing simulator training APIs intentionally do not load these research files.
- Local line/manifest size is bounded64KiB, batch100K lines/64MiB. Existing output folders
  are never overwritten. Raw inputs and artifacts belong under ignored paths with
  restricted OS permissions, not in Git.

## Missing real-world dependencies

The Alroca exporter must validate access, signatures, event/reversal reconciliation,
source provenance and complete observation windows before assigning confirmed
fields. The current code trusts operator/exporter attestations, not network claims.
Sources for product usage, margin/LTV and support are not yet specified. These
remain unknown; no fabricated merchant data or calibration is performed.
