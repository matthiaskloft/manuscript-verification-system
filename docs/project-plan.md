# Projektplan: Manuscript Verification System

> **Namensgebung:** Das Gesamtsystem heißt **Manuscript Verification System**. Das
> erste und bislang einzige umgesetzte Modul – die Referenz- und Zitationsprüfung,
> die dieses Repository ausliefert – heißt **OpenRefCheck**. Weitere geplante Module
> (statistische Konsistenzprüfung, kontextbezogene Volltextprüfung) erhalten eigene
> Namen, sobald sie umgesetzt werden.

## Ziel

Entwicklung eines modularen Systems zur automatisierten Qualitätsprüfung wissenschaftlicher Arbeiten. Das System soll Autor:innen, Betreuende und Universitätsbibliotheken dabei unterstützen, erfundene oder fehlerhafte Referenzen sowie unzureichend belegte Aussagen frühzeitig zu erkennen.

## Zielgruppen

Das System adressiert drei primäre Nutzergruppen mit unterschiedlichen Prüfanforderungen:

1. **Editor:innen wissenschaftlicher Zeitschriften:** Sie müssen eingereichte Manuskripte effizient vorsortieren und bewerten. Durch die zunehmende Menge an teilweise minderwertigen, LLM-generierten Inhalten benötigen sie schnelle, nachvollziehbare Hinweise auf erfundene Referenzen, schwach belegte Aussagen und weitere Qualitätsprobleme.
2. **Prüfende von Abschlussarbeiten:** Sie müssen beurteilen, ob Studierende wissenschaftliche Regeln eingehalten und sorgfältig mit Quellen gearbeitet haben. Für eine manuelle Kontrolle jeder einzelnen Referenz und Zitation fehlt im Prüfungsalltag meist die Zeit.
3. **Autor:innen und Studierende:** Sie möchten die Qualität ihrer Artikel oder Abschlussarbeiten vor der Einreichung selbst überprüfen, Fehler korrigieren und nachvollziehen, an welchen Stellen Quellen oder Belege verbessert werden sollten.

## MVP: Reference Checker

