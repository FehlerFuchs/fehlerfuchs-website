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
  src/statuses.yaml          ← Statusstufen: Label, Farbe, erlaubte CTA
  src/products/<slug>.yaml   ← je Produkt eine Datei (Quelle, von Hand gepflegt)
  products.json              ← ERZEUGT: alle Produkte gebündelt
  statuses.json              ← ERZEUGT: Statusstufen
```

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

---

## 5. Feldreferenz

### 5.1 Wurzelebene

| Feld | Typ | Pflicht | Beschreibung |
|---|---|---|---|
| `slug` | string | ja | Kleinbuchstaben, Ziffern, Bindestrich. Bestimmt Dateiname und URL. |
| `name` | string | ja | Kurzname, wie im Fließtext („GewerbePro") |
| `fullName` | string | ja | Vollständiger Name mit Marke („FehlerFuchs GewerbePro") |
| `kind` | enum | ja | siehe 4.6 |
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

---

## 6. Abgeleitete Artefakte

Aus diesen Daten lassen sich erzeugen — heute noch nicht umgesetzt, aber vorbereitet:

| Artefakt | Quelle |
|---|---|
| Produktseiten, Produktkarten, Filter | `products[]` |
| Downloadseite inkl. Version/Datum/Größe/Prüfsumme | `products[].releases` |
| `updates/<slug>/latest.json` | neuestes Release im passenden Kanal |
| `enterprise/latest.json` | MobileReport-Enterprise-Release |
| `versions.json` (Up2Date) | alle Produkte mit Release |
| `sitemap.xml` | `links.page` |
| JSON-LD `SoftwareApplication` | Produkt + Preis + Plattform |
| Datenschutz-Produktabschnitte | `privacy` + Plattformangaben |

---

## 7. Arbeitsablauf

```
1. YAML unter data/src/ bearbeiten
2. python tools/build_data.py         → prüft und erzeugt die JSON-Dateien
3. Bei Meldungen: Ursache beheben, nicht die Meldung abschalten
4. Änderungen committen (Quelle UND erzeugte Dateien)
```

Das Skript kennt drei Meldungsarten:

- **FEHLER** — Schemaverstoß. Erzeugung bricht ab.
- **WARNUNG** — inhaltlich fragwürdig (fehlende Prüfsumme, Preis offen). Erzeugung läuft weiter.
- **ABGLEICH** — Wert weicht von dem ab, was auf der bestehenden Website steht.
  Das ist kein Fehler im Modell, sondern ein Hinweis, dass eine der beiden Seiten veraltet ist.
