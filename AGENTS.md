# Yolol100 GitHub governance repository agent contract

## Scope
- This repository owns shared GitHub governance, account-level repository metadata and reusable administration conventions for Yolol100 repositories.
- It is governance infrastructure only. It must never become a workflow controller, project source or domain owner.
- `webactueel-workflow` remains the cross-skill controller; each repository/domain owner remains responsible for implementation and acceptance.
- Do not place client truth, credentials, run residue or repository-specific mutable runtime state here.

## Agent capability and impact policy
- Classify every intended action as `read_only`, `safe_write` or `high_risk_write`.
- `read_only`: inspect/search/diff/validate without mutating external state.
- `safe_write`: bounded and reversible governance/documentation changes with exact target preflight and readback.
- `high_risk_write`: permission/ruleset changes, destructive administration, release/publication, secret/security settings or broad multi-repository mutation. Keep these behind explicit owner approval and stronger verification.
- Tool availability, an agent request or green CI never grants broader authority.

Before non-trivial changes, build a bounded impact context from the exact governance file, repositories that consume it, related contracts and validation evidence. Generated repository graphs/indexes are commit-bound evidence/cache only, never project truth, durable memory or a second controller.

GitHub Trending and external repositories are discovery signals only. Extract patterns, then verify owner fit, current primary/official guidance, local regression evidence and compatible usage rights before reusing code, prompts, assets or configuration.

## Change discipline
- Prefer the smallest generic governance delta that solves a proven cross-repository gap.
- Do not push product/domain policy into this repository.
- Read back every mutation and verify that unrelated repository metadata is unchanged.
