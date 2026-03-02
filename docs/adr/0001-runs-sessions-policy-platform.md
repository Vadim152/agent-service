# ADR 0001: Runs, Sessions, Policy, Platform Public Architecture

## Status

Accepted

## Context

The original service exposed legacy `jobs` and `chat/*` APIs while mixing control-plane concerns, execution details, and tool-approval logic. That made it hard to:

- expose a stable client-facing model
- persist runs, sessions, approvals, and artifacts consistently
- split the system into control plane, execution plane, and tool host
- migrate the IntelliJ plugin without preserving old route semantics forever

The target architecture required:

- a control plane centered on `runs`, `sessions`, `policy`, and `platform/*`
- a generic execution model that can support multiple runtime plugins
- a dedicated tool host for repo, patch, artifact, browser, and analytics connectors
- persistent storage for runs, sessions, approvals, audit, and artifacts

## Decision

The public architecture is now defined as:

- `runs`: lifecycle, status, result, events, artifacts
- `sessions`: conversational state, free-text intent entrypoint, streaming, commands
- `policy`: tool registry, approvals, audit
- `platform/*`: step, feature, tool-helper, and memory-management endpoints

Key consequences of this decision:

- legacy `/jobs/*` and `/chat/*` routes are not part of the active public API
- free-text autotest messages remain supported, but they map to `sessions -> intent -> runs(testgen)`
- artifact references are logical `artifact://` URIs backed by an artifact index and object storage
- the IntelliJ plugin is runs-first and talks to `/runs`, `/sessions`, `/policy`, and `/platform/*`
- control-plane state is designed to persist independently from execution workers

## Consequences

Positive:

- cleaner client contract
- easier plugin/backend evolution
- explicit approval and audit boundaries
- split deployment model becomes practical

Tradeoffs:

- migration required compatibility layers during the transition
- documentation and DTOs had to be cleaned up to remove lingering `job` semantics
- plugin tests need explicit sandboxing, and pure unit tests should avoid the IntelliJ JUnit5 `ThreadLeakTracker` path in restricted Windows environments

## Notes

This ADR captures the public architecture and migration outcome. Infrastructure details such as exact queue/storage providers can continue to evolve without changing the client-facing model, as long as the `runs/sessions/policy/platform` boundary remains stable.
