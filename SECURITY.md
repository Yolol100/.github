# Beveiligingsbeleid

## Ondersteunde versies

Tenzij een repository anders vermeldt, worden alleen de actuele default branch en de nieuwste gepubliceerde release actief beoordeeld. Oudere releases kunnen buiten onderhoud vallen.

## Een kwetsbaarheid melden

Publiceer geen exploitdetails, credentials, privélogs, klantdata of productieexports in een publiek issue.

1. Gebruik bij voorkeur **Security → Report a vulnerability** in de betreffende repository wanneer private vulnerability reporting beschikbaar is.
2. Is die optie niet beschikbaar, gebruik dan het detailvrije formulier **Beveiligingscontact** in de betreffende repository. Vermeld geen technische details; vraag alleen om een privé-kanaal. Repositories met eigen issue-templates moeten dit formulier lokaal kopiëren, omdat GitHub de centrale templatemap dan niet erft.
3. Beschrijf privé minimaal het getroffen project en versie, reproduceerstappen, impact, benodigde voorwaarden en een mogelijke mitigatie.

Verwacht geen automatische ontvangst- of oplostermijn. De maintainer bevestigt scope en vervolgstappen zodra de melding veilig is ontvangen.

## Grenzen

- Een groen CI-resultaat bewijst geen afwezigheid van kwetsbaarheden.
- Automatische scanners vervangen geen handmatige validatie.
- Draai geen destructieve proof-of-concept tegen productie of systemen van derden.
