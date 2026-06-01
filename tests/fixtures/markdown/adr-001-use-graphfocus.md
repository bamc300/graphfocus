# ADR 001 — Use GraphFocus for code intelligence

## Status

Accepted.

## Context

We need a way to give our AI tools structural awareness of the codebase
without sending entire files every time. Existing tools like
[graphify](README.md) handle Python only.

See also [[Architecture]] and the [Sigma.js docs](https://www.sigmajs.org/).

## Decision

Adopt GraphFocus.

### Consequences

- Tokens consumed by IA drop significantly.
- Visualization becomes WebGL-based (see [[Visualization]]).
