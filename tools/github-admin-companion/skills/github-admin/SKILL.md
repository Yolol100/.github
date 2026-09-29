---
name: github-admin
description: Use when repository About metadata, homepage URLs, topics, or GitHub profile pin state must be audited or updated through an authenticated local GitHub CLI.
---

# GitHub Admin Companion

Use the MCP tools from this plugin for repository-level GitHub presentation metadata.

For writes, prefer `github_repo_set_about`, then read back the returned repository state. Treat its `topics` input as the exact desired set, not an additive suggestion.

Use `github_profile_get_pins` to inspect current personal profile pins. Do not claim profile pins were changed by API: GitHub's supported public GraphQL surface exposes pin reads but no supported mutation for personal profile pin writes. Direct the user to GitHub's `Customize your pins` UI for that final write.

Never expose the token returned by `gh auth token` or copy credentials into plugin arguments. Authentication is inherited from the local GitHub CLI keyring/session.
