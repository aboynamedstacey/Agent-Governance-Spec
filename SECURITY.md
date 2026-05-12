# Security Policy

## Reporting specification vulnerabilities

A specification-level vulnerability is a flaw in the specification text or its supporting artifacts that would let a conforming implementation be exploited. That includes anything that lets one of the nine system guarantees be circumvented, contracts whose plain reading permits unsafe behavior, and gaps that leave an attack surface unaddressed.

Do not report specification-level flaws through public issue channels. Use GitHub's private vulnerability reporting feature on this repository, or contact the maintainer directly.

## Scope

This policy covers flaws in the specification, its JSON Schemas, and its conformance test vectors. Implementation-specific vulnerabilities should be reported to the maintainer of the affected implementation.

Examples of specification-level vulnerabilities:

- A delegation attenuation rule that permits authority amplification.
- An event schema gap that allows audit entries to be omitted without detection.
- A Policy Gate evaluation order that produces ALLOW when the policy intent is DENY.
- A failure mode that defaults to ALLOW when the specification requires fail-closed behavior.

## Response

Reports will be acknowledged within 72 hours and triaged for severity. Critical specification flaws are those that undermine one of the nine system guarantees. They are addressed in the next specification revision, with a corresponding CHANGELOG entry and a security advisory.
