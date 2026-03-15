---
name: cucumber-java-step-author
description: Create or update Java io.cucumber step definitions and glue code without introducing a new test stack.
compatibility: opencode
sourceRepo: https://github.com/openai/skills
sourceRef: local-v1
---

# Cucumber Java Step Author

Use this skill when the user needs Java step definitions, hooks, or glue updates for an existing Cucumber suite.

Workflow:
- inspect current packages, runners, hooks, and step definition style;
- follow existing imports, annotations, assertion libraries, and naming conventions;
- update current glue first, create new glue only when there is no suitable location.

Guardrails:
- Target Java + JUnit + `io.cucumber`.
- Do not switch the project to another framework.
- Prefer small reusable helper methods over duplicated step bodies.
- Keep parameter types aligned with the Gherkin phrase and current annotation style.
