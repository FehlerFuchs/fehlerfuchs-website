# FehlerFuchs — Zentrales Datenmodell

**Stand:** 19.07.2026 · **Version:** 1.0 · **Gültigkeit:** verbindlich für Website 2.0

Dieses Verzeichnis ist die **einzige Wahrheitsquelle** für alle Produktangaben von FehlerFuchs.
Jede Zahl, jedes Datum, jeder Status und jeder Downloadlink steht **genau einmal** hier —
und wird überall sonst daraus abgeleitet.

---

## 1. Warum das nötig war

Vor diesem Modell stand dieselbe Angabe an bis zu sieben Stellen gleichzeitig: auf der
Produktseite, auf `downloads.html`, auf `produkte.html`, auf der Startseite, in
`wunschliste.html`, in `aktuelles.html` und im Update-Manifest. Bei jeder Änderung mussten
alle sieben Stellen von Hand nachgezogen werden. Genau das ist mehrfach schiefgegangen:

| Vorfall | Ursache |
|---|---|
| Startseite zeigte „Beta pausiert", während die Beta lief | Statusangabe an sechs Stellen dupliziert |
| FAQ nannte ein Release-Datum, das längst überholt war | Datum nur auf der Produktseite gepflegt |
| Downloadgrößen fehlten überall | Nirgends erfasst |

Mit einer einzigen Quelle sind solche Widersprüche **strukturell nicht mehr möglich** —
nicht weil man sorgfältiger arbeitet, sondern weil es die zweite Stelle nicht mehr gibt.

---

## 2. Verzeichnisaufbau

```
website/data/
  SCHEMA.md                  ← dieses Dokument
  schema/product.schema.json ← maschinelle Prüfregeln (JSON Schema, Draft 2020-12)
  schema/meldung.schema.json ← dasselbe für die Meldungen
  src/statuses.yaml          ← Statusstufen: Label, Farbe, erlaubte CTA
  src/vokabular.yaml         ← Anzeigetexte für alle technischen Schlüssel
  src/marke.yaml             ← Haltung, Leitsätze, Person, Kontakt
  src/meldungen.yaml         ← Aktuelles: was wann veröffentlicht wurde
  src/products/<slug>.yaml   ← je Produkt eine Datei (Quelle, von Hand gepflegt)
  products.json              ← ERZEUGT: alle Produkte gebündelt
  statuses.json              ← ERZEUGT: Statusstufen
  vocabulary.json            ← ERZEUGT: Anzeigetexte
  brand.json                 ← ERZEUGT: Marke
  news.json                  ← ERZEUGT: Meldungen, Verweise aufgelöst
```

### Warum `vokabular.yaml` nötig wurde

Ein Schlüssel wie `offline-faehig` ist zum Sortieren und Vergleichen ideal — aber nichts,
was ein Besucher lesen soll. Ohne Zuordnung landeten die Schlüssel wörtlich auf der Seite:
„offline faehig", „kein tracking", „github release". Jetzt hat jeder Schlüssel einen
Anzeigetext, und das Prüfskript meldet als **Fehler**, wenn ein benutzter Wert keinen hat.
Die Umlaute können damit nicht mehr verlorengehen, weil sie nicht mehr aus dem Schlüssel
abgeleitet werden.

`tools/build_data.py` liest `src/`, prüft gegen das Schema und schreibt die `.json`-Dateien.

> **Regel:** Dateien ohne `src/` im Pfad werden **nie von Hand bearbeitet**.
> Sie tragen einen Warnhinweis im Kopf und werden bei jedem Lauf überschrieben.

---

## 3. Grundentscheidungen (und warum)

### 3.1 YAML als Quelle, JSON als Ausgabe

YAML lässt Kommentare zu — bei Feldern wie „Preis noch offen" oder „Zahl aus GitHub gerundet"
ist die Begründung genauso wichtig wie der Wert. JSON kann das nicht. Umgekehrt kann JSON
jede Website und jede App direkt lesen, YAML nicht. Deshalb beides: pflegen in YAML,
ausliefern als JSON.

