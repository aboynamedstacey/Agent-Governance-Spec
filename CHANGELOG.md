# Changelog

## 0.5.0-draft (2026-05-01)

Closes the policy-evaluation ambiguities identified by clean-room implementation
exercise and two rounds of adversarial review. Adds `on_constraint_fail`
directive, defines `can_attenuate` precisely, narrows ATTENUATE to numeric
clamping, and aligns conformance vectors to the published JSON Schema.

### Added (spec)
- **D.2 Attenuation Eligibility (new section).** Defines `can_attenuate` with
  three guard conditions: (1) all failing constraints must be non-strict
  numeric bounds (LTE/GTE only — strict inequalities excluded because their
  attenuated values are not well-defined over the reals), (2) values must be
  finite numeric (excludes booleans, NaN, ±∞, non-numeric, strings parseable
  as numbers — closes the bool-as-int hazard), (3) variable-resolution
  failures disqualify the rule (a constraint that failed because `${...}`
  was unresolvable is not value-out-of-bound and clamping is meaningless).
  Specifies normative clamping rules: LTE clamps down, GTE clamps up;
  clamped values MUST preserve the JSON numeric type of the constraint
  bound (deterministic JCS canonicalization).
- **D.2 Constraint Failure Precedence (new section).** Three-step precedence
  with full decision matrix: `on_constraint_fail` (when explicit and non-null)
  wins, ATTENUATE for ALLOW + attenuable, DENY otherwise. Run-time
  re-evaluation cycle detection MUST break with DENY after configurable
  re-entry count (RECOMMENDED 3); static cycle rejection is RECOMMENDED but
  not REQUIRED (undecidable in general).
- **C.2 ActionPattern.** New field `on_constraint_fail: Decision | null`
  (default null) — author-declared decision when constraints fail and
  attenuation does not apply. MUST be null if `constraints` is empty
  (silent no-op rejected at policy load). MUST NOT be ATTENUATE
  (attenuation is algorithmic, not author-controlled).
- **3 new conformance vectors** (`policy_evaluation` suite): PE-mixed
  (categorical+numeric mixed-failure on ALLOW MUST DENY, not ATTENUATE —
  prevents authority leak), PE-ocf-001 (on_constraint_fail routes ESCALATE
  rule's failure to ALLOW), PE-att-mf (multi-field LTE attenuation clamps
  both fields).

### Changed (normative, breaking)
- **`AuthorityGrantRevoked` replaced by `AuthorityGrantTerminated`** — see
  0.4.0-draft. (No new breakage in this revision; flagged here for
  cross-version implementers.)
- **D.2 algorithm.** Constraint-failure branch now consults
  `on_constraint_fail` before attenuation; previously attenuation always
  won for ALLOW + numeric. v0.4.0 policies without the new field are
  unaffected (null default preserves attenuation behavior). v0.4.0 rules
  that relied on the implicit "ALLOW + LTE failure → ATTENUATE always"
  semantics still get ATTENUATE; the new field is opt-in.
- **`can_attenuate` operator set narrowed.** v0.4.0 reference impl admitted
  LT/LTE/GT/GTE; v0.5.0 admits LTE/GTE only. A v0.4.0 implementation that
  attenuated LT/GT failures is non-conforming under v0.5.0. The
  spec was previously silent on the operator set; v0.4.0 implementations
  diverged in practice. This is a breaking change at the conformance layer
  for any implementation that attenuated strict inequalities.
- **Conformance vectors `delegation` suite.** DL-001 through DL-004
  reshaped to schema-valid `PolicyScope` (was a flat `delegatable: [...]`
  list). Required `decision` on each `ActionPattern`, required
  `max_breadth` on each `DelegationRule`, recursive `delegatable_scope`
  is itself a `PolicyScope`. v0.4.0 vectors failed JSON Schema validation
  in four places per recursion level; now schema-conformant. DL-005 and
  DL-006 remain stateful setup vectors validated by the integration
  harness, not the unit-vector runner.
- **Conformance vector EL-003.** Now specifies its policy explicitly
  (previously underspecified — implementations had to invent one and
  diverged). `modified_action` is now a valid `ModifiedAction` per C.7
  (prior shape conflated `ModifiedAction` outer with `ActionDescriptor`
  inner).

