# Contributing

This specification is in draft. Contributions are welcome, particularly ones that close ambiguities in the text or report what happened when a team tried to implement against it.

## Priority contributions

The most valuable contribution at this stage is an independent Core Profile implementation in a language other than Python (TypeScript, Go, or Rust would all close the gap). Until two independently authored codebases pass the same conformance vectors, the specification's interoperability claim is unproven. See [STATUS.md](STATUS.md) for the current definition of a conforming Core implementation.

Other useful work, in approximate order of priority:

- Implementation reports. A short writeup from a team that has built against the specification, focusing on the gaps and decisions the team had to make on its own. These directly drive subsequent revisions.
- Compliance projection modules. Mappings from the specification's event data to specific regulatory frameworks (EU AI Act, SOC 2, HIPAA, and others).
- Framework adapters. GovernanceClient implementations for specific agent frameworks (LangChain, CrewAI, AutoGen).
- Protobuf definitions. JSON Schema is published; Protobuf would extend reach to performance-sensitive deployments.
- Policy linter. A static analysis tool that flags shadowed rules, unreachable rules, and overbroad wildcards in first-match-wins policies.
- Editorial precision. Tightening normative language and reconciling places where the specification text, the JSON Schemas, and the conformance vectors disagree.

## Process

Contributors should open an issue describing the gap or improvement before submitting a pull request. A specification change should reference the specific section and explain what is ambiguous or incorrect; an implementation contribution should include test cases that demonstrate conformance against the relevant Appendix D algorithms. Pull requests should address one item at a time. Bundled changes are slower to review.

## Out of scope

The following are out of scope at this stage:

- Feature proposals that expand the specification's scope before the Core Profile is stable.
- Alternative architectures for components already specified in the Core Profile.
- Compliance opinions or legal interpretations of cited regulatory frameworks.

## License

Contributions are accepted under the Apache License 2.0. Submission of a pull request constitutes agreement that the contribution is licensed under the same terms as the project.
