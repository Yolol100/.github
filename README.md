# Repository standards

Deze repository levert standaard community-, security- en bijdragebestanden aan publieke repositories van `Yolol100` die geen eigen versie bevatten.

## Standaarden

- [SECURITY.md](SECURITY.md) — veilig melden van kwetsbaarheden.
- [CONTRIBUTING.md](CONTRIBUTING.md) — branches, tests en pull requests.
- [SUPPORT.md](SUPPORT.md) — supportgrenzen en geschikte kanalen.
- [Bugrapport](.github/ISSUE_TEMPLATE/bug_report.yml) — reproduceerbare defecten zonder gevoelige data.
- [Featureverzoek](.github/ISSUE_TEMPLATE/feature_request.yml) — probleemgestuurde verbeteringen.
- [Beveiligingscontact](.github/ISSUE_TEMPLATE/security_contact.yml) — alleen een veilig contactverzoek, zonder kwetsbaarheidsdetails.
- [Pull-requesttemplate](.github/PULL_REQUEST_TEMPLATE.md) — risico, bewijs en rollback.

Privérepositories erven deze bestanden niet automatisch en moeten ze expliciet kopiëren of een eigen repositoryspecifieke versie onderhouden. Een publieke repository met eigen bestanden onder `.github/ISSUE_TEMPLATE/` erft de centrale formulieren evenmin en moet daarom `security_contact.yml` lokaal kopiëren wanneer geen private vulnerability reporting beschikbaar is. Repositoryspecifieke bestanden hebben altijd voorrang op deze defaults. Runtime-, beveiligings- en releaseclaims moeten door de betreffende repository zelf worden bewezen.

## GitHub admin control

- [`github-admin.json`](github-admin.json) is the source of truth for repository descriptions, homepage URLs and topics that ChatGPT may safely maintain through the existing GitHub connector. Each repository entry can manage only the fields it declares, so description-only portfolio updates do not overwrite an existing homepage or topics.
- [`.github/workflows/github-admin.yml`](.github/workflows/github-admin.yml) applies config changes automatically. It validates first, previews the diff, applies only required changes, reads every result back and rolls back earlier writes when a later repository fails.
- [`.github/workflows/github-admin-ci.yml`](.github/workflows/github-admin-ci.yml) runs syntax, config and scenario tests without privileged credentials and audits the current public profile pins against the desired order in `github-admin.json`.
- [`.github/scripts/apply-github-admin.py`](.github/scripts/apply-github-admin.py) rejects malformed config, refuses stale writes after preflight and locks the config owner to the GitHub account that owns this control repository.
- External Actions are pinned to an immutable commit SHA and checkout credentials are not persisted.

### One-time credential setup

The apply workflow requires a repository secret named `GH_ADMIN_TOKEN`. Use a **dedicated fine-grained personal access token** with **All repositories** access and repository permission **Administration: write** when you want this control repository to manage current and future repositories on the account. Do not reuse or pipe the broad OAuth token from `gh auth token` into this secret.

Create the fine-grained token in GitHub account settings, then store that token as the `GH_ADMIN_TOKEN` Actions secret on `Yolol100/.github`. The token is consumed only by the apply job and is never committed to this repository.

### Profile pins

The desired personal-profile pin order is stored in `github-admin.json` under `profile.desired_pins`. CI reads the current public pin state through GitHub's documented GraphQL fields and warns when it differs.

GitHub currently documents personal pin changes through **Profile → Customize your pins → Save pins**. Its public GraphQL profile surface exposes `pinnedItems`, `pinnedItemsRemaining` and `viewerCanChangePinnedItems` for inspection, but no supported personal-profile pin write mutation is documented. For that reason this repository does not automate undocumented browser requests; it keeps the desired state machine-readable and verifies drift.

## Privacy

Plaats nooit tokens, wachtwoorden, privélogs, klantinhoud, medische gegevens, accountgegevens of productieexports in publieke issues, pull requests of artifacts.