### Schemas
- `schemas/types.schema.json` — `ActionPattern.on_constraint_fail` added
  with explicit enum `["ALLOW", "DENY", "ESCALATE"]` (excludes ATTENUATE
  at validation), conditional `if constraints empty then on_constraint_fail
  must be null`.
- `schemas/events.schema.json` — `ActionEvaluated` adds conditional
  `if decision == ATTENUATE then attenuation: not null` (previously
  prose-only normative requirement).

### Tests
- Reference: 72 / 0 / 13 (was 69; +3 new vectors). Integration: 30 / 0 / 0.
  Total: 102 / 0 / 13.

### Improved (from 0.4.0)
- Section 3.3 ATTENUATE narrative tightened to match Patch 1's narrowed
  scope (was broader: "read-only instead of read-write, redacted data"; now
  scoped to v0.5 numeric clamping with the broader patterns flagged as
  out-of-scope for this revision).
- F.5 attenuation-not-applicable prose tightened to reference Attenuation
  Eligibility's specific conditions.
- Reference impl: cleaner separation of concerns — `is_finite_number` and
  `can_attenuate` extracted as named module-level functions; new
  `validate_action_pattern` for policy-load-time checks.

### Process
- Round 1: clean-room implementation exercise produced 36/36-passing
  Python implementation built solely from spec + vectors + schemas (no
  access to reference impl). Surfaced 10 ambiguities, 3 high/medium-severity
  (EL-003 unexpressible under D.2, `can_attenuate` undefined, vector/spec
  shape divergence on `delegatable`).
- Round 2: adversarial review of initial patches caught security-critical
  bug in early `can_attenuate` (any-failing-attenuable would silently drop
  categorical violations) and four schema violations in delegation vector
  reshape.
- Round 3: adversarial review of revisions caught attenuation-vs-author
  precedence inversion (silent override of `on_constraint_fail: DENY`),
  malformed `modified_action` shape, unenforceable static cycle MUST.
  All round-3 findings incorporated.

### Remaining gaps
- Single reference implementation (Python). No second implementation or
  cross-implementation bakeoff. Primary remaining gap.
- Slot-match evaluator uses literal-string containment. Semantic topic
  matching is out of scope for the reference; implementations MAY substitute.
- Trust decay is event-count-based. Time-based decay is an Extension.
- Protobuf definitions not started.
- Conformance vectors file lacks its own JSON Schema; per-test field
  conventions (e.g., `policy_override`, `cases`) are implicit. Should be
  schematized in a future revision.

## 0.4.0-draft (2026-04-21)

Closes operational gaps in Appendix E. Adds Termination Completeness invariant.
Replaces `AuthorityGrantRevoked` with `AuthorityGrantTerminated`.

### Added (spec)
- **Section 3.1 — Termination Completeness invariant.** Every grant termination
  MUST produce exactly one `AuthorityGrantTerminated` event and MUST be reflected
  in the grant struct (`terminated = true`, `terminated_at` set, `terminated_by`
  set for REVOKED or null for system-driven, `termination_reason` set). TTL elapse
  is a termination, not a computed non-state. Eager (scheduled sweep) and lazy
  (on-access) detection both conforming, provided the event is emitted and the
  struct updated before any Policy Gate evaluation runs against the expired grant.
- **`GrantTerminationReason` type** (Appendix C): EXPIRED | REVOKED | CASCADED.
  Distinct from `TerminationReason` for agent identities — a grant and its
  identity can terminate for different reasons.
- **Appendix E.1.** "Cannot" columns completed for all five admin roles, separating
  role-separation restrictions from dual-control restrictions (per E.2).
- **Appendix E.3.2 — Incident Severity and Notification.** Four-tier classification
  (S0/S1/S2/S3) with required notification paths and target engagement times
  (15m / 1h / 4-8h / NBD). Independent of graduated response level (E.3.1).
- **Appendix E.5 — Independent monitoring detection targets.** Six targets
  including silent-corruption proxies and dual-control completion verification.
  Periodic synthetic incident injection to verify monitoring integrity itself.
- **Appendix E.5 — Backup and recovery per-component depth.** RECOMMENDED RPO:
  Ledger ≤ 5m, Identity Registry ≤ 15m, Authority Registry ≤ 1h. Encryption at
  rest with independent keys. Failed restore drills classified as S1 per E.3.2.