### 3.2 Status gehört an die Plattform, nicht ans Produkt

Der wichtigste Unterschied zum ersten Entwurf im Gesamtkonzept. Dort hatte jedes Produkt
**einen** Status. Die Realität sieht anders aus:

- **OrgaFuchs** ist für Windows verfügbar und für Android noch nicht.
- **PDFuchs** ist für Windows in Entwicklung, für Android nur geplant.
- **CheckInVita** ist auf beiden Plattformen geplant.

Ein einzelner Produktstatus zwingt hier zur Lüge in die eine oder andere Richtung. Deshalb:
Der Status steht **je Plattform**. Der Produktstatus (`status`) wird daraus **abgeleitet** —
es gewinnt die am weitesten fortgeschrittene Plattform. Das Skript prüft das und meldet
Abweichungen; es überschreibt nichts stillschweigend.

### 3.3 Größen und Prüfsummen gehören ins Modell

Downloadvertrauen entsteht durch Nachprüfbarkeit. Wer eine unsignierte `.exe` herunterlädt
und dabei eine SHA-256-Summe zum Abgleich bekommt, kann selbst feststellen, ob die Datei
unterwegs verändert wurde. Die Summen stehen deshalb im Modell und werden auf der
Downloadseite ausgegeben — nicht als Zierde, sondern als Ersatz für die fehlende Signatur.

### 3.4 Preise sind ein Objekt, kein Text

„5,00 € · kein Abo", „Preis noch offen", „ab 50 € gestaffelt", „dauerhaft kostenlos" —
als Fließtext ist davon nichts vergleich- oder filterbar. Als strukturiertes Objekt mit
`model`, `amount` und `currency` schon.

---

## 4. Kontrollierte Vokabulare

### 4.1 Statusstufen

Reihenfolge = Fortschritt. `order` bestimmt, welcher Plattformstatus den Produktstatus gewinnt
(kleinste Zahl gewinnt).

| Wert | Label | order | erlaubte CTA | Bedeutung |
|---|---|---|---|---|
| `verfuegbar` | Verfügbar | 1 | `download`, `kauf` | Öffentlich nutzbar, regulär veröffentlicht |
| `pruefung` | In Store-Prüfung | 2 | `keine` | Eingereicht, Freigabe steht aus |
| `beta` | Offene Beta | 3 | `download`, `beta-anmeldung` | Öffentlich testbar, nicht endgültig |
| `alpha` | Geschlossene Alpha | 4 | `beta-anmeldung` | Nur ausgewählte Tester |
| `entwicklung` | In Entwicklung | 5 | `interesse` | Wird aktiv gebaut, kein Termin zugesagt |
| `konzept` | In Planung | 6 | `interesse` | Konzipiert, Umsetzung noch nicht begonnen |
| `idee` | Idee | 7 | `keine` | Gesammelt, nicht bewertet |
| `pausiert` | Pausiert | 8 | `keine` | Arbeit ruht, Wiederaufnahme offen |
| `eingestellt` | Eingestellt | 9 | `keine` | Endgültig beendet |

> **Abweichung vom Gesamtkonzept:** Die Stufe `pruefung` kam hinzu. Grund: SnapFuchs liegt
> bei Google zur Prüfung. Weder `beta` (nichts ist testbar) noch `verfuegbar` (noch nicht
> freigegeben) trifft zu. Ohne eigene Stufe müsste die Seite raten.

### 4.2 Plattformen

`windows` · `android` · `ios` · `linux` · `macos` · `web`

### 4.3 Vertriebswege (`distribution`)

| Wert | Bedeutung |
|---|---|
| `play-store` | Google Play |
| `github-release` | Direkter Download aus einem GitHub-Release |
| `digistore24` | Kauf über Digistore24 (Zahlungsabwickler, Reseller/MoR) |
| `auf-anfrage` | Kein Selbstbedienungsweg, Kontakt nötig |
| `keiner` | Noch kein Vertriebsweg |

### 4.4 Preismodelle (`price.model`)

