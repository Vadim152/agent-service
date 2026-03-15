# OpenCode Skills

This repository ships local OpenCode-compatible skills in [`.opencode/skills`](C:/Users/BaguM/IdeaProjects/agent-service/.opencode/skills).

## Layout

- Each skill lives in `.opencode/skills/<skill-name>/SKILL.md`.
- Skills use YAML frontmatter with OpenCode-oriented metadata such as `name`, `description`, and `compatibility: opencode`.
- The agent service discovers them through the existing OpenCode resource API, and the IDE plugin can inspect them with `/skills`.

## How To Trigger Them

Use normal agent-mode prompts. Examples:

- `Сгенерируй cucumber feature для нового сценария авторизации`
- `Добавь java step definitions для этих шагов cucumber`
- `Почини undefined cucumber steps в этом feature`

The skills are descriptive guidance for the OpenCode agent. They are not separate slash commands.

## Source Policy

Shipped skills are local-only in v1. This keeps them:

- compatible with OpenCode discovery in this repo;
- reviewable in the same codebase as the agent service;
- low-risk from a supply-chain perspective.

Official references may inform future updates, but we do not vendor third-party skill packs verbatim.

## Vendoring Rules

If upstream material is adopted later:

- use only pinned, reviewable upstream references;
- record provenance in the skill frontmatter;
- review compatibility with OpenCode before merging;
- avoid copying external skills unchanged into the repo.