Der erste, datenschutzfreundliche Prototyp verarbeitet ausschließlich das Literaturverzeichnis eines hochgeladenen Dokuments und benötigt zunächst kein LLM. Er wird als **lokal installierte Anwendung** ausgeliefert (siehe [Architektur/Bereitstellung](#architekturbereitstellung)) – es gibt in dieser Phase keinen zentralen Server, auf dem fremde Dokumente verarbeitet werden.

- Referenzen aus PDF- und DOCX-Dateien lokal auf dem Gerät der Nutzerin/des Nutzers extrahieren und strukturieren – das Dokument verlässt das Gerät nicht
- Publikationen über OpenAlex, Crossref und DOI-Datenbanken verifizieren – über Live-API-Aufrufe mit minimalem Feldumfang (Titel/Autor:in/DOI); vollständiges Selbst-Hosting ist nicht praktikabel und daher kein MVP-Ziel (siehe [Technischer Stack (MVP)](#technischer-stack-mvp))
- Optional: bereits abgefragte Referenzen lokal zwischenspeichern, um wiederholte Prüfungen ohne erneute externe Anfrage zu ermöglichen (Stufe 1 im [Stufenmodell](#stufenmodell-zur-risikominimierung), verschlüsselt und durch Nutzerin/Nutzer löschbar)
- Dubletten, unvollständige Angaben und wahrscheinlich halluzinierte Quellen markieren
- Referenzen, die nicht automatisiert verifiziert werden konnten, in einer eigenen Ansicht zur manuellen Prüfung bereitstellen (siehe [Manuelle Verifizierung nicht auflösbarer Referenzen](#manuelle-verifizierung-nicht-auflösbarer-referenzen))
- Kennzahlen zu verifizierten und einzigartigen Quellen, Zitierhäufigkeiten, Alter und thematischer Breite berechnen
- Ergebnisse in einem konfigurierbaren Dashboard visualisieren (Tabellen, Verteilungen/Scores – kein Netzwerkgraph im MVP, siehe [Erweiterungsmodule](#erweiterungsmodule))
- Prüfbericht mit Kategorie-Scores und Konfidenzwerten exportieren

### Manuelle Verifizierung nicht auflösbarer Referenzen

Nicht jede Referenz lässt sich automatisiert klären: kein Treffer bei OpenAlex/Crossref,
mehrere ähnlich plausible Kandidat:innen, oder ein Treffer unterhalb eines
Konfidenz-Schwellwerts. Diese Fälle landen nicht stillschweigend im Score, sondern in einer
eigenen Review-Liste, die die Nutzerin/der Nutzer manuell abarbeitet:

- **Auslöser:** kein automatischer Treffer, mehrdeutige Kandidat:innen (mehrere Treffer mit
  ähnlicher Ähnlichkeitsbewertung) oder Konfidenz unterhalb eines konfigurierbaren
  Schwellwerts.
- **Ansicht:** Tabelle der offenen Referenzen mit automatisiertem Status, Konfidenzwert und –
  falls vorhanden – den besten Kandidat:innentreffern zur Auswahl.
- **Aktionen pro Referenz:** manuell bestätigen (Kandidat:in ist korrekt), manuell korrigieren
  (DOI/Metadaten von Hand eintragen), als nicht auffindbar/vermutlich fehlerhaft markieren,
  optionaler Freitext-Kommentar zur Begründung.
- **Persistenz:** manueller Status, Zeitstempel und Kommentar werden zusätzlich zum
  automatisierten Status lokal gespeichert – in Phase A ohne weitere Serverkommunikation,
  siehe [Speicherung und Löschung](#speicherung-und-löschung).
- **Im Prüfbericht:** automatisierter und manueller Status werden getrennt ausgewiesen (inkl.
  Zeitstempel des manuellen Reviews). Das macht die im Abschnitt
  [Rechtsgrundlage und Governance](#rechtsgrundlage-und-governance) diskutierte Frage nach
  Art. 22 DSGVO im Bericht selbst nachprüfbar – ob tatsächlich echter Beurteilungsspielraum
  ausgeübt wurde, statt es nur zu behaupten.

## Erweiterungsmodule

1. **Citation Context Check:** In-Text-Zitate dem Literaturverzeichnis zuordnen und fehlende oder ungenutzte Einträge erkennen.
2. **Claim Verification:** Volltexte abrufen und per LLM prüfen, ob Quellen die jeweiligen Aussagen tatsächlich stützen.
3. **Methodological Flags:** Widersprüche markieren, etwa kausale Aussagen, die nur durch korrelative Studien belegt werden.
4. **Reproducibility Check:** Statistische Angaben automatisiert prüfen, orientiert an [regcheck](https://github.com/JamieCummins/regcheck).
5. **Quality Report:** Nachvollziehbare Einzelbefunde und Kategorie-Scores mit Konfidenzwerten zusammenfassen.
6. **Zitationsnetzwerk-Visualisierung:** Beziehungen zwischen den zitierten Publikationen als Netzwerkgraph darstellen. Bewusst nicht Teil des MVP – benötigt eine Graph-Rendering-Bibliothek (z. B. d3.js/sigma.js) und wird erst bei Bedarf als eigene, in sich abgeschlossene Ansicht ergänzt (siehe [Technischer Stack (MVP)](#technischer-stack-mvp)).

## Vorhandene Bausteine und Referenzprojekte

- Der bestehende MCP-Server [matthiaskloft/zotero-fulltext-mcp](https://github.com/matthiaskloft/zotero-fulltext-mcp) dient als technischer Ausgangspunkt für den Volltextzugriff. Im Zuge der späteren Volltextprüfung soll untersucht werden, welche Funktionen oder Implementierungsansätze daraus direkt übernommen oder für das Manuscript Verification System angepasst werden können.
- [regcheck](https://github.com/JamieCummins/regcheck) dient als Orientierung für automatisierte Reproduzierbarkeits- und Konsistenzprüfungen statistischer Angaben.
- [Scite](https://scite.ai/) dient als Referenz für die kontextbezogene Bewertung wissenschaftlicher Zitationen; das geplante System konzentriert sich zunächst auf die Prüfung eines konkreten Manuskripts.

### Langfrist-Vision und Wettbewerbsanalyse (Phase B und darüber hinaus)

Vier weitere Planungsdokumente beschreiben die langfristige Produktvision – ein
zentral betriebener, institutioneller Dienst für Editor:innen, Research-Integrity-
Officer und Universitätsverwaltung, deutlich über den aktuellen MVP-Scope hinaus.
Sie enthalten jeweils einen Scope-Hinweis, der sie explizit von diesem Plan
abgrenzt, da sie andernfalls mit dem MVP-Scope und dem Phase-A/B-Modell kollidieren
würden:

- [Open Integration Stack Proposal](open-stack-proposal.md): vorgeschlagene
  Zielarchitektur inkl. Gleichungs-/Variablenprüfung, Statistik-Checks (statcheck,
  scrutiny/GRIM) und institutionellem Service-Betrieb – Funktionen, die **nicht**
  Teil des aktuellen MVP sind (siehe [MVP: Reference Checker](#mvp-reference-checker)).
- [EU Data, Privacy, and AI Compliance Requirements](eu-data-privacy-compliance.md):
  breiterer Compliance-Katalog (inkl. EU-AI-Act-Bereitschaft für ein künftiges
  LLM-Modul) als Ergänzung zum MVP-scoped Abschnitt
  [Datenschutz (DSGVO)](#datenschutz-dsgvo) unten.
- [Clean-room Development Policy](clean-room-development-policy.md): Vorgaben für
  eine unabhängige Implementierung überlappender Funktionen (v. a. gegenüber
  MetaCheck), falls keine lizenzierte Integration gewählt wird.

Alle vier Dokumente sind Diskussionsentwürfe, keine beschlossene Erweiterung des
MVP-Scopes.

## Architektur/Bereitstellung

Das System wird bewusst in zwei Bereitstellungsphasen entwickelt, nicht nur in
Funktionsstufen:

1. **Phase A – Lokale Anwendung (Stufe 0/1):** Die Anwendung läuft vollständig auf dem
   Gerät der Nutzerin/des Nutzers (Desktop-App oder lokal gestarteter Dienst). Es gibt
   keinen zentralen Server, der Dokumente Dritter entgegennimmt oder speichert. Damit
   entfällt für diese Phase die Notwendigkeit eines Auftragsverarbeitungsvertrags mit einem
   Hosting-Anbieter und das Risiko einer zentralen Datenpanne. Das ändert aber **nichts an
   der Verantwortlichenstellung der Universität** (Art. 4 Nr. 7 DSGVO): Nutzen Prüfende oder
   Studierende die App in dienstlicher Funktion, bleibt die Universität Verantwortliche –
   Rechtsgrundlage, Transparenzpflichten (Art. 13) und Sicherheitsmaßnahmen (Art. 32) gelten
   unverändert, nur eben ohne zentrale Serverinfrastruktur. Auch der Bedarf einer
   Datenschutz-Folgenabschätzung (DSFA, Art. 35 DSGVO – international auch als DPIA
   bezeichnet) kann schon in Phase A entstehen, sobald die App systematisch zur Bewertung von
   Studierenden
   eingesetzt wird (siehe [Rechtsgrundlage und Governance](#rechtsgrundlage-und-governance)).
   Einzige verbleibende Übermittlungen nach außen sind die Live-API-Abfragen an
   OpenAlex/Crossref (siehe [Datenübermittlung an Drittländer](#datenübermittlung-an-drittländer)),
   die durch minimalen Feldumfang (Titel/Autor:in/DOI statt Volltext-Kontext) begrenzt
   werden – ein Selbst-Hosting der Referenzdatenbanken ist für Phase A nicht praktikabel
   (siehe [Technischer Stack (MVP)](#technischer-stack-mvp)) und daher keine Option, um diese
   Übermittlung in Phase A zu vermeiden. Hinzu kommen mögliche Nebenkanäle wie
   Auto-Update- oder Crash-Reporting-Funktionen der App selbst – diese müssen vor Auslieferung
   geprüft und wenn nötig deaktiviert oder auf EU-Infrastruktur gelegt werden, sonst
   unterläuft ein "unauffälliger" Telemetriekanal die gesamte Local-first-Architektur.
2. **Phase B – Server-Dienst auf Uni-Infrastruktur (Stufe 2/3):** Erst wenn die in
   [Datenschutz (DSGVO)](#datenschutz-dsgvo) gelisteten Punkte geklärt sind (Rechtsgrundlage,
   DSB-Freigabe, ggf. DSFA, AVV, Löschkonzept), wird ein Server-Dienst auf
   Uni-Infrastruktur aufgesetzt. Erst ab dieser Phase werden Volltexte zentral
   gespeichert oder an weitere Dienste (LLM) weitergereicht – und erst ab dieser Phase
   kommt zur bestehenden Verantwortlichenrolle die Pflicht hinzu, Auftragsverarbeiter nach
   Art. 28 DSGVO vertraglich zu binden (z. B. das Uni-Rechenzentrum, sofern es als externer
   Betreiber auftritt).

Der Umstieg von Phase A auf Phase B ist ein expliziter Freigabepunkt, kein automatischer
Nebeneffekt wachsender Funktionalität.

## Technischer Stack (MVP)

**Sprache: Python durchgängig** für Kernlogik (Extraktion, OpenAlex/Crossref-Anbindung,
Anwendungslogik). GROBID (JVM) und AnyStyle (Ruby) laufen ohnehin als eigenständige,
containerisierte Dienste über HTTP – das erzwingt Python nicht. Ausschlaggebend ist die
Reife der domänenspezifischen Bibliotheken: `pyalex` und `habanero` sind etablierte,
gepflegte Clients für OpenAlex/Crossref. Die Rust-Äquivalente (`crossref-rs`,
`openalex`-Crates) sind dünner und weniger battle-tested; für Node/JS existiert überhaupt
kein vergleichbar etablierter Client – dort müsste der REST-Zugriff komplett selbst gebaut
und dauerhaft selbst gepflegt werden. Da das Team mit Python vertraut ist, überwiegt der
Bibliotheksvorteil den geringen Architekturvorteil, den Rust/Tauri oder Node/Electron sonst
böten.

**UI: PySide6** statt NiceGUI-native, Electron oder Tauri. Der Hauptgrund für ein
webview-basiertes UI – Zugriff auf JS-Graphbibliotheken für das Zitationsnetzwerk – entfällt
für den MVP-Scope, da dieses Modul bewusst auf später verschoben ist (siehe
[Erweiterungsmodule](#erweiterungsmodule)). PySide6 rendert nativ über Qt, ganz ohne
Abhängigkeit von einer System-Webview-Komponente (WebView2 unter Windows, WebKitGTK unter
Linux) – relevant, weil die Zielnutzer:innen (Prüfende, Betreuende) häufig auf verwalteten,
restriktiven Uni-Rechnern arbeiten, auf denen eine fehlende oder veraltete Webview-Runtime
ein reales Verteilungsrisiko wäre, das man dort nicht selbst beheben kann. Zusätzlicher
Vorteil: einfachere PyInstaller-Verpackung ohne Laufzeit-Abhängigkeitsprüfung. Wird das
Netzwerkgraph-Modul später gebaut, kommt dafür eine einzelne `QWebEngineView`-Insel für
genau diese eine Ansicht hinzu – keine Neuarchitektur der ganzen Anwendung. Der im MVP
geforderte "Prüfbericht ... exportieren" als HTML-Datei (Jinja2-Template mit eingebetteten
matplotlib-Grafiken) braucht dafür keine Rendering-Laufzeit in der App selbst – Erzeugen
einer HTML-Datei ist reines Templating, kein eingebetteter Browser.

- **Diagramme:** `matplotlib` (eingebettet via `FigureCanvasQTAgg`) für Dashboard und
  HTML-Report; Aufwertung auf `pyqtgraph` möglich, falls interaktivere Diagramme
  (Zoom/Filter) gebraucht werden.
- **Tabellen:** native Qt `QTableView`/`QTableWidget`.
- **Packaging:** PyInstaller, pro Zielplattform nativ gebaut (kein Cross-Compiling).

**Referenzextraktion – gestuftes Benchmark-Konzept**, vor der finalen Auswahl gegen die
Referenzlisten der eigenen veröffentlichten Open-Access-Artikel zu evaluieren (Goldstandard
über die Crossref Works API `/works/{DOI}` abrufbar, kein manuelles Labeling nötig):

| Tier | Ansatz | Charakteristik |
|---|---|---|
| 0 | PyMuPDF + python-docx + Regex-Heuristiken | Baseline, kein zusätzliches Laufzeitsystem. **Stresstest gegen ein reales, nicht in `tests/fixtures/` enthaltenes Manuskript** (Siepe et al. 2024, Bayesian estimation of idiographic network models — Psychologie/Statistik, viele Referenzen mit 5–15+ Autor:innen) deckte zwei Splitting-Bugs in `_APA_AUTHOR_START_RE` (`src/openrefcheck/extraction/tier0.py`) auf, beide seither behoben: (1) eine umgebrochene Autor:innen-Liste, deren zweite Zeile zufällig selbst wie "Nachname, I." aussieht (ein Koautor/eine Koautorin), wurde fälschlich als neuer Eintrag erkannt und zerriss den echten Eintrag in zwei kaputte Fragmente — betraf 8 von 78 Roheinträgen (~10 %) in diesem einen Dokument und war die alleinige Ursache **aller** "kein Treffer/Review"-Fehlklassifikationen dieses Checks, nicht nur ein Rand­fall (Fix: ein Zeilen-Start wird erst als neuer Eintrag akzeptiert, wenn seit dem letzten akzeptierten Start bereits ein `(JJJJ)`-Jahr gesehen wurde, mit einer Zeilenzahl-Obergrenze als Fallback für jahrlose Einträge wie "(n.d.)"); (2) niederländische/deutsche Nachnamenspartikel in Kleinschreibung ("van der Veen, D.", "van Erp, S.") wurden nie als Eintragsanfang erkannt (Regex verlangte einen Großbuchstaben am Zeilenanfang) und verschmolzen lautlos mit dem vorherigen Eintrag (Fix: optionales `(?:[a-zà-ý]+\s+){0,2}`-Präfix vor dem Großbuchstaben-Nachnamen). Nach beiden Fixes: 78 → 71 korrekt getrennte Einträge, keine Fragmente/Merges mehr; volle Testsuite (`pytest`) weiterhin grün. Stichprobe über echte Dateien aus der eigenen Zotero-Bibliothek (Zotero-MCP: `zotero__search`/`get_children`/lokale ZotMoov-Attachment-Basis, nicht der Zotero-Volltextindex — letzterer flacht Zeilenumbrüche anders ab als der eigene PyMuPDF-Pfad und ergab dadurch einen zunächst irreführenden, nicht reproduzierbaren Befund) deckte einen dritten, unabhängigen Splitting-Bug auf: (3) der Zitierstil von *Journal of Statistical Software* ("Nachname II (JJJJ)." — Initialen ohne Punkt/Komma, z. B. "Alexandrov T, Decker J … (2009).") wurde von keiner der vier bisherigen Heuristiken erkannt und die gesamte 26-Einträge-Bibliografie kollabierte auf 1 Block (Fix: neue `_JSS_AUTHOR_START_RE`-Heuristik, alle-Großbuchstaben-Initialen mit Wortgrenze direkt danach, um keine normalen großgeschriebenen Fließtext-Phrasen zu treffen; nutzt dieselbe jahr-gegatete Split-Logik wie der APA-Fallback). Getestet gegen 6 reale, verschiedenartige Artikel (Psychologie/Statistik mit 5–15 Autor:innen, IEEE-nummeriert, MDPI-nummeriert, APA mit niederländischen Partikeln, JSS-Stil) — alle sauber, keine Fragmente/Merges mehr. Bekannte, bewusst nicht behobene Grenze: bei der JSS-Datei hängt sich ein Autor:innen-Adressblock direkt nach dem letzten echten Eintrag ohne eigene Überschrift an und wird als zusätzlicher, inhaltsloser Pseudo-Eintrag mitgesplittet (kein sauberer Anker zur Unterscheidung "Adresse" vs. "Referenz", ohne das Risiko neuer falscher Treffer anderswo einzugehen — daher dokumentiert statt heuristisch geraten). Eigener Struktur-Benchmark für genau diese Splitting-/Titel-Pipeline (getrennt vom reinen DOI-Regex-Scan, der als Tier-0-Beitrag im Ensemble dient): `scripts/run_tier0_benchmark.py` — lief zum Zeitpunkt dieses Eintrags mangels lokal vorhandener `tests/fixtures/local_pdfs/`-PDFs nur mit "skipped", liefert aber Zahlen sobald diese vorhanden sind. **Zufallsstichprobe über 10 weitere, zufällig aus der Zotero-Bibliothek gezogene Artikel** (Zotero-MCP `search` mit zufälligen Offsets über die gesamte `journalArticle`-Menge, echte PDF-Pfade über `get_children` + die ZotMoov-Basis aus `extensions.zotmoov.attach_search_dir` in `prefs.js` aufgelöst — nicht der Zotero-Volltextindex) deckte zwei weitere, unabhängige Bugs auf, beide seither behoben: (4) die drei nummerierten Heuristiken (`[1]`, `1.`, sowie eine neu ergänzte "bare number"-Variante ohne jede Interpunktion, z. B. "1 Hogan JW, Laird NM…" bei *International Journal of Epidemiology*) prüften bislang nur "mindestens 2 Treffer", nicht ob die gefundenen Nummern überhaupt eine echte Sequenz bilden — ein umgebrochener Seitenbereich wie "107, 238–\n246." erzeugt eine alleinstehende Zeile "246.", die als Nummerierungs-Marker fehlinterpretiert wird und (mit nur 2 zufälligen Treffern) die komplette, eigentlich unnummerierte APA-Bibliografie kapert: bei *Ferrando (1999)* kollabierten dadurch 47 echte Einträge auf 2 Riesenblöcke. Fix: `require_sequential` in `_entries_from_line_starts` verlangt jetzt, dass die Marker-Zahlen tatsächlich 1, 2, 3, … fortlaufen; die Prüfung ist bewusst *greedy* (einzelne nicht passende Zeilen werden übersprungen, nicht die ganze Heuristik verworfen), weil auch eine echte nummerierte Bibliografie gelegentlich eine zufällige Nicht-Sequenz-Zeile enthalten kann (beobachtet: ein umgebrochenes "2019." aus einem Jahr mitten in einer sonst korrekt 1–30 durchnummerierten Liste); (5) mehrwortige, großgeschriebene Nachnamen wie "De Mario, T. J." wurden nicht erkannt, weil der Partikel-Präfix aus dem vorherigen Fix nur Kleinschreibung ("van", "de") abdeckte — Fix: Präfix-Zeichenklasse auf beliebige Groß-/Kleinschreibung erweitert (`[A-Za-zÀ-ÿ]+` statt `[a-zà-ý]+`). Nach beiden Fixes: alle 10 Stichproben-Artikel plus die bereits getesteten 5 zusammen praktisch fehlerfrei (0–1 Restauffälligkeiten pro Dokument). Eine verbleibende, bewusst nicht behobene Beobachtung: bei einem Artikel (*Irwing et al. 2023*) enthält ein einzelner Autor:innenname ("Rönkkö") im PDF einen eigenständigen Diaerese-Glyphen (U+00A8) statt eines vorkomponierten "ö" — ein Font-/Encoding-Fehler der Quell-PDF selbst, keine Unicode-NFD-Zerlegung (die eine `unicodedata.normalize("NFC", …)`-Vorverarbeitung beheben könnte) und damit auf Regex-Ebene nicht sauber reparierbar, ohne PDF-spezifisches Rätselraten zu betreiben. |
| ~~0.5~~ | ~~[`refextract`](https://pypi.org/project/refextract/) (CERN/INSPIRE-HEP)~~ — **evaluiert und verworfen** | Spike gegen eigene Kloft-Erstautor:innen-PDFs (Preprints + Open-Access-Artikel) zeigte: bereits `import refextract` bzw. ein einzelner Zitationsstring hängt sich auf (getestet bis 90s, teils >20 GB RAM). Ursache: bekannter, seit 2017 offener Bug in der Autor:innen-Parsing-Regex ([catastrophic backtracking, inspirehep/refextract#26](https://github.com/inspirehep/refextract/issues/26)) – kein Performance-, sondern ein Korrektheitsproblem der Regex selbst, nicht durch Timeouts o. Ä. entschärfbar. Kein produktionstauglicher Kandidat. |
| 1 | GROBID (lokal containerisiert, REST) | **Mit eigenen Daten nachgeprüft** (Skript: `scripts/run_grobid_benchmark.py`, gegen 4 Kloft-Erstautor:innen-Manuskripte, je Preprint- und veröffentlichte Version): DOI-Recall Ø 0,873, DOI-Precision Ø 0,950 gegen den kombinierten Crossref+OpenAlex-Goldstandard. Preprints schneiden konsistent schlechter ab als die veröffentlichte Version desselben Manuskripts (z. B. "measuring_variability": Recall 0,67 vs. 0,88) – erwartbar, da Preprint-Layouts oft weniger GROBID-freundlich sind, aber ein Befund, den ein Benchmark nur auf Basis veröffentlichter Artikel übersehen hätte |
| 2 | AnyStyle (Ruby, containerisiert eigenes Image, `docker/anystyle/Dockerfile` – kein offizielles Image verfügbar) | **Mit eigenen Daten nachgeprüft** (Skript: `scripts/run_anystyle_benchmark.py`, gleicher Goldstandard/gleiche Manuskripte wie Tier 1): DOI-Recall Ø 0,646, DOI-Precision Ø 0,896 – spürbar schwächerer Recall als GROBID (0,873) bei ähnlicher Precision. Auffällig: bei "measuring_variability" schneidet hier die veröffentlichte Version schlechter ab als der Preprint (Recall 0,26 vs. 0,60) – umgekehrtes Muster zu GROBID bei demselben Manuskript, d. h. welches Tier "besser mit Preprints umgeht" ist keine pauschale Tool-Eigenschaft, sondern hängt vom konkreten Dokumentenlayout ab |
| 3 | Ensemble aus Tier 0–2 ("Swiss-Cheese"-Vereinigung: DOI-Match plus Titel-Fuzzy-Match für DOI-lose Treffer) | **Mit eigenen Daten nachgeprüft** (Skript: `scripts/run_ensemble_benchmark.py`): DOI-Recall Ø 0,873 (identisch zu GROBID allein), DOI-Precision Ø 0,862 (schlechter als GROBID allein: 0,950) – bestätigt weiterhin, dass eine reine DOI-Vereinigung keine neuen echten DOI-Treffer bringt, nur zusätzliche Falsch-Positive. Die ursprüngliche Merge-Implementierung war zudem fehlerhaft "swiss cheese": sie deduplizierte nur nach DOI und **verwarf jede DOI-lose Referenz komplett**, wodurch Parsing-Recall (siehe unten) auf 0,08 einbrach, obwohl die Einzeltools die meisten Referenzen korrekt gelesen hatten – nur eben ohne im Text gedrucktes DOI. Nach Korrektur (Titel-Fuzzy-Dedup für DOI-lose Treffer, plus Auffüllen fehlender Titel bei geteiltem DOI zwischen Tiers) liegt Parsing-Recall Ø 0,880 – nahezu identisch zu GROBID allein (0,881), d. h. das Ensemble verliert hier keine von GROBID bereits korrekt geparsten Referenzen mehr, gewinnt auf diesen 7 Dokumenten aber auch keine zusätzlichen hinzu. Ensemble bleibt damit **kein MVP-Kandidat gegenüber GROBID allein** – der Zusatzaufwand (zwei weitere Container, Merge-Logik) lohnt sich auf dieser Datenbasis nicht |

Bewertungsmetrik (implementiert in `src/openrefcheck/benchmark/`): **zwei** unabhängige Metriken,
weil eine reine DOI-Metrik zwei verschiedene Fehlerursachen vermischt – "Tool hat Referenz gar
nicht erkannt/geparst" und "Tool hat Referenz korrekt geparst, aber die Quelle druckt keine DOI
im Text":

1. **DOI-Recall/-Precision/-F1** (`score.py`), gemessen gegen die **Vereinigung** der DOI-
   Referenzen aus Crossref Works API und OpenAlex' `referenced_works`-Graph
   (`combined_gold.py`) – beide Quellen sind je für sich unvollständig (z. B. lieferte
   OpenAlex für einen erst 2025 erschienenen Artikel noch 0 referenzierte Werke, da die
   Zitationsgraph-Indexierung dort Zeit braucht), die Vereinigung deckt mehr echte Referenzen
   ab als jede Quelle allein.
2. **Parsing-Recall/-Precision** (`parsing_match.py`), Titel-Fuzzy-Match gegen Crossrefs
   `article-title`/`unstructured`-Feld pro Referenz – unabhängig davon, ob eine DOI im Text
   stand. Nur Parsing-Recall ist verlässlich: Crossref taggt Titel nur für eine Teilmenge der
   Referenzen eines Dokuments, Parsing-Precision ist dadurch bei geringer Titel-Abdeckung
   (`gold_titled` in der Report-Ausgabe) ein schwaches Signal (siehe Docstring in
   `parsing_match.py`).

Der komplette Goldstandard (DOIs, Zähler sowie Crossref-Titel/Jahr/Erstautor:in-Einträge, keine
Volltexte) liegt versioniert unter `tests/fixtures/ground_truth.json`
(`scripts/build_ground_truth.py` zum Neuerzeugen). Weiterhin bewusst enger als eine vollständige
Precision/Recall/F1 pro Feld (Autor:in/Jahr/Titel/DOI kombiniert), da Autor:in/Jahr allein ohne
manuelles Labeling nicht zuverlässig automatisiert abgleichbar wären.

**Einschränkungen dieses Benchmarks, die bei der Interpretation zu beachten sind:**

- Crossref-Referenzlisten sind nicht garantiert vollständig oder strukturiert – viele
  Verlage liefern nur unstrukturierte Zeichenketten statt geparster Autor:in/Jahr/Titel/DOI-
  Felder. Ein Tool kann dadurch künstlich gut oder schlecht abschneiden, je nachdem wie
  sauber die Metadaten des jeweiligen Verlags sind, nicht nur je nach eigener Extraktionsgüte.
  Vor der Auswertung stichprobenartig prüfen, ob die eigenen DOIs überhaupt strukturierte
  Referenzlisten bei Crossref hinterlegt haben.
- Die eigenen Artikel decken nur ein Fachgebiet, wenige Verlage und deren PDF-Layout-
  Konventionen ab – das Ergebnis sagt wenig darüber aus, wie die Tools auf studentischen
  Abschlussarbeiten mit anderen Zitierstilen und Layouts abschneiden. Der Benchmark eignet
  sich für eine erste Tier-Auswahl, nicht als abschließende Qualitätsaussage.
- **Zeitbudget festlegen, bevor der Benchmark beginnt:** Drei Basis-Ansätze (Tier 0–2) plus
  deren Ensemble (Tier 3) zu evaluieren (inkl. GROBID- und AnyStyle-Container aufsetzen) ist
  für ein Solo-/Kleinteam-Projekt ein nicht triviales Stück Infrastrukturarbeit. Ein
  Abbruchkriterium ("Tier X reicht, wenn F1 > Y erreicht wird") vorab festlegen, damit der
  Benchmark nicht selbst zum Projekt wird, bevor das MVP überhaupt läuft.

**Bibliografische Verifizierung:** Für Phase A zunächst Live-API-Aufrufe (`pyalex`,
`habanero`) direkt aus der lokalen Anwendung. Vollständiges Selbst-Hosting ist nicht
praktikabel (Größenordnung: OpenAlex-Snapshot mehrere hundert GB bis niedriger TB-Bereich,
Crossref Public Data File ca. 200 GB laut Crossrefs eigener Ankündigung des aktuellen
Jahrgangs – vor einer Kapazitätsplanung die aktuellen Werte auf den jeweiligen
Anbieter-Seiten neu prüfen, da beide Datensätze jährlich wachsen) und bleibt daher kein
MVP-Ziel. Ein leichtgewichtiger, EU-gehosteter Caching-Proxy bleibt als dokumentierte Option
für Phase B, sobald ein Server ohnehin ansteht; `ourresearch/openalex-api-proxy` wurde
geprüft, ist aber OpenAlex' eigener, US-betriebener Edge-Cache und keine self-hostbare
Lösung – zum Zeitpunkt der Recherche wurde kein maintainter, self-hostbarer Caching-Proxy für
OpenAlex/Crossref gefunden; diese Suche vor Phase B erneut durchführen, statt die Abwesenheit
als dauerhaft gegeben anzunehmen.

**Geprüfte und verworfene Alternativen:**

- **Tauri + Rust** (`mupdf-rs`/`rdocx` für Tier 0): technisch machbar, aber dünnere
  Crossref/OpenAlex-Client-Bibliotheken bedeuten höheren Eigenwartungsaufwand, ohne dass der
  ursprüngliche "kein Bridge"-Vorteil ohne Netzwerkgraph-Anforderung noch relevant wäre.
- **Electron + Node** (`pdfjs-dist`/`mammoth.js` für Tier 0): ausgereifte PDF/DOCX-Bibliotheken,
  aber keine etablierte Crossref/OpenAlex-Client-Bibliothek – höchster
  Selbstwartungsaufwand aller Optionen.
- **NiceGUI-native**: war die richtige Wahl, solange das Zitationsnetzwerk Teil des MVP war;
  ohne diese Anforderung bringt die Webview-Laufzeitabhängigkeit (WebView2/WebKitGTK) nur
  Verteilungsrisiko ohne Gegenwert.

## Umsetzung

1. **Prototyp (Phase A, Stufe 0/1):** Lokale Anwendung mit Referenzextraktion, Abgleich
   über Live-API-Aufrufe an OpenAlex/Crossref mit minimalem Feldumfang, einfacher
   HTML-Report (templated, kein eingebetteter Browser nötig) – läuft komplett offline/lokal
   bis auf die Referenzabfrage
2. **Dashboard (Phase A, Stufe 0/1):** Interaktive Statistiken (Tabellen, Diagramme via
   matplotlib/pyqtgraph) innerhalb der lokalen PySide6-Anwendung – Zitationsnetzwerk bewusst
   ausgeklammert (siehe [Erweiterungsmodule](#erweiterungsmodule))
3. **DSGVO-Freigabe für Phase B:** Rechtsgrundlage, DSB-Rücksprache, DSFA-Bedarf, AVV und
   Löschkonzept klären und dokumentieren – Voraussetzung für den nächsten Schritt, nicht
   optional
4. **Zitationskontext (Phase B, Stufe 2):** Server-Dienst auf Uni-Infrastruktur aufsetzen,
   Volltext-Speicherung mit Löschkonzept und Zugriffsschutz umsetzen, In-Text-Zitate dem
   Literaturverzeichnis zuordnen
5. **Claim Verification (Phase B, Stufe 3):** Eigener Freigabeschritt, da höheres Risiko –
   Bibliothekszugang klären, Claim-Checking über lokal/selbst gehostetes LLM ergänzen, erst
   nach separater Prüfung von Transfermechanismus und AVV mit dem LLM-Betrieb
6. **Pilotierung:** Mit Abschlussarbeiten testen und Feedback von Bibliothek, Lehrenden und
   Studierenden einholen

## Offene Punkte

- Zugang zu wissenschaftlichen Volltexten über eine Universitätsbibliothek
- Endgültigen Projektnamen auswählen und anschließend Namens-, Marken-, Domain- und Repository-Verfügbarkeit prüfen
- Datenschutz und lokale Verarbeitung unveröffentlichter Arbeiten (siehe [Datenschutz (DSGVO)](#datenschutz-dsgvo))
- Umgang mit unsicheren Treffern und unterschiedlichen Zitierstilen
- Abgrenzung zu bestehenden Angeboten
- Evaluation anhand manuell geprüfter Referenzen und Claims
- Umgang mit übergroßen oder beschädigten PDF/DOCX-Dateien beim Upload
- Reproduzierbarkeit des Prüfberichts: OpenAlex/Crossref-Metadaten ändern sich über die Zeit
  (neue Retraction-Einträge, korrigierte Angaben) – zwei Prüfungen desselben Dokuments zu
  unterschiedlichen Zeitpunkten können unterschiedliche Ergebnisse liefern; das sollte im
  Bericht selbst (z. B. Prüfdatum, abgefragte API-Version) sichtbar gemacht werden
- Zitierstil-Erkennung: `src/openrefcheck/extraction/tier0.py` und `title.py` probieren aktuell nur
  stilspezifische Regex-Heuristiken der Reihe nach durch (nummeriert/IEEE, APA-Autor:in-Jahr,
  Vancouver), ohne den erkannten Stil je zu klassifizieren oder am Dokument/an der Referenz zu
  speichern. Ob ein explizites Stil-Tagging (z. B. zur gezielten Auswahl der passenden
  Heuristik statt Trial-and-Error, oder zur Anzeige im Report) den Aufwand wert ist, ist noch
  offen – Verifizierung/Matching danach ist bewusst stilunabhängig (reiner Titel-Abgleich) und
  bräuchte dafür keine Änderung
- ~~GROBID (Tier 1) optional in der App nutzbar machen~~ — **umgesetzt**: neues
  `src/openrefcheck/extraction/grobid.py` wrapt `benchmark/grobid_client.py`
  (`call_grobid`/`parse_grobid_tei`) für den Produktionspfad und liefert
  `RawReferenceEntry`s mit direkt gesetztem `title`. `extraction/document.py`s
  `extract_references()` prüft für PDFs per `is_grobid_available()` (GET
  `/api/isalive`, 2s Timeout) die Erreichbarkeit und fällt bei nicht laufendem GROBID
  oder einem `GrobidUnavailableError` (Verbindungsfehler, Timeout, Parse-Fehler)
  transparent auf Tier 0 zurück, statt einen Fehler anzuzeigen — kein
  Settings-Umschalter, GROBID ist ein Best-Effort-Upgrade, kein Nutzer-Toggle. DOCX
  nutzt weiterhin immer Tier 0 (GROBID kann kein DOCX). `gui/real_pipeline.py` nutzt
  `entry.title`, wenn vorhanden, und fällt sonst auf die `extraction/title.py`-Heuristik
  zurück. GROBID-URL über `GROBID_URL`-Env-Var konfigurierbar (Default
  `http://localhost:8070`, ein lokaler Container — bleibt konsistent mit dem
  "local"-Modus-Privacy-Versprechen in `gui/deployment.py`, da das Dokument das Gerät
  nicht verlässt). Tests: `tests/test_grobid_extraction.py`,
  `tests/test_document_extraction.py`.
  - Lokales LLM statt/zusätzlich zu GROBID wurde erwogen und bewusst zurückgestellt: kein
    geringerer Betriebsaufwand (auch ein externer Dienst, z. B. Ollama + mehrere GB Modell),
    aber ein zusätzliches Risiko, das GROBID nicht hat – plausibel wirkende, aber erfundene
    Titel/DOIs/Jahre statt eines sauberen Parsing-Fehlschlags. Falls überhaupt, dann nur als
    eng begrenzter Fallback für die wenigen Einträge, die weder Tier 0 noch GROBID sauber
    splitten/titeln können (ungewöhnliche Formatierung, gemischte Sprachen) – nicht als
    primärer Parser, und nur nach eigener Benchmark-Prüfung (existierendes Benchmark-Setup
    in `src/openrefcheck/benchmark/` könnte dafür wiederverwendet werden). Naheliegendster
    Einstiegspunkt: ein Button auf dem Manual-Review-Screen
    (`gui/screens/manual_review.py`), der pro einzelnem ungelöstem Eintrag das lokale LLM um
    einen Titel-/Autor:innen-/Jahr-Vorschlag bittet – nicht als automatischer Pipeline-Schritt,
    sondern On-Demand für genau die Referenz, die eine Person gerade ohnehin manuell prüft, die
    also einen erfundenen Vorschlag direkt erkennen würde, statt dass er unbemerkt in den
    Bericht einfließt
- **TODO:** `_extract_pdf_text`/`find_bibliography_section` in `extraction/document.py` per
  [`pymupdf4llm`](https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/) statt reinem
  PyMuPDF-`get_text()` prüfen. Kein zusätzlicher externer Dienst, kein ML/GPU-Bedarf (baut auf
  derselben PyMuPDF-Abhängigkeit auf, nur ein zusätzliches Paket) — liefert echte
  Markdown-Überschriften (`#`/`##`, aus Schriftgröße abgeleitet) statt reinem Fließtext und
  explizite Mehrspalten-Layout-Erkennung. Beides adressiert direkt dokumentierte Schwächen von
  `find_bibliography_section()` (exakter Zeilen-Textvergleich gegen eine feste
  Überschriften-Liste, verwundbar durch zeilenumbrochene Überschriften oder zufällig
  gleichlautende Fließtext-Zeilen — siehe Docstring dort) sowie das Fehlen einer expliziten
  Spalten-Lesereihenfolge im aktuellen `_extract_pdf_text`. Ersetzt **nicht** Tier 0s
  Eintrags-Splitting-Heuristiken (`tier0.py`) oder GROBID — nur eine mögliche Verbesserung der
  Dokumentstruktur-Erkennung, die diesen Heuristiken vorgelagert ist. Vor Übernahme: Vergleich
  gegen die bestehenden synthetischen Fixtures und die eigenen Stresstest-Manuskripte (siehe
  Tier-0-Eintrag oben), ob `NoBibliographySectionError`-Rate und Fehl-Splits sinken.

## Datenschutz (DSGVO)

> Dieser Abschnitt ist ein Planungsstand, keine rechtliche Freigabe. Er dient als
> Diskussionsgrundlage für die Rücksprache mit dem/der Datenschutzbeauftragten der
> Universität – nicht als Ersatz dafür.

Jedes Modul verarbeitet personenbezogene Daten: die Namen zitierter Autor:innen im
Literaturverzeichnis ebenso wie – sobald Volltext ins Spiel kommt – die Angaben der
einreichenden Person selbst (häufig Studierende). Die folgenden Punkte sind vor einem
Pilotbetrieb zu klären, nicht erst danach.

### Rechtsgrundlage und Governance

- Rechtsgrundlage je Nutzungsszenario festlegen (Art. 6 DSGVO): Einwilligung der
  einreichenden Person vs. Stützung auf die Prüfungsordnung, wenn Prüfende das Tool nutzen.
  Beide Fälle brauchen unterschiedliche Transparenz- und Widerrufsmechanismen. Gilt bereits
  für Phase A – die lokale Bereitstellung ändert nichts an der Notwendigkeit einer
  Rechtsgrundlage, nur an der technischen Angriffsfläche.
- Rücksprache mit dem/der Datenschutzbeauftragten der Universität vor der Pilotierung;
  klären, ob eine DSFA nötig ist – naheliegend,
  sobald das Tool systematisch zur Bewertung von Studierenden eingesetzt wird. Dieser
  Trigger hängt an der Nutzung, nicht an der Architektur, und kann daher schon in Phase A
  greifen, wenn Prüfende die App regelmäßig zur Bewertung von Abschlussarbeiten einsetzen.
- Verarbeitungsverzeichnis-Eintrag (Art. 30) gilt unabhängig von der Architektur, sobald die
  Universität die Verarbeitung als Verantwortliche betreibt – nicht erst "sobald ein Server
  feststeht". Ein Auftragsverarbeitungsvertrag (Art. 28) kommt erst in Phase B hinzu, wenn
  ein externer Hosting-/Rechenzentrumsbetrieb als Auftragsverarbeiter eingebunden wird.
- Auto-Update-, Telemetrie- und Crash-Reporting-Funktionen der lokalen Anwendung selbst als
  eigenen Übermittlungskanal prüfen (siehe [Architektur/Bereitstellung](#architekturbereitstellung))
  – sonst unterläuft ein "unauffälliger" Hersteller-Kanal die lokale Verarbeitung.
- Scores/Konfidenzwerte sind als Unterstützung für Prüfende konzipiert, nicht als Ersatz für
  deren Beurteilung. Ob das tatsächlich keine automatisierte Entscheidung im Sinne von
  Art. 22 DSGVO darstellt, hängt davon ab, ob Prüfende in der Praxis echten
  Beurteilungsspielraum ausüben – ein UI mit manueller Review-Möglichkeit allein genügt dafür
  nicht, wenn sie unter Zeitdruck faktisch zum Abnicken wird. Das ist bei der Pilotierung zu
  beobachten und ggf. mit der/dem Datenschutzbeauftragten zu klären, nicht als von vornherein
  geklärt zu behandeln.

### Datenübermittlung an Drittländer

- OpenAlex und Crossref sind US-basiert. Der Abgleich von Autor:innennamen und Titeln ist
  eine Drittlandübermittlung (Art. 44 ff.) und muss über eine gültige Grundlage abgesichert
  werden. Für das MVP heißt das konkret: **EU-US Data Privacy Framework-Zertifizierung für
  OpenAlex und Crossref jeweils einzeln und aktuell prüfen** (nicht als "US-Unternehmen
  generell zertifiziert" annehmen – Zertifizierungen sind anbieterspezifisch, müssen zum
  Zeitpunkt der Nutzung gültig sein und können, wie beim Vorgänger Privacy Shield, rückwirkend
  für ungültig erklärt werden). Vollständiges Selbsthosting würde die Übermittlung vermeiden,
  ist aber für Phase A nicht praktikabel (siehe [Technischer Stack (MVP)](#technischer-stack-mvp))
  und bleibt eine mögliche spätere Option über einen EU-gehosteten Proxy in Phase B. Das gilt
  unabhängig davon, ob die Anfrage von einem Uni-Server oder direkt von der lokalen Anwendung
  einer Nutzerin/eines Nutzers ausgeht – die lokale Architektur entschärft das zentrale
  Speicherrisiko, nicht diese Übermittlung. OpenAlex und Crossref agieren dabei als
  eigenständige Verantwortliche für die bei ihnen ohnehin öffentlich vorliegenden
  bibliografischen Metadaten, nicht als Auftragsverarbeiter der Universität – ein AVV nach
  Art. 28 ist hier nicht das passende Instrument (anders als beim Uni-Rechenzentrum oder
  einem LLM-Anbieter in Phase B); relevant ist stattdessen ausschließlich der
  Transfermechanismus für die Drittlandübermittlung (DPF-Zertifizierung o. Ä.).
- Verhalten bei API-Ausfall oder Rate-Limiting festlegen: Sowohl OpenAlex als auch Crossref
  können zeitweise nicht erreichbar sein oder Anfragen drosseln – die Anwendung muss dies der
  Nutzerin/dem Nutzer transparent machen (z. B. "Referenz X konnte nicht geprüft werden") statt
  einen Treffer stillschweigend als unauffällig zu werten.
- Bei späteren LLM-Modulen: keine Übermittlung von Volltexten unveröffentlichter Arbeiten an
  externe LLM-APIs ohne AVV, geprüfte Transfermechanismen und – wo möglich – vorherige
  Pseudonymisierung/Redaktion identifizierender Angaben.

### Speicherung und Löschung

- Für Phase A: Verarbeitung so ephemer wie möglich halten – Dateien werden ausschließlich
  lokal geöffnet, es gibt keine Ablage auf einem Server, die gelöscht werden müsste.
- Für Phase B: Aufbewahrungsfristen für gespeicherte Volltexte, extrahierte Referenzlisten
  und Prüfberichte definieren und dokumentieren, bevor Server-seitige Speicherung eingeführt
  wird.
- Verarbeitungsort (EU-Hosting) für den Server-Dienst in Phase B von Anfang an festlegen, um
  zusätzliche Drittlandtransfers durch die Infrastruktur selbst zu vermeiden.

### Stufenmodell zur Risikominimierung

Die Module lassen sich nach DSGVO-Risiko ordnen, sodass jede Ausbaustufe bewusst mehr
personenbezogene Daten preisgibt – und einzeln freigegeben werden kann.

| Stufe | Bereitstellung | Umfang | Was verlässt die Kontrolle des Systems | DSGVO-Risiko | Risikominimierender Hebel |
|---|---|---|---|---|---|
| **0 – Referenzprüfung, lokal** | Phase A: lokale Anwendung | Dokument wird auf dem eigenen Gerät geparst, nur das Literaturverzeichnis wird zur Prüfung herangezogen | Autor:innennamen/Titel an OpenAlex/Crossref (Live-API, Drittlandübermittlung bleibt bestehen – Selbst-Hosting ist nicht praktikabel, siehe [Technischer Stack (MVP)](#technischer-stack-mvp)) | Niedrig-mittel – kein Upload an einen Server überhaupt, kein zentraler Betreiber, aber die Drittlandübermittlung an sich bleibt bestehen | **Feldbegrenzung** (nur Titel/Autor:in/DOI statt Volltext-Kontext) plus DPF-Zertifizierungsprüfung je Anbieter; vollständige Vermeidung nur durch einen EU-gehosteten Proxy in Phase B möglich (siehe [Technischer Stack (MVP)](#technischer-stack-mvp)) |
| **1 – Referenzprüfung, lokal mit Cache** | Phase A: lokale Anwendung | Wie Stufe 0, zusätzlich lokaler Zwischenspeicher/Cache auf dem eigenen Gerät für wiederholte Prüfungen | Wie Stufe 0 | Niedrig-mittel – Daten bleiben auf dem Gerät der Nutzerin/des Nutzers, keine zentrale Speicherung, aber dieselbe Drittlandübermittlung wie Stufe 0 | Gleicher Feldbegrenzungs-Hebel wie Stufe 0; lokaler Cache verschlüsselt und durch Nutzerin/Nutzer löschbar, reduziert wiederholte Anfragen an OpenAlex/Crossref |
| **2 – Zitationskontext (In-Text-Check)** | Phase B: Server auf Uni-Infrastruktur | Volltext wird serverseitig gehalten, um Zitate im Fließtext zuzuordnen | Volltext liegt zentral auf dem Uni-Server, länger als für eine einzelne Anfrage nötig | Mittel – Speicherung von Volltext unveröffentlichter Arbeiten erfordert Löschkonzept, AVV mit Uni-Rechenzentrum und Zugriffsschutz | **Redaktion/Feldbegrenzung vor jedem Export:** nur die für den Abgleich nötigen Felder (Titel/Autor:in/DOI) verlassen die Volltext-Speicherzone; Zugriff auf den Volltext-Speicher selbst eng begrenzen und protokollieren |
| **3 – Claim Verification (LLM)** | Phase B: Server auf Uni-Infrastruktur | Volltextabschnitte werden an ein Sprachmodell geschickt, um Aussagen gegen Quellen zu prüfen | Volltextauszüge an LLM-Provider | Hoch – Drittlandtransfer plus Verarbeitung durch externen Anbieter; braucht AVV, Transfermechanismus, ggf. Redaktion | **Lokales/selbst gehostetes LLM** (offenes Modell auf Uni-/EU-Infrastruktur) statt externer API vermeidet den Drittlandtransfer für die risikoreichste Stufe vollständig, auf Kosten von Qualität/Aufwand |

Phase A (Stufen 0/1) kann ohne Server-Governance ausgeliefert werden, weil es schlicht
keinen Server gibt, der fremde Dokumente verarbeitet. Der Übergang zu Phase B (Stufen 2/3)
ist an die Klärung aller Punkte im Abschnitt [Rechtsgrundlage und Governance](#rechtsgrundlage-und-governance)
gebunden.

Übergreifendes Prinzip: **Opt-in pro Stufe.** Nutzer:innen entscheiden aktiv, ob sie über
Stufe 0 hinausgehen – das MVP bleibt der datenschutzfreundliche Standardpfad, höhere Stufen
sind explizite Zusatzfunktionen mit eigener Einwilligung und eigenem Rechtsgrundlagen-Check.

## Kurzpitch

Ein sofort nutzbares Referenzprüfungsmodul bildet den Einstieg in ein umfassendes, modulares Qualitätssicherungssystem für wissenschaftliche Manuskripte.