| Wert | Pflichtfelder | Beispiel |
|---|---|---|
| `kostenlos` | — | PDFuchs Reader |
| `einmalig` | `amount`, `currency` | GewerbePro Pro (Betrag noch offen) |
| `iap` | `amount`, `currency` | MobileReport Pro, 5,00 € |
| `staffel` | `tiers[]` | MobileReport Enterprise |
| `auf-anfrage` | — | Custom-Branding |
| `offen` | — | Preis noch nicht festgelegt |

### 4.5 Datenschutz-Merkmale (`privacy`)

`nur-lokal` · `keine-cloud` · `kein-konto` · `kein-tracking` · `werbefrei` · `kein-google` ·
`eigener-sync` · `offline-faehig`

Diese Liste speist später die produktbezogenen Abschnitte der Datenschutzerklärung. Ein
Merkmal darf nur gesetzt werden, wenn es **uneingeschränkt** zutrifft.

### 4.6 Produktart (`kind`)

| Wert | Bedeutung |
|---|---|
| `produkt` | Eigenständige App oder Programm |
| `edition` | Eigenständig vermarktete Ausbaustufe eines Produkts (z. B. Enterprise) |
| `werkzeug` | Kostenloses Zubehör zu einem Produkt (z. B. Branding-Konfigurator) |
| `dienstleistung` | Gibt es nicht fertig — wird auf Bestellung gebaut (Individuelle Anwendung) |

Bei einer `dienstleistung` beschreiben die `platforms[]` nicht, **wo es etwas gibt**,
sondern **was gebaut werden kann**; `distribution` ist dort immer `auf-anfrage`. Die
Prüfung weiß das: Sie verlangt bei einer Dienstleistung weder Release noch Store-Link,
obwohl der Status `verfuegbar` ist — verfügbar ist hier die Leistung, nicht eine Datei.

