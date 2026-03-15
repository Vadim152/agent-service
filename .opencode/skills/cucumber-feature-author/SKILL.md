---
name: cucumber-feature-author
description: Create a Cucumber .feature autotest draft from a testcase, requirement, or existing cucumber steps in Java/JUnit repositories, reusing current repo vocabulary and clarifying ambiguity before drafting.
compatibility: opencode
sourceRepo: https://opencode.ai/docs/skills
sourceRef: local-v2
---

# Cucumber Feature Author

Use this skill when the user asks to create a Cucumber autotest or `.feature` draft from:
- a testcase or requirement;
- a list of cucumber steps;
- an instruction like `создай автотест`, `сгенерируй cucumber feature`, `собери feature по шагам`, or similar English variants.

Work in this order:
1. Inspect the repository for existing `.feature` files and Java `io.cucumber` step definitions.
2. Infer the dominant Gherkin language (`ru` or `en`) and the project's naming and path conventions.
3. Reconstruct testcase intent in these dimensions: actor, goal, expected outcome, preconditions, data dimensions.
4. If that intent is too ambiguous for reliable step mapping, ask for clarification before drafting.
5. Search for similar scenarios and reuse existing wording and structure before inventing new steps.
6. Bind intended steps to existing definitions where possible, preferring exact or strong semantic matches.
7. Build only the `.feature` draft. Do not invent Java glue or step-definition code in this skill.
8. Run a final self-check: valid Gherkin, observable outcome present, ambiguity surfaced, unmapped steps called out explicitly.

Guardrails:
- Prefer draft-first behavior over speculative completion.
- Keep the dominant repo language and vocabulary.
- Use `Scenario Outline` only when examples are truly needed.
- If a step cannot be mapped confidently, keep it visible as a placeholder or unmapped draft step and list the gap.
- If multiple phrasings are possible, choose the one closest to existing repo wording.
- Keep the result implementation-friendly for `io.cucumber`, but stop at the `.feature` draft.
