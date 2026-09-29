# GitHub Admin Companion

Local ChatGPT/Codex plugin for GitHub repository presentation metadata that the standard connector may not expose as write actions.

## What it can do

- Verify local `gh` authentication.
- Read repository description, homepage URL and topics.
- Set description, homepage URL and the exact topic set with readback.
- Read personal profile repository pins.
- Report the GitHub API limitation around writing personal profile pins.

## Why pins are read-only

GitHub's public GraphQL schema exposes `pinnedItems`, `pinnableItems`, `pinnedItemsRemaining` and `viewerCanChangePinnedItems`, but there is currently no supported public mutation for changing a personal user's pinned repositories. The plugin therefore refuses to automate undocumented browser internals for this action.

## Requirements

- Node.js 20+
- GitHub CLI (`gh`)
- An authenticated GitHub CLI session: `gh auth status`

## Install runtime dependencies

From this directory:

```powershell
npm install
```

The plugin host starts `server/index.js` through `mcp.json`.

## Security model

The plugin never requests or stores a GitHub token. It calls the already-authenticated local `gh` executable and relies on the operating system keyring/session used by GitHub CLI.
