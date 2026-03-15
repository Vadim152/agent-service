---
name: cucumber-feature-author
description: Author or refine valid Cucumber feature files for Java/JUnit repositories, reusing existing project steps first.
compatibility: opencode
sourceRepo: https://opencode.ai/docs/skills
sourceRef: local-v1
---

# Cucumber Feature Author

Use this skill when the user wants to create or improve a Cucumber `.feature` file in a Java project.

Inspect the repository before writing:
- find existing `.feature` files and step definitions;
- preserve the dominant Gherkin language (`ru` or `en`);
- reuse existing step wording when possible instead of inventing new phrases.

Guardrails:
- Prefer valid Gherkin over verbosity.
- Use `Scenario Outline` only when examples are clearly needed.
- Keep steps implementation-friendly for `io.cucumber`.
- If required behavior is unclear, state the assumption in the output.
