# Changelog

## Unreleased

- Moved the public backend model to `runs`, `sessions`, `policy`, and `platform/*`
- Preserved free-text autotest creation through session intent parsing
- Added Postgres-backed control-plane persistence for sessions, runs, approvals, audits, and artifacts
- Added RabbitMQ-backed queue support and worker concurrency controls
- Expanded tool host into connector-style routes for repo, patch, and artifact operations
- Added artifact index plus local or S3-compatible object storage support
- Migrated the IntelliJ plugin to the runs-first API surface
- Stabilized plugin Gradle tests on Windows by moving pure unit tests off the IntelliJ JUnit5 `ThreadLeakTracker` path and keeping test runs inside a local IDEA sandbox
