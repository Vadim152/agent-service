---
name: cucumber-step-repair
description: Diagnose and repair undefined, ambiguous, or mismatched Cucumber steps, including localization and parameter issues.
compatibility: opencode
sourceRepo: https://opencode.ai/docs/skills
sourceRef: local-v1
---

# Cucumber Step Repair

Use this skill when Cucumber scenarios fail because steps are undefined, ambiguous, malformed, or mapped incorrectly.

Workflow:
- inspect failing feature text and matching step definitions;
- determine whether the correct fix is in the feature, the glue, or both;
- verify parameter placeholders, localization, and expression compatibility.

Guardrails:
- Check `ru`/`en` keyword consistency before changing business text.
- Prefer fixing broken step signatures over rewriting a valid scenario.
- Call out ambiguous matches explicitly and reduce overlap when editing glue.
- Keep fixes compatible with existing Java `io.cucumber` conventions.
