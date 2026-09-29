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

- [`github-admin.json`](github-admin.json) is the source of truth for repository descriptions, homepage URLs and topics that ChatGPT may safely maintain through the existing GitHub connector.
- [`.github/workflows/github-admin.yml`](.github/workflows/github-admin.yml) applies changes made to that file.
- [`.github/scripts/apply-github-admin.py`](.github/scripts/apply-github-admin.py) validates, applies and reads back every configured repository through GitHub CLI.
- The workflow requires one repository secret named `GH_ADMIN_TOKEN` with fine-grained **Administration: write** access to the managed repositories. The secret is used only by GitHub Actions and is never stored in this repository.
- Personal profile pins are not changed by this workflow because GitHub does not expose a supported public write operation for them.

## Privacy

Plaats nooit tokens, wachtwoorden, privélogs, klantinhoud, medische gegevens, accountgegevens of productieexports in publieke issues, pull requests of artifacts.
