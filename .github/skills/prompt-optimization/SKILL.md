---
name: prompt-optimization
description: 'Improve and optimize prompts for agents and actor-style role behavior. Use for tightening instructions, reducing ambiguity, improving reliability, and increasing actionability with measurable checks.'
argument-hint: 'Describe the current prompt, target behavior, constraints, and failure examples.'
user-invocable: true
---

# Prompt Optimization

## What This Produces
A revised prompt that is clearer, more deterministic, and easier for an agent to execute, plus a short validation checklist.

## When to Use
- Prompt is verbose but underperforms
- Outputs are inconsistent across runs
- Agent misses required steps or constraints
- Role or actor behavior drifts from intent
- Tool usage is wrong, unsafe, or incomplete

## Inputs to Collect
- Current prompt text
- Intended output behavior and format
- Hard constraints (must/never rules)
- 2 to 5 failure examples from real usage
- Success criteria (how we know optimization worked)

## Quick Optimization Checklist
1. Define the objective in one sentence.
2. Convert vague goals into explicit output requirements.
3. Split requirements into:
   - Must do
   - Should do
   - Must not do
4. Add role boundaries:
   - What the agent controls
   - What the agent cannot assume
5. Add process guardrails:
   - Clarify decision points and branch conditions
   - Define fallback behavior for missing inputs
6. Minimize token waste:
   - Remove repetition
   - Replace long prose with short directive bullets
7. Add output contract:
   - Required structure and field names when task output must be machine-consumable
   - Error handling format
8. Add quality gates:
   - Completeness check
   - Constraint compliance check
   - Hallucination risk check
9. Run against failure examples and revise once.
10. Freeze the prompt and record known limitations.

## Branching Decisions
- If failures are mostly formatting errors: prioritize output schema and examples.
- If failures are mostly logic errors: prioritize decision steps and fallback rules.
- If failures are mostly policy/safety errors: prioritize hard constraints and refusal behavior.
- If failures are mostly style drift: tighten persona, tone, and allowed vocabulary.

## Completion Criteria
- Optimized prompt has clear objective, constraints, and output contract.
- At least 80% of known failure examples are addressed.
- No contradiction between instructions and constraints.
- Prompt length is reduced or kept flat while quality improves.
- Structured schema is required only when the task benefits from strict parsing.

## Reusable Prompt Skeleton
Use this as a starting shape:

- Objective: [single sentence]
- Role: [what the agent is responsible for]
- Inputs: [what will be provided]
- Constraints: [must, should, must not]
- Decision Logic: [if X then Y]
- Output Format: [fields and structure]
- Failure Handling: [what to do when data is missing or conflicting]
- Quality Check: [self-check before final output]

## Notes for Agent/Actor Prompts
- Keep role identity stable, but avoid theatrical over-specification.
- Prefer behavior constraints over personality adjectives.
- Bind decisions to observable world state, not hidden assumptions.
- Require explicit uncertainty statements when evidence is missing.
