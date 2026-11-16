# Der Korrespondent

Eine automatisch erstellte, analytische Tageszeitung: jeden Morgen ein Essay pro Ressort (acht Ressorts),
historisch eingeordnet, mit internationaler Presseschau („Weltspiegel“), Faktencheck und englischer Fassung.

Live: https://konstison.github.io/der-korrespondent/

## Ablauf (täglich 05:15 Uhr MEZ, GitHub Actions)

1. `scripts/generate_edition.py`
   - liest ~30 RSS-Feeds (Politik, Wirtschaft, Wissenschaft/Medizin, Technik, Feuilleton; deutsch + international)
   - Chefredaktion (Gemini): ein Thema je Ressort, Gewichtung, Dossier-Schlagworte, Bezug auf frühere Essays
   - lädt Volltexte frei zugänglicher Quellen (robots.txt wird respektiert; Bezahlangebote nur Titel + Teaser)
   - schreibt die Essays, prüft sie in einem zweiten Durchlauf gegen die Quellen (Faktencheck mit Prüfprotokoll)
   - übersetzt ins Englische; sonntags zusätzlich Wochenrückblick „Die Woche“
   - schreibt `data/ausgabe.json` und `data/archiv/<datum>.json`
2. `scripts/build_site.py` baut daraus statische Seiten: `artikel/…`, `en/…`, `archiv.html`, `themen/…`,
   `feed.xml`, `sitemap.xml`, `robots.txt`
3. Commit → GitHub Pages veröffentlicht

## Einstellungen

| Wo | Was |
|---|---|
| Repository-Secret `GEMINI_API_KEY_FREE` | Gemini-Schlüssel aus einem Projekt **ohne** Abrechnung (wird zuerst genutzt, kostenlos) |
| Repository-Secret `GEMINI_API_KEY` | Gemini-Schlüssel mit Abrechnung (nur Ausweichlösung bei Überlastung oder erschöpftem Gratis-Kontingent) |
| Repository-Variable `SCHLUESSEL` (optional) | `automatisch` (Standard), `bezahlt` oder `frei` |
| Repository-Variable `SITE_URL` (optional) | Basis-URL, z. B. nach Umzug auf eigene Domain |
| `RSS_FEEDS`, `RESSORTS`, `STANDARD_ANZAHL` in `generate_edition.py` | Quellen, Ressorts, Anzahl Essays in der Standardauswahl |
| Umgebungsvariable `ENGLISCH=0` | englische Fassung abschalten |

## Workflows

- **Tägliche Ausgabe generieren** – automatisch, manuell startbar unter „Actions“
- **Schriften lokal einbinden** – einmalig manuell starten (lädt die Schriften nach `assets/fonts/`)

## Newsletter

`feed.xml` ist ein RSS-Feed aller Essays. Newsletter-Dienste mit „RSS-to-Email“
(z. B. Buttondown, Mailchimp, follow.it) können daraus automatisch einen Morgen-Newsletter versenden.