- **Appendix E.6 — Governance-of-Governance Metrics.** Eight metrics covering
  the operational integrity of the governance layer itself: incident
  distribution and response time per severity, dual-control completion rate
  (expected 100%), independent monitoring synthetic test result, backup integrity
  verification per component, restore drill timestamp and measured RTO per
  component, key rotation timestamp per key class, on-call coverage (expected 100%).
- **Appendix F expanded 3 → 9 worked examples.** Added: clean deny, authority
  expiration mid-task, tamper detection, fail-closed, Output Evaluator REVISE,
  delegation cascade.

### Changed (normative, breaking)
- **`AuthorityGrantRevoked` replaced by `AuthorityGrantTerminated`.** Not a rename
  alone. The new event MUST fire for all three termination paths (EXPIRED,
  REVOKED, CASCADED) per the Termination Completeness invariant. A 0.3.0
  implementation that only emitted on explicit revocation is non-conforming
  under 0.4.0 even if the event is renamed: TTL elapse and cascade now require
  emission. Breaking change at the conformance layer.

### Tests
- Reference: 69 / 0 / 13 unchanged. Integration: 30 / 0 / 0 unchanged. New
  Termination Completeness invariant exercised by existing stateful policy
  evaluation and audit chain integrity suites.

### Improved (from 0.3.0)
- Appendix E operational ownership — Termination Completeness ownership assigned
  to Grant Administrator; Audit Reader owns verify_integrity cadence and
  external-anchor reconciliation.
- Worked examples expanded from 3 to 9, covering all primary decision paths.

### Remaining gaps
- Single reference implementation (Python). No second implementation or
  cross-implementation bakeoff. Primary remaining gap.
- Slot-match evaluator uses literal-string containment. Semantic topic matching
  is out of scope for the reference; implementations MAY substitute.
- Trust decay is event-count-based. Time-based decay is an Extension.
- Protobuf definitions not started.

## 0.3.0-draft (2026-04-20)

Closes the Extension Profile implementation gaps flagged in 0.2.0.

### Added (reference implementations for Extension Profile components)
- **Appendix D.6 — Trust State Management.** Per-`(agent_id, capability)` trust scores with event-driven updates (ALLOW/DENY/ESCALATE/TAMPER), bounded clamping, decay toward neutral, and scrutiny tier mapping. Reference implementation covers the algorithm in full.
- **Appendix D.7 — Policy Gate Tier 3 Behavioral Pattern Analysis.** Deterministic rules based on trust score and recent-escalate count. Five-rule decision tree (escalation-pattern override, low-trust mutating → ATTENUATE, low-trust read-only → ALLOW, normal with audit, fast-path). Reference implementation covers the algorithm in full.
- **Appendix D.8 — Output Evaluator.** Two alignment methods: D.8.1 keyword overlap (baseline) and D.8.2 slot match (structured `TaskDeclaration` with required_topics, forbidden_topics, allowed_resources). Both methods share uniform credential-pattern detection and out-of-scope capability-reference detection. Reference implementation covers both methods.

### Added (tests)
- 23 new reference tests: 7 trust, 7 Tier 3, 4 keyword-overlap, 5 slot-match. All pass. Total reference tests: 69 executed, 0 failed, 13 skipped (integration-covered).

### Closed gaps (from 0.2.0 remaining-gaps list)
- ~~Trust Engine remains architecturally defined but not exercised by the reference implementation~~ → D.6 implemented and tested
- ~~Output Evaluator scope alignment remains architecturally defined but not exercised~~ → D.8.1 and D.8.2 implemented and tested
- ~~Policy Gate Tier 3 remains architecturally defined but not exercised~~ → D.7 implemented and tested

### Remaining gaps
- Single reference implementation (Python). No second implementation or cross-implementation bakeoff.
- Slot-match evaluator uses literal-string containment for topic detection. Semantic topic matching (embedding-based or classifier-based) is out of scope for the reference; implementations MAY substitute semantic methods provided determinism requirements for the Audit Ledger record are met by other means.
- Trust decay is event-count-based in the reference. Time-based decay is an Extension that implementations MAY substitute.

## 0.2.0-draft (2026-04-20)

Addresses gaps identified in adversarial review of v0.1.1.