Auf der **Startseite** zählt eine Dienstleistung bewusst nicht mit („3 Helfer, die du
heute nutzen kannst" wäre gelogen, wenn einer davon erst gebaut werden muss). Dafür gibt
es `nutzbareProdukte` neben `hauptprodukte`.

Die Produktübersicht zeigt alles mit `kind: produkt` und `kind: dienstleistung` —
**und zusätzlich alles mit `standalone: true`**. Diese Unterscheidung war nötig, weil MobileReport Enterprise
fachlich eine Ausbaustufe ist, wirtschaftlich aber ein eigenes Produkt: eigener Preis,
eigener Download, eigener Kaufweg. Ohne das Kennzeichen wäre es aus der Übersicht
verschwunden, obwohl es das einzige Produkt mit Lizenzverkauf ist.

Faustregel: **Kann man es einzeln kaufen oder herunterladen, ohne das Hauptprodukt zu
haben? Dann `standalone: true`.** Der Branding-Konfigurator ist ohne Enterprise nutzlos
und bleibt deshalb draußen.

---

## 5. Feldreferenz

### 5.1 Wurzelebene

| Feld | Typ | Pflicht | Beschreibung |
|---|---|---|---|
| `slug` | string | ja | Kleinbuchstaben, Ziffern, Bindestrich. Bestimmt Dateiname und URL. |
| `name` | string | ja | Kurzname, wie im Fließtext („GewerbePro") |
| `fullName` | string | ja | Vollständiger Name mit Marke („FehlerFuchs GewerbePro") |
| `kind` | enum | ja | siehe 4.6 |
| `standalone` | bool | nein | Nur bei `edition`/`werkzeug`: erscheint trotzdem in der Produktübersicht |
| `parent` | slug | nein | Nur bei `edition`/`werkzeug`: zugehöriges Hauptprodukt |
| `tagline` | string | ja | Ein Satz, max. 200 Zeichen. Die Kernaussage. |
| `description` | string | ja | 2–4 Sätze für Meta-Description und Produktkarte |
| `audience` | string[] | ja | `privat` · `selbststaendige` · `unternehmen` · `vereine` |
| `accent` | string | ja | Akzentfarbe als Hex. Muss zur Produktseite passen. |
| `status` | enum | ja | Abgeleitet aus `platforms[].status` (siehe 3.2) |
| `platforms` | object[] | ja | mindestens ein Eintrag |
| `privacy` | string[] | ja | siehe 4.5 |
| `editions` | object[] | nein | Ausbaustufen innerhalb des Produkts |
| `releases` | object[] | nein | Veröffentlichte Fassungen, neueste zuerst |
| `features` | object[] | nein | Merkmalsmatrix, siehe 5.6 |
| `faq` | object[] | nein | Häufige Fragen, siehe 5.7 |
| `media` | object | nein | Wortmarke, OG-Bild, Bildschirmfotos, siehe 5.8 |
| `links` | object | ja | siehe 5.5 |
| `manifests` | object | nein | Pfade zu Update-Manifesten |
| `notes` | string | nein | Interne Anmerkung, wird **nicht** ausgegeben |

### 5.2 `platforms[]`

| Feld | Typ | Pflicht | Beschreibung |
|---|---|---|---|
| `os` | enum | ja | siehe 4.2 |
| `status` | enum | ja | siehe 4.1 |
| `requirements` | string | nein | z. B. „Windows 10/11 (64-bit)" |
| `distribution` | enum | ja | siehe 4.3 |
| `storeId` | string | nein | Play-Store-Paketname |
| `since` | date | nein | Datum der ersten Verfügbarkeit auf dieser Plattform |

### 5.3 `editions[]`

| Feld | Typ | Pflicht | Beschreibung |
|---|---|---|---|
| `id` | string | ja | `free`, `pro`, `enterprise`, … |
| `name` | string | ja | Anzeigename |
| `public` | bool | ja | `false` = intern, wird nirgends ausgegeben |
| `price` | object | ja | siehe 4.4 |
| `summary` | string | nein | Ein Satz zur Abgrenzung |
| `wordmark` | object[] | nein | Wortmarke in farbigen Teilen, für Tabellenüberschriften |
| `emphasis` | bool | nein | Diese Spalte wird in der Merkmalsmatrix hervorgehoben |

`wordmark` zerlegt den Namen in Textstücke mit eigener Farbe und Stärke:

```yaml
wordmark:
  - { text: "FehlerFuchs ", color: "#7C3F16", weight: normal }
  - { text: "Gewerbe",      color: "#B45309", weight: bold }
  - { text: "Pro",          color: "#7C3F16", weight: bold }
```

Ohne dieses Feld wird schlicht `name` gesetzt. Es ist also nur nötig, wo die Marke
tatsächlich mehrfarbig gesetzt wird.

### 5.4 `releases[]`

| Feld | Typ | Pflicht | Beschreibung |
|---|---|---|---|
| `version` | string | ja | Semantisch, ohne führendes „v" |
| `date` | date | ja | Veröffentlichungsdatum (ISO) |
| `channel` | enum | ja | `stable` · `beta` · `alpha` |
| `os` | enum | ja | Plattform dieses Artefakts |
| `url` | url | ja | Direkter Downloadlink |
| `filename` | string | ja | Dateiname des Artefakts |
| `size.bytes` | int\|null | ja | Exakte Größe. `null` erlaubt, wenn nur gerundet bekannt. |
| `size.label` | string | ja | Anzeigetext, z. B. „114 MB" |
| `size.source` | string | ja | Woher die Angabe stammt |
| `sha256` | string\|null | ja | Prüfsumme zum Selbstabgleich |
| `signed` | bool | ja | Code-signiert? Steuert den SmartScreen-Hinweis. |
| `notes` | string | nein | Kurzfassung der Änderungen |

### 5.5 `links`

| Feld | Pflicht | Beschreibung |
|---|---|---|
| `page` | ja | Produktseite auf fehlerfuchs.eu |
| `store` | nein | Store-Eintrag |
| `release` | nein | GitHub-Release-Übersicht |
| `betaSignup` | nein | Endpunkt der Tester-Registrierung |
| `checkout` | nein | Kaufweg |
| `contact` | nein | Vorbelegtes Kontaktformular |

### 5.6 `features[]` — die Merkmalsmatrix

```yaml
features:
  - group: Rechnung und Zahlung
    items:
      - name: E-Rechnung erstellen, prüfen und versenden
        values: { free: nein, pro: ja, vather: ja }
      - name: OCR für Belege
        values: { free: nein, pro: optional, vather: ja }
        note: Wird als Zusatzpaket installiert.
```

Die Schlüssel unter `values` sind **Editions-IDs**. Das Prüfskript vergleicht sie mit
`editions[].id` und meldet sowohl erfundene Spalten als auch fehlende Werte — eine Lücke
in der Tabelle ist damit nicht mehr möglich.

**Erlaubte Werte:** `ja` · `nein` · `optional` · `teilweise` · `geplant` · `in-arbeit` ·
`in-vorbereitung` — oder freier Text (bis 60 Zeichen) für Fälle wie „Export + Logo".

> **Was hier nicht hineingehört:** Die alte HTML-Tabelle hatte zwei Zeilen „Verfügbarkeit /
> Preis" und „Download / Kauf". Das sind keine Merkmale, sondern ergeben sich aus
> `editions[].price` und `releases[]`. Als Tabellenzeilen wären es Duplikate, die
> auseinanderlaufen können — genau das, was dieses Modell verhindern soll.

**Interne Editionen erscheinen nicht.** Die Matrix zeigt nur Spalten mit `public: true`.
Die Entwicklerfassung „Vather" steht vollständig im Modell, taucht aber auf keiner
öffentlichen Seite auf.

#### Spalten für eigenständige Ausbaustufen

Eine Spalte darf statt einer Editions-ID auch der **slug einer Ausbaustufe** sein, die
`parent` auf dieses Produkt setzt und `standalone: true` trägt:

```yaml
values: { free: nein, pro: ja, mobilereport-enterprise: ja }
```

Enterprise ist fachlich ein eigenes Produkt, aus Käufersicht aber schlicht die dritte
Stufe derselben App. Ihn für den Vergleich auf eine andere Seite zu schicken, hieße den
Vergleich zu zerreißen, den er gerade anstellt.

**Die Matrix existiert dabei nur einmal — beim Elternprodukt.** Beide Seiten zeigen
dieselbe Tabelle aus unterschiedlicher Blickrichtung:

| Seite | Was sie zeigt |
|---|---|
| `/produkte/mobilereport/` | eigene Editionen, Enterprise als dritte Spalte mit Verweis |
| `/produkte/mobilereport-enterprise/` | dieselbe Tabelle, die eigene Spalte hervorgehoben |

Die Ausbaustufe braucht dafür **kein eigenes `features`**. Hätte sie eines, würde
derselbe Vergleich an zwei Stellen gepflegt — und genau das soll dieses Modell abschaffen.

#### Wann eine Matrix Pflicht ist

**Grundregel: keine Produktseite ohne Merkmalstabelle.** Ohne sie steht dort Fließtext und
eine Preisangabe — der Besucher müsste aus Prosa herauslesen, was das Ding eigentlich kann.
Eine Spalte genügt; die Seite macht daraus eine **Funktionsübersicht** („Was es kann")
statt eines Vergleichs.

| Lage | Stufe |
|---|---|
| Produkt ist öffentlich nutzbar (`verfuegbar`, `pruefung`, `beta`) und hat kein `features` | **Fehler** |
| Produkt ist noch in Arbeit (`entwicklung` und tiefer) und hat kein `features` | Warnung |
| `customPage: true` | keine Prüfung — dort *ist* die Seite das Werkzeug |
| Ausbaustufe, die die Matrix des Elternprodukts mitbenutzt | keine Prüfung — die Tabelle steht dort einmal |

Zusätzlich: Stehen eine **kostenlose und eine kostenpflichtige** Edition öffentlich
nebeneinander, ohne dass `features` vorhanden ist, sagt die Meldung ausdrücklich, dass die
Seite nicht zeigen kann, wofür der Besucher zahlen soll. Zwei Bezahlstufen, die sich nur in
der Betreuung unterscheiden (Enterprise: selbst branden oder branden lassen), sind mit
ihren `summary`-Zeilen ausreichend erklärt.

### 5.7 `faq[]`

| Feld | Pflicht | Regel |
|---|---|---|
| `question` | ja | Muss auf ein Fragezeichen enden |
| `answer` | ja | 20–1200 Zeichen |

FAQ-Antworten veralten schneller als jeder andere Inhalt. Zwei Regeln greifen deshalb:

- Nennt eine Antwort eine **Versionsnummer**, die es in `releases[]` nicht gibt, warnt das
  Skript.
- Nennt eine Antwort ein **festes Datum** (`01.08.2026`), warnt es ebenfalls.

Genau dieser Fehler ist schon passiert: Eine FAQ kündigte ein Datum an, das durch ein
Release längst überholt war, und stand monatelang falsch auf der Seite.

### 5.8 `media`

```yaml
media:
  lockup:      { src: /img/lockups/orgafuchs.png, alt: "…", width: 1040, height: 400 }
  og:          { src: /img/…, alt: "…", width: 1200, height: 630 }
  screenshots: [ { src: …, alt: …, width: …, height: …, caption: … } ]
```

`width` und `height` sind Pflicht, damit der Browser den Platz reservieren kann und die
Seite beim Laden nicht springt. Das Prüfskript stellt sicher, dass jede angegebene Datei
tatsächlich existiert — ein toter Bildpfad fällt beim Bauen auf, nicht erst beim Besucher.

---

## 6. Abgeleitete Artefakte

| Artefakt | Quelle | Stand |
|---|---|---|
| `updates/<slug>/latest.json` | neuestes Release im passenden Kanal | **erzeugt** |
| `enterprise/latest.json` | MobileReport-Enterprise-Release | **erzeugt** |
| `versions.json` (Up2Date) | alle Produkte mit Release | **erzeugt**, Schema noch abzustimmen |
| Produktseiten, Produktkarten, Filter | `products[]` | vorbereitet |
| Downloadseite inkl. Version/Datum/Größe/Prüfsumme | `products[].releases` | vorbereitet |
| `sitemap.xml` | `links.page` | vorbereitet |
| JSON-LD `SoftwareApplication` | Produkt + Preis + Plattform | vorbereitet |
| Datenschutz-Produktabschnitte | `privacy` + Plattformangaben | vorbereitet |

### Manifeste, die ausgelieferte Apps lesen

Drei Dateien werden nicht von der Website gelesen, sondern von installierten Programmen:

| Datei | Leser | Ausgewertete Felder |
|---|---|---|
| `updates/gewerbepro/latest.json` | GewerbePro In-App-Updater | `version`, `download_url`, `notes` |
| `enterprise/latest.json` | MobileReport Enterprise | `version`, `apkUrl`, `notes` |
| `versions.json` | Up2Date | noch abzustimmen |

Für diese gilt: **Pfad und Feldnamen sind fest verdrahtet und dürfen sich nicht ändern.**
`notes` erscheint wörtlich im Update-Hinweis der App — eine Änderung dieses Textes im
YAML ändert unmittelbar, was Nutzer zu sehen bekommen.

---

## 7. Arbeitsablauf

```
1. YAML unter data/src/ bearbeiten
2. python tools/build_data.py            → prüft und erzeugt data/*.json
3. python tools/build_manifests.py       → Trockenlauf: zeigt, was sich an den
                                           App-Manifesten ändern würde
4. Abweichungen prüfen, dann:
   python tools/build_manifests.py --write
5. Änderungen committen (Quellen UND erzeugte Dateien)
```

Der Trockenlauf in Schritt 3 ist Absicht. Diese Dateien erreichen Nutzer ohne Umweg über
die Website — ein falscher Wert wird sofort ausgeliefert. Deshalb wird jede Abweichung
erst gezeigt und muss bewusst bestätigt werden.

**Reihenfolge beim Veröffentlichen:** erst den GitHub-Release anlegen, dann die Website
pushen. Andersherum zeigen die Downloadlinks vorübergehend ins Leere.

Das Skript kennt drei Meldungsarten:

- **FEHLER** — Schemaverstoß. Erzeugung bricht ab.
- **WARNUNG** — inhaltlich fragwürdig (fehlende Prüfsumme, Preis offen). Erzeugung läuft weiter.
- **ABGLEICH** — Wert weicht von dem ab, was auf der bestehenden Website steht.
  Das ist kein Fehler im Modell, sondern ein Hinweis, dass eine der beiden Seiten veraltet ist.

---

## 8. Meldungen (Aktuelles)

`src/meldungen.yaml`, geprüft gegen `schema/meldung.schema.json`.

### Der Grundsatz

> Eine Meldung wiederholt keine Tatsache, die schon beim Produkt steht.

Version, Datum, Download-Adresse, Store-Link und Produktname kommen aus
`src/products/*.yaml`. In der Meldung stehen nur Überschrift und Wortlaut — also
genau das, was es sonst nirgends gibt.

Das ist keine Sparsamkeit um ihrer selbst willen. Der Ausgangspunkt des ganzen
Datenmodells war eine Startseite, auf der „Beta pausiert" stand, während die Beta lief:
dieselbe Aussage an zwei Stellen, eine davon vergessen. Ein Datum, das nur einmal
existiert, kann sich nicht widersprechen.

### Woher das Datum kommt

Die Reihenfolge der Wahrheit ist festgelegt:

| Fall | Quelle des Datums |
|---|---|
| `version` verweist auf einen Release | `releases[].date` |
| `typ: store` und genau eine Plattform hat `since` | `platforms[].since` |
| sonst | `datum` in der Meldung selbst |

Steht ein `datum` zusätzlich in der Meldung und weicht ab, ist das ein **Fehler** —
nicht ein stillschweigender Vorrang. Denn beide Angaben beschreiben dasselbe Ereignis,
also ist eine von beiden schlicht falsch, und welche das ist, kann nur ein Mensch wissen.

### Feldreferenz

| Feld | Pflicht | Bedeutung |
|---|---|---|
| `id` | ja | Sprungziel (`/aktuelles/#id`). **Ändert sich nie** — sonst brechen geteilte Links. |
| `typ` | ja | `veroeffentlichung`, `update`, `store`, `test`, `hinweis` |
| `produkt` | nein | slug. Fehlt er, ist es eine Meldung ohne Produktbezug. |
| `version` | nein | Verweis auf einen Release-Eintrag des Produkts |
| `datum` | bedingt | nur nötig, wenn es sich nicht ableiten lässt |
| `titel` | ja | 8–90 Zeichen |
| `text` | ja | 40–700 Zeichen, zwei bis vier Sätze in normaler Sprache |
| `ziel` | nein | zusätzlicher Weg, der sich **nicht** aus dem Produkt ergibt |

### Prüfregeln

| Regel | Stufe |
|---|---|
| `produkt` und `version` existieren im Modell | Fehler |
| `datum` widerspricht Release oder `since` nicht | Fehler |
| Versionsnummer im Titel passt zur verwiesenen Version | Fehler |
| `id` ist eindeutig | Fehler |
| **jeder Release hat eine Meldung** | Warnung |
| `ziel.url` wiederholt keinen automatischen Weg | Warnung |
| kein `https://` im Fließtext | Warnung |
| Datum liegt nicht in der Zukunft | Warnung |

Die fett gesetzte Regel ist der eigentliche Zweck: Wer etwas veröffentlicht, ohne es zu
erzählen, hat es für die Besucher nicht veröffentlicht.

### Was `news.json` zusätzlich enthält

Die Auflösung passiert beim Erzeugen, nicht in der Website — damit jeder Verbraucher
der Daten dieselben Werte sieht:

- `datum` — aufgelöst
- `datumQuelle` — woher es stammt (nachvollziehbar, ohne ins YAML zu schauen)
- `wege` — `download`, `store`, `kauf`, sofern das Produkt sie hat