### Added
- **Section 1.3 — Scope of Governance-Layer Defense Against Prompt Injection.** Explicit scoping statement separating model-layer defenses (out of scope) from governance-layer containment (in scope). Maps injection consequences to the System Guarantees that contain them.
- **Section 9.2 — AI Governance Standards.** Relationship tables for NIST AI RMF 1.0, NIST AI 600-1 Generative AI Profile, ISO/IEC 42001:2023, MITRE ATLAS, OWASP LLM Top 10 (2025), and EU AI Act (Regulation (EU) 2024/1689). Previous Section 9 becomes Section 9.1 (Security and Identity Standards).

### Changed (normative, breaking)
- **Hash chain canonical form** (Appendix D.5) switched from pipe-delimited `key=value` to **RFC 8785 (JSON Canonicalization Scheme, JCS)**. The prior form was ambiguous for field values containing `|` or `=`. Implementations conforming to v0.1.x will produce different chain hashes from v0.2.0 implementations for the same entry content. This is a breaking change at the conformance layer.

### Resolved gaps (from adversarial review)
- ~~Prompt injection identified as Threat 3 but not engaged architecturally~~ → Section 1.3 scopes and maps to containment mechanisms
- ~~No relationship to NIST AI RMF, ISO 42001, MITRE ATLAS, or OWASP LLM Top 10~~ → Section 9.2 added
- ~~Hash chain canonical form has no escaping rules for `|` or `=`~~ → Replaced with RFC 8785 JCS

### Remaining gaps
- Trust Engine, Output Evaluator scope alignment, and Policy Gate Tier 3 remain architecturally defined but are not exercised by the reference implementation. Either implement stubs or demote from prose assertions in README to clearly marked future work.
- Single reference implementation. No second implementation or cross-implementation bakeoff.

## 0.1.1-draft (2026-04-11)

Closes five gaps identified in specification review.

### Added
- **JSON Schemas** (`schemas/`): Machine-readable JSON Schema definitions for all types (Appendix C) and all 14 event types. Normative for interoperability.
- **Canonical algorithms** (`spec/02-algorithms.md`): Formal definitions for action pattern matching, first-match-wins policy evaluation, constraint evaluation, scope subset comparison, rate limit evaluation, and hash chain verification.
- **Reference implementation** (`simulation/reference_algorithms.py`): Executable Python implementations of all canonical algorithms with test runner.
- **Conformance test vectors** (`tests/conformance-vectors.json`): 25 algorithmic test cases (pattern matching, scope subset, policy evaluation) plus 11 behavioral test definitions (delegation, escalation lifecycle). All algorithmic tests pass against reference implementation.
- **Worked examples** (`spec/04-worked-examples.md`): Three end-to-end scenarios with complete event traces — simple allow, attenuation with modification record, escalation with candidate rule promotion lifecycle.
- **Governance-of-governance** (`spec/03-governance-of-governance.md`): Administrative role separation, dual control requirements for high-risk operations, kill switch authorization protocol, policy change management lifecycle, infrastructure security requirements, and observability metric requirements.
- **Conformance profiles**: Core Profile (5 components) and Extension Profiles (Trust, Output Governance, Adaptive Escalation, Compliance Projection).

### Changed
- Positioning: "open architectural standard" → "draft interoperability specification"
- Trust Engine: explicit normative statement that trust adjusts scrutiny level within existing authority, never creates new permissions
- Compliance language: "legally defensible" → "supports evidence production for"; added disclaimer that adoption does not equal compliance
- Output Evaluator moved to Extension Profile (not Core conformance)

### Resolved gaps
- ~~Types are expressed as markdown pseudo-types~~ → JSON Schema published
- ~~Canonical algorithms not formally specified~~ → Appendix D with reference implementation
- ~~Conformance profiles not defined~~ → Core + Extension profiles in README and spec
- ~~Governance-of-governance not formally specified~~ → Appendix E with role separation, dual control, observability
- ~~No conformance test suite~~ → 25 algorithmic test vectors + 11 behavioral test definitions

### Remaining gaps
- Output Evaluator scope alignment needs narrower testable semantics (Extension Profile — not blocking Core conformance)
- No Protobuf definitions yet (JSON Schema covers primary interoperability need)
- Conformance test vectors cover algorithms but not full system integration scenarios

## 0.1.0-draft (2026-04-11)

Initial draft specification. See git history for full initial content list.
