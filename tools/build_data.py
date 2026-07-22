#!/usr/bin/env python3
"""
FehlerFuchs — Datenmodell prüfen und ausliefern.

Liest die YAML-Quellen unter data/src/, prüft sie gegen data/schema/product.schema.json,
gleicht sie mit der bestehenden Website ab und schreibt data/products.json und
data/statuses.json.

Aufruf (aus dem Ordner website/):
    python tools/build_data.py            # prüfen und erzeugen
    python tools/build_data.py --check    # nur prüfen, nichts schreiben

Rückgabewert: 0 = in Ordnung, 1 = Fehler gefunden (nichts geschrieben).

Abhängigkeiten: PyYAML. jsonschema ist optional – fehlt es, greift eine eingebaute
Minimalprüfung, die alle im Schema verwendeten Konstrukte abdeckt.
"""

import hashlib
import pathlib
import random
import json
import re
import struct
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("FEHLER: PyYAML fehlt.  Installation:  pip install pyyaml")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "src"
SCHEMA_FILE = ROOT / "data" / "schema" / "product.schema.json"
MELDUNG_SCHEMA_FILE = ROOT / "data" / "schema" / "meldung.schema.json"
OUT_PRODUCTS = ROOT / "data" / "products.json"
OUT_NEWS = ROOT / "data" / "news.json"
OUT_WUENSCHE = ROOT / "data" / "wishes.json"
OUT_DIENSTE = ROOT / "data" / "services.json"
OUT_DATENSCHUTZ = ROOT / "data" / "privacy.json"
WUNSCH_SCHEMA_FILE = ROOT / "data" / "schema" / "wunsch.schema.json"
OUT_STATUSES = ROOT / "data" / "statuses.json"
OUT_VOKABULAR = ROOT / "data" / "vocabulary.json"
OUT_MARKE = ROOT / "data" / "brand.json"
OUT_BEDARF = ROOT / "data" / "needs.json"
OUT_AKTIONEN = ROOT / "data" / "campaigns.json"

fehler, warnungen, abgleich = [], [], []


def bildmasse(pfad):
    """Echte Maße aus der Datei lesen – PNG und JPEG, ohne Zusatzpaket.
    Falsche Maße im Modell führen zu verzerrten oder falsch beschnittenen
    Bildern; das fällt sonst erst dem Besucher auf."""
    d = pfad.read_bytes()
    if d[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", d[16:24])
    if d[:2] == b"\xff\xd8":
        i = 2
        while i < len(d) - 9:
            if d[i] != 0xFF:
                i += 1
                continue
            m = d[i + 1]
            if m in (0xC0, 0xC1, 0xC2, 0xC3):
                h, w = struct.unpack(">HH", d[i + 5:i + 9])
                return (w, h)
            if m in (0xD8, 0xD9) or 0xD0 <= m <= 0xD7:
                i += 2
                continue
            i += 2 + struct.unpack(">H", d[i + 2:i + 4])[0]
    return None


# Die einzigen zwei Schriften der Marke. Steht so im Markenkonzept
# (_Marke_und_IP\MARKENKONZEPT.md, Abschnitt 3) und ist dort ausdrücklich
# abschließend: keine Ersatzschriften, auch nicht „nur diesmal".
MARKENSCHRIFTEN = {"poppins", "inter"}

# Generische Angaben sind keine Schriftwahl, sondern der Notnagel dahinter.
# Sie allein sind kein Verstoß – nur wenn sie als EINZIGES dastehen, fehlt
# eine echte Angabe, und das meldet die Prüfung ohnehin als „ohne Schriftangabe".
GENERISCH = {"sans-serif", "serif", "monospace", "system-ui", "ui-sans-serif",
             "-apple-system", "blinkmacsystemfont", "segoe ui"}


def schriften_im_svg(inhalt):
    """Alle font-family-Angaben einer SVG – und welche davon fremd sind.

    Gibt (alle, fremde) zurück. 'fremd' meint: weder Poppins noch Inter noch
    ein generischer Notnagel. Genau diese Liste entscheidet zwischen Warnung
    und Fehler.
    """
    roh = re.findall(r"font-family\s*[:=]\s*[\"']?([^;\"'>]+)", inhalt)
    einzeln = []
    for angabe in roh:
        # 'Poppins, Arial, sans-serif' sind drei Angaben, nicht eine. Die
        # zweite ist der Fall, um den es geht: Sie greift bei jedem Besucher
        # ohne Poppins – also bei fast allen.
        for teil in angabe.split(","):
            name = teil.strip().strip("\"'")
            if name:
                einzeln.append(name)
    alle = sorted(set(einzeln), key=str.lower)
    fremd = sorted({n for n in alle
                    if n.lower() not in MARKENSCHRIFTEN and n.lower() not in GENERISCH},
                   key=str.lower)
    return alle, fremd


def melde(liste, slug, text):
    liste.append(f"{slug}: {text}")


# ------------------------------------------------------------------ Kontrast

def leuchtkraft(hex_farbe):
    """Relative Helligkeit nach WCAG. Nicht die naive Mittelung der drei Kanäle:
    Das Auge sieht Grün viel heller als Blau, deshalb die Gewichtung."""
    r, g, b = (int(hex_farbe[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def linear(k):
        return k / 12.92 if k <= 0.03928 else ((k + 0.055) / 1.055) ** 2.4

    return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)


def kontrast(a, b):
    """Kontrastverhältnis zweier Farben, 1 (gleich) bis 21 (Schwarz auf Weiß).
    Ab 4,5 gilt Fließtext als lesbar, ab 3,0 große Schrift.

    Warum das hier steht und nicht im Kopf: Die Werte lassen sich nicht
    schätzen. #B8912F auf Weiß sieht kräftig aus und liegt trotzdem bei 3,0 –
    unter der Schwelle. Genau dieser Irrtum wäre uns beim Gold des EinzelStücks
    fast durchgegangen."""
    la, lb = leuchtkraft(a), leuchtkraft(b)
    hell, dunkel = max(la, lb), min(la, lb)
    return round((hell + 0.05) / (dunkel + 0.05), 2)


# ---------------------------------------------------------------- Schemaprüfung

def pruefe_gegen_schema(daten, schema, pfad, slug, defs=None):
    """Kleine, vollständige Prüfung für genau die Konstrukte, die unser Schema nutzt."""
    defs = defs if defs is not None else schema.get("$defs", {})

    if "$ref" in schema:
        ziel = schema["$ref"].split("/")[-1]
        return pruefe_gegen_schema(daten, defs[ziel], pfad, slug, defs)

    if "enum" in schema:
        if daten not in schema["enum"]:
            melde(fehler, slug, f"{pfad}: {daten!r} ist kein erlaubter Wert "
                                f"(erlaubt: {', '.join(map(str, schema['enum']))})")
        return

    typ = schema.get("type")
    typen = typ if isinstance(typ, list) else [typ] if typ else []

    def passt(t):
        return {
            "object": isinstance(daten, dict),
            "array": isinstance(daten, list),
            "string": isinstance(daten, str),
            "integer": isinstance(daten, int) and not isinstance(daten, bool),
            "number": isinstance(daten, (int, float)) and not isinstance(daten, bool),
            "boolean": isinstance(daten, bool),
            "null": daten is None,
        }.get(t, True)

    if typen and not any(passt(t) for t in typen):
        melde(fehler, slug, f"{pfad}: erwartet {'/'.join(typen)}, ist {type(daten).__name__}")
        return

    if daten is None:
        return

    if isinstance(daten, str):
        if "pattern" in schema and not re.search(schema["pattern"], daten):
            melde(fehler, slug, f"{pfad}: {daten!r} passt nicht zum Muster {schema['pattern']}")
        if "minLength" in schema and len(daten) < schema["minLength"]:
            melde(fehler, slug, f"{pfad}: zu kurz ({len(daten)} < {schema['minLength']} Zeichen)")
        if "maxLength" in schema and len(daten) > schema["maxLength"]:
            melde(fehler, slug, f"{pfad}: zu lang ({len(daten)} > {schema['maxLength']} Zeichen)")

    if isinstance(daten, (int, float)) and not isinstance(daten, bool):
        if "minimum" in schema and daten < schema["minimum"]:
            melde(fehler, slug, f"{pfad}: {daten} unter Minimum {schema['minimum']}")
        if "maximum" in schema and daten > schema["maximum"]:
            melde(fehler, slug, f"{pfad}: {daten} über Maximum {schema['maximum']}")

    if isinstance(daten, dict):
        for pflicht in schema.get("required", []):
            if pflicht not in daten:
                melde(fehler, slug, f"{pfad}: Pflichtfeld '{pflicht}' fehlt")
        eigenschaften = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for k in daten:
                if k not in eigenschaften:
                    melde(fehler, slug, f"{pfad}: unbekanntes Feld '{k}'")
        for k, v in daten.items():
            if k in eigenschaften:
                pruefe_gegen_schema(v, eigenschaften[k], f"{pfad}.{k}" if pfad else k, slug, defs)

    if isinstance(daten, list):
        if "minItems" in schema and len(daten) < schema["minItems"]:
            melde(fehler, slug, f"{pfad}: mindestens {schema['minItems']} Eintrag/Einträge nötig")
        if schema.get("uniqueItems") and len(daten) != len({json.dumps(x, sort_keys=True) for x in daten}):
            melde(fehler, slug, f"{pfad}: enthält Dubletten")
        if "items" in schema:
            for i, v in enumerate(daten):
                pruefe_gegen_schema(v, schema["items"], f"{pfad}[{i}]", slug, defs)


# ------------------------------------------------------------- Inhaltliche Regeln

def pruefe_vokabular(p, vok):
    """Jeder benutzte Schlüssel braucht einen Anzeigetext – sonst steht der
    technische Schlüssel auf der Seite ('offline faehig', 'github release')."""
    slug = p["slug"]

    def deckt_ab(bereich, wert, wo):
        if wert not in vok.get(bereich, {}):
            melde(fehler, slug, f"{wo}: '{wert}' hat keinen Anzeigetext in "
                                f"vokabular.yaml → {bereich}")

    for m in p.get("privacy", []):
        deckt_ab("privacy", m, "privacy")
    for pl in p["platforms"]:
        deckt_ab("os", pl["os"], f"platforms[{pl['os']}].os")
        deckt_ab("distribution", pl["distribution"], f"platforms[{pl['os']}].distribution")
    for r in p.get("releases", []):
        deckt_ab("os", r["os"], f"releases[{r['version']}].os")
    for g in p.get("features", []):
        for item in g["items"]:
            for wert in item["values"].values():
                # Freitext ist erlaubt; nur die Vokabular-Kurzwörter müssen abgedeckt sein.
                if " " not in wert and wert not in vok.get("featureWerte", {}):
                    melde(warnungen, slug,
                          f"Merkmalswert '{wert}' steht nicht im Vokabular – "
                          f"er wird als freier Text ausgegeben. Tippfehler?")


def pruefe_inhalt(p, statuses, alle_slugs, alle_produkte):
    slug = p["slug"]

    # 1. Gesamtstatus muss der weitesten Plattform entsprechen (siehe SCHEMA.md 3.2)
    beste = min(p["platforms"], key=lambda pl: statuses[pl["status"]]["order"])
    if p["status"] != beste["status"]:
        melde(fehler, slug,
              f"status ist '{p['status']}', die weiteste Plattform ({beste['os']}) "
              f"steht aber auf '{beste['status']}'. Einer von beiden ist falsch.")

    # 2. parent muss existieren und darf nicht auf sich selbst zeigen
    if p.get("parent"):
        if p["parent"] == slug:
            melde(fehler, slug, "parent zeigt auf das eigene Produkt")
        elif p["parent"] not in alle_slugs:
            melde(fehler, slug, f"parent '{p['parent']}' gibt es nicht")
    if p["kind"] in ("edition", "werkzeug") and not p.get("parent"):
        melde(fehler, slug, f"kind '{p['kind']}' verlangt ein parent")
    if p["kind"] == "produkt" and "standalone" in p:
        melde(warnungen, slug, "'standalone' hat bei kind 'produkt' keine Wirkung – "
                               "echte Produkte stehen ohnehin in der Übersicht")
    # Eine Edition mit eigenem Download oder eigenem Kaufweg, die NICHT als
    # standalone gekennzeichnet ist, verschwindet aus der Produktübersicht.
    if p["kind"] == "edition" and not p.get("standalone") \
            and (p.get("releases") or p.get("links", {}).get("checkout")):
        melde(warnungen, slug, "Edition hat einen eigenen Bezugsweg, ist aber nicht als "
                               "'standalone: true' gekennzeichnet – sie taucht in der "
                               "Produktübersicht nicht auf")

    # 3. Dateiname muss zum slug passen
    #    (wird von der aufrufenden Schleife geprüft, siehe unten)

    # 4. Releases: absteigend sortiert, Versionen eindeutig, Datum nicht in der Zukunft
    verz = [r["version"] for r in p.get("releases", [])]
    if len(verz) != len(set(verz)):
        melde(fehler, slug, "mehrere Releases mit derselben Versionsnummer")
    daten_liste = [r["date"] for r in p.get("releases", [])]
    if daten_liste != sorted(daten_liste, reverse=True):
        melde(warnungen, slug, "Releases sind nicht nach Datum absteigend sortiert (neuestes zuerst)")
    for r in p.get("releases", []):
        if datetime.strptime(r["date"], "%Y-%m-%d").date() > date.today():
            melde(fehler, slug, f"Release {r['version']} hat ein Datum in der Zukunft ({r['date']})")
        if r["os"] not in [pl["os"] for pl in p["platforms"]]:
            melde(fehler, slug, f"Release {r['version']} ist für '{r['os']}', "
                                f"diese Plattform ist beim Produkt nicht angelegt")
        # Version muss in Dateiname und URL wiederauftauchen. Sonst zeigt ein
        # hochgesetzter Versionseintrag weiter auf die alte Datei – ein Fehler,
        # den man sonst erst bemerkt, wenn Nutzer das falsche Paket installiert haben.
        if r["version"] not in r["filename"]:
            melde(fehler, slug, f"Release {r['version']}: Dateiname '{r['filename']}' "
                                f"enthält die Versionsnummer nicht")
        if r["version"] not in r["url"]:
            melde(fehler, slug, f"Release {r['version']}: die URL zeigt nicht auf diese Version "
                                f"({r['url'].rsplit('/', 1)[-1]})")
        if r["sha256"] is None:
            melde(warnungen, slug, f"Release {r['version']}: keine SHA-256-Summe – "
                                   f"Nutzer können den Download nicht selbst prüfen")
        if r["size"]["bytes"] is None:
            melde(warnungen, slug, f"Release {r['version']}: exakte Dateigröße nicht erfasst "
                                   f"(nur '{r['size']['label']}')")
        if not r["signed"] and r["os"] == "windows":
            melde(warnungen, slug, f"Release {r['version']}: nicht signiert – "
                                   f"SmartScreen-Hinweis auf der Seite ist Pflicht")

    # 5. Status verlangt bzw. verbietet bestimmte Wege
    st = statuses[p["status"]]
    hat_download = bool(p.get("releases")) or any(
        pl.get("distribution") == "play-store" and pl["status"] == "verfuegbar"
        for pl in p["platforms"])
    # Reine Web-Werkzeuge laufen im Browser – sie brauchen weder Release noch Store.
    nur_web = all(pl["os"] == "web" for pl in p["platforms"])
    # Eine Dienstleistung ist verfügbar, ohne dass es etwas herunterzuladen gäbe:
    # Sie entsteht erst auf Bestellung. Ihre platforms[] sagen nicht „hier gibt es
    # das", sondern „so etwas kann gebaut werden".
    if "download" in st["cta"] and not hat_download and not nur_web \
            and p["kind"] != "dienstleistung" \
            and not p.get("links", {}).get("store"):
        melde(warnungen, slug, f"Status '{p['status']}' erlaubt einen Download, "
                               f"es ist aber weder ein Release noch ein Store-Link hinterlegt")
    if st["cta"] == ["keine"] and p.get("releases"):
        melde(warnungen, slug, f"Status '{p['status']}' erlaubt keine Download-CTA, "
                               f"es sind aber Releases hinterlegt")

    # 5b. Merkmalsmatrix: Spalten müssen zu den Editionen passen
    editions_ids = {e["id"] for e in p.get("editions", [])}
    oeffentliche = {e["id"] for e in p.get("editions", []) if e["public"]}

    # Eine Ausbaustufe, die als eigenes Produkt geführt wird (parent + standalone),
    # darf ebenfalls eine Spalte bekommen. Aus Sicht eines Käufers ist sie die
    # dritte Stufe derselben App – ihn dafür auf eine andere Seite zu schicken,
    # hieße den Vergleich zu zerreißen, den er gerade anstellt.
    kinder = {k["slug"] for k in alle_produkte
              if k.get("parent") == slug and k.get("standalone")}
    erlaubte_spalten = editions_ids | kinder

    namen_gesehen = set()
    for gruppe in p.get("features", []):
        for item in gruppe["items"]:
            if item["name"] in namen_gesehen:
                melde(warnungen, slug, f"Merkmal '{item['name']}' kommt mehrfach vor")
            namen_gesehen.add(item["name"])
            unbekannt = set(item["values"]) - erlaubte_spalten
            if unbekannt:
                melde(fehler, slug, f"Merkmal '{item['name'][:40]}…': Spalte(n) "
                                    f"{', '.join(sorted(unbekannt))} sind weder Editionen "
                                    f"dieses Produkts noch eigenständige Ausbaustufen davon")
            fehlend = oeffentliche - set(item["values"])
            if fehlend:
                melde(warnungen, slug, f"Merkmal '{item['name'][:40]}…': für die öffentliche(n) "
                                       f"Edition(en) {', '.join(sorted(fehlend))} fehlt ein Wert – "
                                       f"die Tabelle hat dort eine Lücke")

    # 5c. FAQ – Antworten veralten am schnellsten von allen Inhalten.
    #     Genau dieser Fall ist schon passiert: eine FAQ nannte ein Datum,
    #     das durch ein Release längst überholt war.
    bekannte_versionen = {r["version"] for r in p.get("releases", [])}
    for f in p.get("faq", []):
        if not f["question"].rstrip().endswith("?"):
            melde(warnungen, slug, f"FAQ '{f['question'][:40]}…' ist keine Frage")
        # \d{1,3} am Ende, damit Datumsangaben wie 01.08.2026 nicht als
        # Versionsnummer durchgehen – die werden gleich darunter eigens gemeldet.
        for v in re.findall(r"\b\d+\.\d+\.\d{1,3}\b", f["answer"]):
            if v not in bekannte_versionen:
                melde(warnungen, slug, f"FAQ '{f['question'][:40]}…' nennt Version {v}, "
                                       f"die es im Modell nicht gibt – vermutlich veraltet")
        for d in re.findall(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b", f["answer"]):
            melde(warnungen, slug, f"FAQ '{f['question'][:40]}…' enthält das feste Datum {d}. "
                                   f"Feste Daten veralten – besser aus releases[] ableiten")

    # 5j-b: Ein Plattform-Hinweis muss zum Status DIESER Plattform passen.
    # Dieselbe Regel wie beim statusGrund, nur eine Ebene tiefer: Sonst stuende
    # dort irgendwann ein Satz ueber eine Ablehnung, waehrend die App laengst
    # im Store liegt.
    for pl in p.get("platforms", []):
        h = pl.get("hinweis")
        if not h:
            continue
        if h["wenn"] != pl["status"]:
            melde(fehler, slug,
                  f"platforms[{pl['os']}].hinweis.wenn ist '{h['wenn']}', die Plattform steht "
                  f"aber auf '{pl['status']}' – der Satz wuerde nicht angezeigt. Entweder "
                  f"anpassen oder loeschen.")

    # 5d. Bilder müssen existieren – und die Bildmarke muss zum Namen passen
    medien = p.get("media", {})
    for bezeichnung, bild in list(medien.items()):
        # 'platzhalter' ist ein Schalter, kein Bild. Ohne diese Zeile faende die
        # Schleife dort ein src-Feld an einer Zahl - und bricht ab.
        if not isinstance(bild, (dict, list)):
            continue
        bilder = bild if isinstance(bild, list) else [bild]
        for b in bilder:
            datei = ROOT / b["src"].lstrip("/")
            if not datei.exists():
                melde(fehler, slug, f"media.{bezeichnung}: Datei {b['src']} gibt es nicht")
            if bezeichnung == "lockup":
                # Bei gesetztem Lockup IST das Bild der sichtbare Titel. Passt sein
                # Alternativtext nicht zum Produktnamen, driften Bildmarke und Modell
                # auseinander – und Screenreader lesen einen anderen Namen vor als
                # sehende Besucher sehen.
                if p["name"].lower() not in b["alt"].lower():
                    melde(fehler, slug, f"media.lockup: Alternativtext {b['alt']!r} enthält "
                                        f"den Produktnamen {p['name']!r} nicht")
                if b["src"].endswith(".png"):
                    melde(warnungen, slug, f"media.lockup ist eine PNG-Datei "
                                           f"({datei.stat().st_size // 1024} KB, sofern vorhanden). "
                                           f"Eine Wortmarke ist reine Vektorgrafik – als SVG "
                                           f"wäre sie ein Bruchteil davon und in jeder Größe scharf.")

                # Ein SVG mit echtem <text> ist eine Falle. Als <img> eingebunden
                # erbt es KEINE Schriften von der Seite: Der Browser nimmt, was
                # er hat. Poppins und Inter sind auf keinem Standardsystem
                # installiert, also wird mit Arial oder Ähnlichem gerendert –
                # das Logo sieht dann anders aus als gestaltet, und zwar nur bei
                # Besuchern, nie beim Entwickeln mit installierter Schrift.
                #
                # Aufgefallen am 19.07.2026 beim Umstellen der Wortmarken von
                # PNG auf SVG: Vier von sieben Vorlagen hatten Text statt Pfade,
                # eine davon sogar mit 'Liberation Sans' – einer Linux-Schrift,
                # die es unter Windows nicht gibt.
                #
                # Abhilfe im Zeichenprogramm: Text in Pfade wandeln
                # ("Objekt → Pfad → Objekt in Pfad umwandeln" bei Inkscape).
                if b["src"].endswith(".svg") and datei.exists():
                    inhalt = datei.read_text(encoding="utf-8", errors="ignore")
                    if re.search(r"<text[\s>]", inhalt):
                        gefunden, fremd = schriften_im_svg(inhalt)
                        # Zwei verschiedene Lagen, bisher in einen Topf geworfen:
                        #
                        # Poppins mit echtem Text ist die RICHTIGE Schrift, nur
                        # noch nicht in Pfade gewandelt – ärgerlich, reparabel.
                        #
                        # Arial ist die FALSCHE Marke. Das Markenkonzept kennt
                        # seit dem 20.07.2026 genau zwei Schriften; alles andere
                        # ist keine Nachlässigkeit mehr, sondern ein Verstoß.
                        # Beides als Warnung zu melden hieß, dass die schwerere
                        # Lage in der Menge unterging.
                        if fremd:
                            # Siehe pruefe_alle_svg(): vorerst Warnung, weil
                            # der Altbestand gerade neu gesetzt wird.
                            melde(warnungen, slug,
                                  f"media.lockup ist in {', '.join(fremd)} gesetzt. "
                                  f"Das Markenkonzept kennt nur Poppins und Inter "
                                  f"(_Marke_und_IP\\MARKENKONZEPT.md, Abschnitt 3). "
                                  f"Die Wortmarke ist neu zu setzen, nicht zu wandeln.")
                        else:
                            melde(warnungen, slug,
                                  f"media.lockup ist ein SVG mit echtem Text "
                                  f"({', '.join(gefunden) or 'ohne Schriftangabe'}). "
                                  f"Als Bild eingebunden erbt es die Schriften der Seite NICHT – "
                                  f"bei Besuchern ohne diese Schrift sieht die Wortmarke anders "
                                  f"aus. Im Zeichenprogramm Text in Pfade wandeln.")

    # 5e. Ein Titel braucht eine Form: Bildmarke ODER Wortmarke. Ohne beides
    #     steht dort schlichter Text – zulässig, aber es sollte Absicht sein.
    if p["kind"] == "produkt" and not medien.get("lockup") and not p.get("wordmark"):
        melde(warnungen, slug, "weder media.lockup noch wordmark – der Titel erscheint "
                               "als schlichter Text ohne Markenbezug")

    # 5f. Eine hervorgehobene Edition muss sich begründen lassen.
    #     Ohne Merkmalsmatrix steht auf der Seite eine betonte Spalte, die nicht
    #     zeigt, was sie mehr kann – die Bezahlfassung wirkt dann behauptet
    #     statt belegt. Genau dieser Punkt war schon einmal Anlass zur Kritik.
    #     Ausschlaggebend ist die Kombination kostenlos NEBEN kostenpflichtig: Nur
    #     dann steht der Besucher vor der Frage „wofür soll ich zahlen?". Zwei
    #     Bezahlstufen, die sich im Leistungsumfang gleichen und sich nur in der
    #     Betreuung unterscheiden (Enterprise: selbst branden oder branden lassen),
    #     sind mit ihren Kurzbeschreibungen ausreichend erklärt.
    oeffentlich = [e for e in p.get("editions", []) if e.get("public")]
    gratis = [e for e in oeffentlich if e["price"]["model"] == "kostenlos"]
    bezahlt = [e for e in oeffentlich if e["price"]["model"] in ("iap", "einmalig", "staffel")]
    if gratis and bezahlt and not p.get("features"):
        melde(warnungen, slug,
              f"kostenlose und kostenpflichtige Edition nebeneinander "
              f"({gratis[0]['id']} / {bezahlt[0]['id']}), aber keine features. "
              f"Die Seite kann nicht zeigen, wofür der Besucher zahlen soll.")

    # 5g. Jede Produktseite muss mindestens EINEN Weg anbieten.
    #     Die Seite leitet ihre Knöpfe aus diesen Angaben ab. Gibt es weder einen
    #     Download noch einen Store, weder einen Kaufweg noch eine Kontaktadresse,
    #     liest der Besucher etwas Interessantes und kann anschließend nichts tun.
    #     Für Online-Werkzeuge gilt das nicht: Dort IST die Seite das Werkzeug.
    if not p.get("customPage"):
        wege = []
        if st["cta"] != ["keine"] and p.get("releases"):
            wege.append("Download")
        if p.get("links", {}).get("store"):
            wege.append("Store")
        if p.get("links", {}).get("checkout"):
            wege.append("Kauf")
        if any(t.get("checkout") for e in p.get("editions", [])
               for t in e["price"].get("tiers", [])):
            wege.append("Pakete")
        if p.get("links", {}).get("contact"):
            wege.append("Kontakt")
        if not wege:
            melde(fehler, slug, "Sackgasse: kein Download, kein Store, kein Kaufweg und "
                                "keine links.contact – die Seite bietet dem Besucher nichts an")

    # 5h. Keine Produktseite ohne Merkmalstabelle.
    #     Ohne sie steht dort Fließtext und eine Preisangabe – der Besucher muss
    #     aus Prosa herauslesen, was das Ding eigentlich kann. Eine Spalte genügt
    #     (Funktionsübersicht), mehrere ergeben den Editionsvergleich.
    #
    #     Zwei Ausnahmen:
    #       • customPage – dort IST die Seite das Werkzeug.
    #       • Ausbaustufen, die die Matrix des Elternprodukts mitbenutzen: Die
    #         Tabelle steht dort EINMAL und wird von beiden Seiten gezeigt.
    eltern = next((q for q in alle_produkte if q["slug"] == p.get("parent")), None)
    erbt_matrix = any(
        p["slug"] in item["values"]
        for gruppe in (eltern or {}).get("features", [])
        for item in gruppe["items"]
    )
    if not p.get("features") and not p.get("customPage") and not erbt_matrix:
        stufe_offen = statuses[p["status"]]["order"] <= statuses["beta"]["order"]
        melde(fehler if stufe_offen else warnungen, slug,
              "keine features – die Produktseite hätte keine Merkmalstabelle. "
              "Eine Spalte reicht (Funktionsübersicht), mehrere ergeben den "
              "Editionsvergleich.")

    # 5k. Bildschirmfotos: echte Maße, echte Beschreibung.
    # Regel 5k-b: Platzhalter und echte Bilder schliessen einander aus. Beides
    # anzugeben ist kein Fehler mit Folgen - die Platzhalter greifen dann eh
    # nicht -, aber es ist ein vergessener Schalter, und der veraltet still.
    if medien.get("platzhalter") and medien.get("screenshots"):
        melde(warnungen, slug,
              "media.platzhalter steht neben echten screenshots und bleibt wirkungslos - "
              "echte Bilder haben Vorrang. Die Zeile kann weg.")

    # Regel 5k-c: Eine oeffentlich nutzbare Anwendung ohne jedes Bild laesst den
    # Besucher raten, wie sie aussieht. Platzhalter sind die Notloesung, kein
    # Ziel - deshalb bleibt der Hinweis stehen, solange sie im Einsatz sind.
    if p["kind"] == "produkt" and not p.get("customPage"):
        if not medien.get("screenshots"):
            if medien.get("platzhalter"):
                melde(abgleich, slug,
                      "zeigt Platzhalter statt Bildschirmfotos - sobald es die Anwendung gibt, "
                      "gehoeren echte Bilder her")
            else:
                melde(warnungen, slug,
                      "keine Bildschirmfotos und keine Platzhalter - die Produktseite hat "
                      "keine Galerie. Mit 'media.platzhalter: 4' gibt es wenigstens Motive.")

    for i, b in enumerate(medien.get("screenshots", [])):
        wo = f"media.screenshots[{i}]"
        datei = ROOT / b["src"].lstrip("/")
        if not datei.exists():
            melde(fehler, slug, f"{wo}: {b['src']} gibt es nicht")
            continue
        echt = bildmasse(datei)
        if echt and echt != (b["width"], b["height"]):
            melde(fehler, slug, f"{wo}: Datei ist {echt[0]}×{echt[1]}, im Modell steht "
                                f"{b['width']}×{b['height']} – das verzerrt das Bild "
                                f"oder lässt die Seite beim Laden springen")
        # Ein Alternativtext, der nur „Screenshot" sagt, hilft niemandem.
        if re.fullmatch(r"(?i)\s*(screenshot|bildschirmfoto|bild)\s*\d*\s*", b["alt"]):
            melde(fehler, slug, f"{wo}: Alternativtext '{b['alt']}' beschreibt nichts. "
                                f"Was ist auf dem Bild zu sehen?")
        # Hoch oder quer? Wenn 'geraet' dazu nicht passt, steht das Bild später
        # in der falschen Spaltenbreite.
        hoch = b["height"] > b["width"]
        if b.get("geraet") == "handy" and not hoch:
            melde(warnungen, slug, f"{wo}: als 'handy' gekennzeichnet, ist aber breiter als hoch")
        if b.get("geraet") == "desktop" and hoch:
            melde(warnungen, slug, f"{wo}: als 'desktop' gekennzeichnet, ist aber höher als breit")

    # 5l. Eigene Seitenfarben – der Kontrast wird gerechnet, nicht geschätzt.
    th = p.get("theme")
    if th:
        hg = th.get("hintergrund") or ("#1A1A1A" if th["modus"] == "dunkel" else "#fbf7f2")
        paare = [
            ("text", th.get("text") or ("#F0E8DC" if th["modus"] == "dunkel" else "#2B160B"), 4.5,
             "Fließtext"),
            ("textLeise", th.get("textLeise") or ("#B0A090" if th["modus"] == "dunkel" else "#6b5b50"), 4.5,
             "gedämpfter Text"),
            ("akzent", th.get("akzent") or p["accent"], 3.0,
             "Akzent (Überschriften, Rahmen – große Schrift)"),
        ]
        for feld, farbe, schwelle, wofuer in paare:
            k = kontrast(farbe, hg)
            if k < schwelle:
                melde(fehler, slug, f"theme.{feld} {farbe} auf {hg}: Kontrast {k} – "
                                    f"nötig sind {schwelle} für {wofuer}. Nicht lesbar.")
            elif k < schwelle + 0.7:
                melde(warnungen, slug, f"theme.{feld} {farbe} auf {hg}: Kontrast {k} – "
                                       f"knapp über der Schwelle von {schwelle}")

        # Der Modus muss zur Farbe passen. Ein 'dunkel' mit hellem Hintergrund
        # hätte alle Ableitungen gegen sich.
        dunkel_gemeint = th["modus"] == "dunkel"
        ist_dunkel = leuchtkraft(hg) < 0.2
        if dunkel_gemeint != ist_dunkel:
            melde(fehler, slug, f"theme.modus ist '{th['modus']}', der Hintergrund {hg} "
                                f"ist aber {'hell' if not ist_dunkel else 'dunkel'}")

        # Die Fläche soll sich vom Hintergrund abheben, sonst sieht man keine Karten.
        if th.get("flaeche") and kontrast(th["flaeche"], hg) < 1.08:
            melde(warnungen, slug, f"theme.flaeche {th['flaeche']} hebt sich kaum vom "
                                   f"Hintergrund ab – Karten wären unsichtbar")

    # 5j. Der persönliche Grund muss zum Status passen.
    #     Sonst steht auf der Seite „aufgeschoben, aber es kommt", während längst
    #     wieder gebaut wird – eine warme Erklärung, die zur Ausrede verkommt.
    grund = p.get("statusGrund")
    if grund and grund["wenn"] != p["status"]:
        melde(warnungen, slug,
              f"statusGrund gehört zu '{statuses[grund['wenn']]['label']}', das Produkt "
              f"steht aber auf '{statuses[p['status']]['label']}'. Der Text wird nicht "
              f"angezeigt – bitte neu schreiben oder entfernen.")

    # Wer stillsteht, sollte etwas dazu sagen. Ein nacktes „Pausiert" liest sich,
    # als sei das Projekt tot.
    if p["status"] in ("pausiert", "eingestellt") and not grund:
        melde(warnungen, slug,
              f"Status '{statuses[p['status']]['label']}' ohne statusGrund. Ein Satz dazu, "
              f"warum, nimmt der Meldung die Kälte.")

    # 5i. Umwege sind Berichte über Vergangenes – und müssen dazu passen.
    #     Der Sinn dieses Feldes steht und fällt damit, dass es NICHT den
    #     aktuellen Stand behauptet. Deshalb wird hier vor allem geprüft, ob
    #     ein Umweg mit dem abgeleiteten Weg zusammenpasst.
    plattform_nach_os = {pl["os"]: pl for pl in p["platforms"]}
    heute_iso = date.today().isoformat()
    vorher = {}
    for u in p.get("umwege", []):
        wo = f"Umweg {u['datum']}"
        if u["os"] not in plattform_nach_os:
            melde(fehler, slug, f"{wo}: für '{u['os']}' gibt es gar keine Plattform")
            continue
        # Entweder ein Ziel auf dem Weg ODER ein Zwischenschritt. Beides
        # zugleich hiesse: zwei Antworten auf die Frage, wo es weitergeht.
        if not u.get("nach") and not u.get("zwischenschritt"):
            melde(fehler, slug, f"{wo}: weder 'nach' noch 'zwischenschritt' – wo geht der "
                                f"Weg denn weiter?")
            continue
        if u.get("nach") and u.get("zwischenschritt"):
            melde(fehler, slug, f"{wo}: hat 'nach' UND 'zwischenschritt'. Der Weg kann nur "
                                f"an einer Stelle weitergehen – bitte eines von beiden.")
            continue

        if u.get("zwischenschritt"):
            # Der Name darf keine Statusstufe nachbauen. Wer einen echten
            # Meilenstein braucht, gehoert nach statuses.yaml - sonst gaebe es
            # dieselbe Stufe zweimal, einmal fuer alle und einmal versteckt.
            name = u["zwischenschritt"]["name"].strip().lower()
            for schluessel, st in statuses.items():
                if name == st.get("label", "").strip().lower():
                    melde(fehler, slug, f"{wo}: Zwischenschritt heisst wie die Statusstufe "
                                        f"'{st['label']}'. Echte Stufen gehoeren nach "
                                        f"statuses.yaml, nicht in einen einzelnen Umweg.")
            d = u["zwischenschritt"].get("datum")
            if d and d < u["datum"]:
                melde(fehler, slug, f"{wo}: Zwischenschritt datiert vor dem Umweg selbst")
            if d and d > heute_iso:
                melde(fehler, slug, f"{wo}: Zwischenschritt liegt in der Zukunft")
            continue

        von, nach = statuses.get(u["von"]), statuses.get(u["nach"])
        if von is None or nach is None:
            continue
        if "weg" not in von or "weg" not in nach:
            melde(fehler, slug, f"{wo}: '{u['von']}' oder '{u['nach']}' liegt nicht auf dem "
                                f"Weg (siehe statuses.yaml → weg)")
        elif nach["weg"] > von["weg"]:
            melde(fehler, slug, f"{wo}: geht von '{von['label']}' nach '{nach['label']}' – "
                                f"das ist kein Umweg, sondern ein Fortschritt")
        # nach == von ist erlaubt und heisst SCHLEIFE: Es ging nichts zurueck,
        # der Weg wurde nur noch einmal gegangen. Der haeufigste Fall dafuer ist
        # eine Ablehnung, gegen die Widerspruch laeuft - inhaltlich aendert sich
        # nichts, es kostet nur Zeit. Genau das soll man sehen.
        if u["datum"] > heute_iso:
            melde(fehler, slug, f"{wo}: liegt in der Zukunft. Umwege sind Ereignisse, "
                                f"die stattgefunden haben.")
        # Zwei Umwege am selben Tag für dieselbe Plattform sind fast immer ein
        # Versehen beim Abtippen.
        schluessel = (u["os"], u["datum"])
        if schluessel in vorher:
            melde(warnungen, slug, f"{wo}: zweiter Umweg am selben Tag für {u['os']}")
        vorher[schluessel] = True

    # Der jüngste Umweg je Plattform darf nicht weiter sein als der Stand heute:
    # Wer im Juni auf 'entwicklung' zurückfiel, kann heute nicht bei 'konzept' stehen.
    for os_name, pl in plattform_nach_os.items():
        letzte = sorted([u for u in p.get("umwege", []) if u["os"] == os_name and u.get("nach")],
                        key=lambda u: u["datum"])
        if not letzte:
            continue
        rueck = statuses.get(letzte[-1]["nach"], {})
        jetzt = statuses.get(pl["status"], {})
        if "weg" in rueck and "weg" in jetzt and jetzt["weg"] < rueck["weg"]:
            melde(fehler, slug, f"{os_name}: steht auf '{jetzt['label']}', der letzte Umweg "
                                f"({letzte[-1]['datum']}) führte aber schon nach "
                                f"'{rueck['label']}' – eines von beidem ist veraltet")

    # 6. Preise
    for e in p.get("editions", []):
        pr = e["price"]
        if pr["model"] in ("einmalig", "iap") and pr.get("amount") is None:
            melde(fehler, slug, f"Edition '{e['id']}': Modell '{pr['model']}' braucht einen Betrag")
        if pr["model"] == "staffel" and not pr.get("tiers"):
            melde(fehler, slug, f"Edition '{e['id']}': Modell 'staffel' braucht tiers")
        if pr["model"] == "offen" and e["public"] and p["status"] == "verfuegbar":
            melde(warnungen, slug, f"Edition '{e['id']}' ist öffentlich und das Produkt verfügbar, "
                                   f"der Preis ist aber noch offen")
        letzter_preis = None
        for t in pr.get("tiers", []):
            erwartet = round(t["amount"] / t["seats"], 2)
            if abs(erwartet - t["perSeat"]) > 0.005:
                melde(fehler, slug, f"Edition '{e['id']}', Staffel {t['seats']}: "
                                    f"perSeat {t['perSeat']} passt nicht zu {t['amount']}/{t['seats']} "
                                    f"= {erwartet}")
            # Ein Preis ohne Kaufweg ist eine Sackgasse: Die Seite nennt einen
            # Betrag, aber der Besucher kommt nirgendwohin.
            if e["public"] and p["status"] == "verfuegbar" and not t.get("checkout"):
                melde(fehler, slug, f"Edition '{e['id']}', Staffel {t['seats']} Plätze: "
                                    f"kein Kassenlink hinterlegt – der Preis "
                                    f"{t['amount']:.2f} € führt ins Leere")
            # Mengenrabatt heißt: pro Platz wird es günstiger, nie teurer.
            if letzter_preis is not None and t["perSeat"] > letzter_preis:
                melde(fehler, slug, f"Edition '{e['id']}': bei {t['seats']} Plätzen kostet "
                                    f"der Platz {t['perSeat']} € – mehr als in der Staffel "
                                    f"darunter ({letzter_preis} €). Das ist kein Mengenrabatt.")
            letzter_preis = t["perSeat"]
            if t.get("discountPercent") is not None and pr.get("tiers"):
                basis = pr["tiers"][0]["perSeat"]
                erw_rabatt = round((1 - t["perSeat"] / basis) * 100)
                if abs(erw_rabatt - t["discountPercent"]) > 1:
                    melde(warnungen, slug, f"Edition '{e['id']}', Staffel {t['seats']}: "
                                           f"angegebener Rabatt {t['discountPercent']} % passt nicht "
                                           f"zum tatsächlichen ({erw_rabatt} % gegenüber "
                                           f"{basis} € pro Platz)")

        # Einzelpreis ohne Kaufweg – dieselbe Sackgasse eine Ebene höher
        if pr["model"] in ("einmalig",) and e["public"] and p["status"] == "verfuegbar" \
                and not p.get("links", {}).get("checkout"):
            melde(fehler, slug, f"Edition '{e['id']}' hat einen Festpreis, aber es gibt "
                                f"keinen links.checkout – der Kauf ist nicht möglich")


# ------------------------------------------------------------------- Meldungen

# ------------------------------------------------- Doppelte Schluessel in YAML
#
# YAML nimmt bei einem doppelt vergebenen Schluessel wortlos den LETZTEN. Kein
# Fehler, keine Warnung, nichts. Am 21.07.2026 stand 'bild:' zweimal in
# aktionen.yaml - einmal mit vollem Pfad, einmal nur mit Dateinamen. Gewonnen
# hat der falsche, und aufgefallen ist es nur, weil zufaellig geprueft wurde,
# ob die Datei existiert.
#
# Es ist die zweite stille YAML-Falle dieser Woche (die erste war eine
# Einrueckung, die 'push' zum Kind von 'workflow_dispatch' machte). Beide
# haben gemeinsam: Die Datei ist gueltig, sie bedeutet nur etwas anderes.
# Genau dagegen hilft nur Nachsehen.

class WaechterLader(yaml.SafeLoader):
    """Wie SafeLoader, meldet aber doppelte Schluessel statt sie zu schlucken."""


def _keine_doppelten(lader, knoten, deep=False):
    gesehen = {}
    for schluessel_knoten, _ in knoten.value:
        k = lader.construct_object(schluessel_knoten, deep=deep)
        if k in gesehen:
            zeile = schluessel_knoten.start_mark.line + 1
            datei = pathlib.Path(schluessel_knoten.start_mark.name).name
            melde(fehler, "yaml",
                  f"{datei}, Zeile {zeile}: '{k}' steht zum zweiten Mal. YAML nimmt "
                  f"dann stillschweigend den letzten Wert - der erste ist wirkungslos, "
                  f"ohne dass irgendetwas es meldet.")
        gesehen[k] = True
    return yaml.SafeLoader.construct_mapping(lader, knoten, deep)


WaechterLader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _keine_doppelten)


def schreibe(pfad, text):
    """Schreibt eine erzeugte Datei - immer mit LF, nie mit CRLF.

    Pythons write_text() uebersetzt im Textmodus jedes '\n' unter Windows in
    '\r\n'. Git wandelt beim Einchecken zurueck und meldet das jedes Mal:

        warning: in the working copy of 'data/products.json', CRLF will be
        replaced by LF the next time Git touches it

    Zehnmal nebeneinander, bei jedem Commit. Schlimmer als der Laerm ist die
    Folge: Alle zehn Dateien gelten nach jedem Lauf als geaendert, auch wenn
    inhaltlich nichts anders ist. Man sieht dann nie, ob wirklich etwas
    passiert ist - und gewoehnt sich an, im 'git status' wegzuschauen.

    newline='\n' schreibt so, wie .gitattributes es ohnehin verlangt.
    """
    with open(pfad, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def lies_yaml(pfad):
    """Einziger Weg, eine YAML zu lesen - damit die Wache nirgends fehlt."""
    with open(pfad, encoding="utf-8") as f:
        return yaml.load(f, Loader=WaechterLader)


# Wird nach dem Lesen von meldungen.yaml gefuellt. pruefe_aktionen braucht die
# Liste, um zu sehen, ob dieselbe Meldung von Hand ein zweites Mal dasteht.
MELDUNGS_IDS = []


def pruefe_meldungen(meldungen, produkte, schema):
    """Prüft die Meldungen und löst ihre Verweise auf.

    Rückgabe: die Meldungen mit aufgelöstem Datum und den Wegen, die sich aus
    dem Produkt ergeben. Die Auflösung passiert HIER und nicht in der Website,
    damit jeder Verbraucher der Daten dieselben Werte sieht.
    """
    nach_slug = {p["slug"]: p for p in produkte}
    heute = date.today().isoformat()
    gesehen = {}
    ergebnis = []

    for m in meldungen:
        mid = m.get("id", "?")
        pruefe_gegen_schema(m, schema, "", f"meldung {mid}")

        # id ist ein Sprungziel. Eine doppelte id hieße: ein geteilter Link
        # führt mal hierhin, mal dorthin.
        if mid in gesehen:
            melde(fehler, f"meldung {mid}", "diese id gibt es schon ein zweites Mal")
        gesehen[mid] = True

        p = nach_slug.get(m.get("produkt")) if m.get("produkt") else None
        if m.get("produkt") and p is None:
            melde(fehler, f"meldung {mid}", f"Produkt '{m['produkt']}' gibt es im Modell nicht")
            continue

        # --- Version auflösen ------------------------------------------------
        release = None
        if m.get("version"):
            if p is None:
                melde(fehler, f"meldung {mid}", "version ohne produkt – ein Verweis ins Nichts")
            else:
                release = next((r for r in p.get("releases", [])
                                if r["version"] == m["version"]), None)
                if release is None:
                    vorhanden = ", ".join(r["version"] for r in p.get("releases", [])) or "keine"
                    melde(fehler, f"meldung {mid}",
                          f"{p['name']} hat keinen Release {m['version']} "
                          f"(vorhanden: {vorhanden})")

        # --- Datum auflösen --------------------------------------------------
        # Reihenfolge der Wahrheit: Release > platforms[].since > eigenes Feld.
        abgeleitet, quelle = None, None
        if release:
            abgeleitet, quelle = release["date"], f"Release {release['version']}"
        elif p is not None and m.get("typ") == "store":
            mit_since = [pl for pl in p["platforms"] if pl.get("since")]
            if len(mit_since) == 1:
                abgeleitet, quelle = mit_since[0]["since"], f"platforms[{mit_since[0]['os']}].since"

        if abgeleitet and m.get("datum") and m["datum"] != abgeleitet:
            melde(fehler, f"meldung {mid}",
                  f"datum {m['datum']} widerspricht {quelle} ({abgeleitet}). "
                  f"Eines von beiden ist falsch – beide Stellen zeigen dasselbe Ereignis.")
        datum = m.get("datum") or abgeleitet
        if not datum:
            melde(fehler, f"meldung {mid}",
                  "kein Datum – und keines, das sich aus Release oder platforms[].since ergibt")
            continue
        if datum > heute:
            melde(warnungen, f"meldung {mid}", f"Datum {datum} liegt in der Zukunft")

        # --- Versionsnummer im Titel darf nicht abdriften ---------------------
        # \d+\.\d+\.\d+ trifft absichtlich keine Datumsangaben wie 18.07.2026,
        # weil dort vier Stellen am Ende stehen.
        im_titel = re.search(r"\b(\d+\.\d+\.\d{1,3})\b", m.get("titel", ""))
        if im_titel and m.get("version") and im_titel.group(1) != m["version"]:
            melde(fehler, f"meldung {mid}",
                  f"im Titel steht Version {im_titel.group(1)}, verwiesen wird auf "
                  f"{m['version']}")

        # --- Wege, die sich aus dem Produkt ergeben --------------------------
        wege = {}
        if p is not None:
            if release:
                wege["download"] = release["url"]
            if p.get("links", {}).get("store"):
                wege["store"] = p["links"]["store"]
            if p.get("links", {}).get("checkout"):
                wege["kauf"] = p["links"]["checkout"]

        ziel = m.get("ziel")
        if ziel and ziel["url"] in wege.values():
            melde(warnungen, f"meldung {mid}",
                  "ziel.url wiederholt einen Weg, den die Seite ohnehin anbietet – "
                  "der Knopf stünde zweimal da")

        # HIER STAND EINE WARNUNG, DIE SEIT DEM 20.07.2026 FALSCH WAR.
        #
        # Sie meldete "hat keine eigene Produktseite", wenn links.page auf eine
        # Sammelseite zeigte. Seit dem Umbau bekommt JEDES Produkt eine Seite
        # unter /produkte/<slug>/, ganz gleich, was in links stand - die
        # Warnung beschrieb also einen Zustand, den es nicht mehr gibt. Sie
        # meldete das u.a. fuer SnapFuchs, einen Tag nachdem dessen Seite
        # entstanden war.
        #
        # Das Feld heisst jetzt links.alt_html und sagt, was es ist: die alte
        # Adresse, allein fuer die Weiterleitung. Gepruft wird stattdessen in
        # pruefe_alte_adressen(), ob die Datei dazu ueberhaupt existiert.

        if re.search(r"https?://", m.get("text", "")):
            melde(warnungen, f"meldung {mid}",
                  "im Text steht eine Adresse – Wege gehören nach ziel, sonst sind "
                  "sie nicht anklickbar und veralten unbemerkt")

        ergebnis.append({**m, "datum": datum, "datumQuelle": quelle or "eigene Angabe",
                         **({"wege": wege} if wege else {})})

    # --- Kein Release ohne Meldung -------------------------------------------
    # Das ist der eigentliche Zweck der Prüfung: Wer etwas veröffentlicht, ohne
    # es zu erzählen, hat es für die Besucher nicht veröffentlicht.
    erzaehlt = {(m.get("produkt"), m.get("version")) for m in meldungen}
    for p in produkte:
        for r in p.get("releases", []):
            if (p["slug"], r["version"]) not in erzaehlt:
                melde(warnungen, p["slug"],
                      f"Release {r['version']} vom {r['date']} hat keine Meldung in "
                      f"meldungen.yaml – auf der Aktuelles-Seite fehlt er damit")

    # Nur nach Datum sortieren. Pythons Sortierung ist stabil, deshalb behalten
    # Meldungen desselben Tages die Reihenfolge aus meldungen.yaml – also die,
    # die der Schreibende gemeint hat. Nach id zu sortieren wäre Zufall.
    return sorted(ergebnis, key=lambda m: m["datum"], reverse=True)


# -------------------------------------------------------------------- Wünsche

# Muster für Dinge, die in einer veröffentlichten Datei nichts zu suchen haben.
# Bewusst großzügig: Ein Fehlalarm kostet eine Minute, eine durchgerutschte
# E-Mail-Adresse kostet das Vertrauen, mit dem die ganze Marke wirbt.
PERSONENBEZUG = [
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "eine E-Mail-Adresse"),
    (re.compile(r"(?<!\d)(?:\+49|0)[\s/-]?\d{2,5}[\s/-]?\d{3,}(?!\d)"), "eine Telefonnummer"),
    (re.compile(r"\b(?:IBAN|DE\d{20})\b"), "eine Bankverbindung"),
]


def pruefe_dienste(dienste, produkte):
    """Dienste, die FehlerFuchs betreibt oder in Anspruch nimmt.

    Die Datenschutzseite leitet daraus ihre unterste Schicht ab. Geprueft wird
    vor allem eines: dass hier nichts steht, was nicht ins Netz gehoert.
    """
    slugs = {p["slug"] for p in produkte}
    gesehen = set()
    heute_iso = date.today().isoformat()
    # Grob, aber ausreichend: vier Zahlengruppen mit Punkten. Eine IP in einem
    # oeffentlich ausgelieferten Ordner ist genau die Sorte Angabe, die man
    # einmal eintraegt und nie wieder anschaut.
    ip = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
    # Ausgenommen: Adressen, die auf JEDEM Rechner dasselbe bedeuten und
    # nichts ueber unsere Infrastruktur verraten. Aufgefallen am 19.07.2026 im
    # BelegWerk-Steckbrief ("Voreinstellung 127.0.0.1") - die Regel haette dort
    # einen Fehler gemeldet, wo gar keiner ist. Eine Regel, die falsch anschlaegt,
    # wird abgeschaltet; deshalb lieber hier genau sein.
    HARMLOS = {"127.0.0.1", "0.0.0.0", "255.255.255.255"}

    for d in dienste:
        wo = f"Dienst '{d.get('id', '?')}'"
        if d["id"] in gesehen:
            melde(fehler, "dienste.yaml", f"{wo}: id kommt zweimal vor")
        gesehen.add(d["id"])

        for schluessel, wert in d.items():
            if isinstance(wert, str):
                treffer = [x for x in ip.findall(wert) if x not in HARMLOS]
                if treffer:
                    melde(fehler, "dienste.yaml",
                          f"{wo}: '{schluessel}' enthaelt eine IP-Adresse ({treffer[0]}). "
                          f"Dieser Ordner wird ausgeliefert - Infrastrukturangaben "
                          f"gehoeren nicht ins Netz.")

        if d.get("stand", "") > heute_iso:
            melde(fehler, "dienste.yaml", f"{wo}: 'stand' liegt in der Zukunft")

        unbekannt = [x for x in d.get("produkte", []) if x not in slugs]
        if unbekannt:
            melde(fehler, "dienste.yaml",
                  f"{wo}: nennt Produkte, die es nicht gibt: {', '.join(unbekannt)}")
        if not d.get("produkte"):
            melde(warnungen, "dienste.yaml",
                  f"{wo}: kein Produkt nutzt ihn. Ein Dienst ohne Nutzer gehoert entweder "
                  f"zugeordnet oder von der Datenschutzseite genommen.")
    return dienste


def pruefe_steckbriefe(produkte, dienste):
    """Die Datenschutz-Steckbriefe der Projekte.

    Sie kommen aus dem Einreichordner und sind vor der Uebernahme schon auf
    Vertrauliches geprueft (tools/steckbriefe_uebernehmen.py). Hier geht es um
    etwas anderes: um WIDERSPRUECHE zwischen dem, was die Produktseite
    verspricht, und dem, was das Projekt ueber sein eigenes Programm sagt.

    Das ist der eigentliche Zweck des ganzen Umlaufs. Ein Werbeversprechen
    'nur lokal' neben einem Steckbrief, der eine Uebertragung nennt, ist keine
    Kleinigkeit - es ist eine falsche Zusicherung auf einer Rechtsseite.
    """
    ordner = SRC / "datenschutz"
    if not ordner.is_dir():
        warnungen.append(
            "keine Datenschutz-Steckbriefe im Modell (data/src/datenschutz/) - "
            "die Datenschutzseite haette dann nur den allgemeinen Teil. "
            "Uebernehmen mit: python tools/steckbriefe_uebernehmen.py --uebernehmen")
        return []

    # Werbeaussage auf der Produktseite  ->  Tatsachenfeld im Steckbrief
    VERSPRECHEN = {
        "nur-lokal": ("lokal_only", True),
        "kein-tracking": ("tracking", False),
        "werbefrei": ("werbung", False),
        "kein-konto": ("konto_noetig", False),
    }

    heute = date.today().isoformat()
    lange_her = (date.today() - timedelta(days=180)).isoformat()
    nach_slug = {p["slug"]: p for p in produkte}
    dienst_ids = {d["id"] for d in dienste}

    steckbriefe = []
    for f in sorted(ordner.glob("*.yaml")) + sorted((ordner / "dienste").glob("*.yaml")):
        ist_dienst = f.parent.name == "dienste"
        try:
            s = lies_yaml(f)
        except yaml.YAMLError as e:
            fehler.append(f"datenschutz/{f.name}: YAML lässt sich nicht lesen – {e}")
            continue
        if not isinstance(s, dict) or "slug" not in s:
            fehler.append(f"datenschutz/{f.name}: kein gültiger Steckbrief (slug fehlt)")
            continue

        kennung = s["slug"]
        wo = f"Steckbrief '{kennung}'"
        if kennung != f.stem:
            fehler.append(f"{wo}: Dateiname {f.name} passt nicht zum slug")

        stand = str(s.get("stand", ""))
        if stand > heute:
            fehler.append(f"{wo}: 'stand' liegt in der Zukunft ({stand})")
        elif stand < lange_her:
            warnungen.append(
                f"{wo}: zuletzt am {stand} geprüft – älter als ein halbes Jahr. "
                f"Bestätigend erneuern, dann sieht man, dass hingeschaut wurde.")

        if ist_dienst:
            if kennung not in dienst_ids:
                fehler.append(f"{wo}: kein Dienst mit dieser Kennung in dienste.yaml")
            steckbriefe.append({**s, "art": "dienst"})
            continue

        # --- Widerspruch zwischen Versprechen und Tatsache ------------------
        p = nach_slug.get(kennung)
        if p:
            tags = p.get("privacy") or []
            for tag, (feld, erwartet) in VERSPRECHEN.items():
                if tag in tags and s.get(feld) not in (None, erwartet):
                    fehler.append(
                        f"{wo}: Die Produktseite verspricht '{tag}', der Steckbrief sagt "
                        f"{feld}={s[feld]!r}. Eines von beidem ist falsch – und auf einer "
                        f"Rechtsseite ist das keine Kleinigkeit.")

            # Die schwächere Zusage bei einem Programm, das gar nichts sendet:
            # kein Fehler, aber verschenkt. Wer strenger ist, soll es sagen.
            if "inhalte-lokal" in tags and s.get("lokal_only") is True:
                warnungen.append(
                    f"{wo}: trägt 'inhalte-lokal', sendet laut Steckbrief aber gar nichts. "
                    f"Dann ist 'nur-lokal' die richtige – und stärkere – Angabe.")
            if "nur-lokal" in tags and "inhalte-lokal" in tags:
                fehler.append(f"{wo}: 'nur-lokal' und 'inhalte-lokal' schließen sich aus.")

            # 'kein-google' heißt seit dem 20.07.2026: „Es geht nichts an
            # Google-Server." Die Frage ist damit nicht mehr, ob Google-Code
            # im Programm steckt, sondern ob eine VERBINDUNG entsteht.
            #
            # Der Unterschied entscheidet zwei reale Fälle:
            #   SnapFuchs fragte beim App-Start den Kaufstatus bei Google Play
            #     ab – eine Übertragung, das Merkmal war falsch.
            #   OrgaFuchs rechnet mit Google ML Kit, aber auf dem Gerät –
            #     keine Übertragung, das Merkmal ist richtig.
            #
            # Deshalb sucht die Prüfung in 'uebertragungen' und nicht in
            # 'fremde_dienste'. Eine Regel, die beides gleich behandelt, hätte
            # OrgaFuchs zu Unrecht angeschwärzt – und wer einmal zu Unrecht
            # gemeldet wird, glaubt der Regel beim nächsten Mal nicht mehr.
            if "kein-google" in tags:
                nach_google = []
                for u in (s.get("uebertragungen") or []):
                    if not isinstance(u, dict):
                        continue
                    ziel = str(u.get("wohin", ""))
                    if re.search(r"(?i)google", ziel):
                        nach_google.append(f"{ziel} ({u.get('wann', 'ohne Angabe')})")
                if nach_google:
                    warnungen.append(
                        f"{wo}: trägt 'kein-google', überträgt laut Steckbrief aber an "
                        f"{'; '.join(nach_google)}. Das Merkmal sagt zu, dass nichts an "
                        f"Google-Server geht.")

                # Kein Befund, aber ein Hinweis: Google-Bibliotheken im
                # Programm sind zulässig, solange sie nichts senden. Damit
                # das eine bewusste Aussage bleibt und keine Nachlässigkeit,
                # wird es beim Prüflauf einmal genannt.
                lokal = [str(d.get("name", ""))[:60]
                         for d in (s.get("fremde_dienste") or [])
                         if isinstance(d, dict)
                         and "google" in json.dumps(d, ensure_ascii=False).lower()
                         and not str(d.get("name", "")).lower().startswith(("kein", "keine"))]
                if lokal and not nach_google:
                    abgleich.append(
                          f"{wo}: trägt 'kein-google' und bindet {'; '.join(lokal)} ein – "
                          f"laut Steckbrief ohne Verbindung nach draußen. So gemeint? "
                          f"Dann ist alles richtig.")

        # --- Widerspruch im Steckbrief selbst -------------------------------
        # Nicht jede 'Uebertragung' geht nach draussen. BelegWerk prueft eine
        # TCP-Verbindung zum eigenen Rechner (127.0.0.1) - das ist keine
        # Datenweitergabe, sondern die Frage 'laeuft mein Dienst?'. Wer das als
        # Widerspruch meldet, bringt ein Projekt dazu, seinen ehrlichen
        # Steckbrief zu beschoenigen. Genau das darf nicht passieren.
        EIGENES_GERAET = re.compile(
            r"(?i)127\.0\.0\.1|\blocalhost\b|eigener?\s+rechner|dasselbe\s+ger[äa]t")

        pflicht = [u for u in (s.get("uebertragungen") or [])
                   if isinstance(u, dict) and u.get("freiwillig") is False
                   and u.get("was") not in (None, "nichts", "keine")
                   and not EIGENES_GERAET.search(str(u.get("wohin", "")))]
        if s.get("lokal_only") is True and pflicht:
            fehler.append(
                f"{wo}: lokal_only=true, aber {len(pflicht)} Übertragung(en) ohne "
                f"Zutun des Nutzers (freiwillig: false). Das schließt sich aus.")
        if s.get("lokal_only") is False and not (s.get("uebertragungen") or []):
            warnungen.append(
                f"{wo}: lokal_only=false, aber keine Übertragung genannt – "
                f"dann fehlt die Angabe, wohin die Daten gehen.")

        steckbriefe.append({**s, "art": "anwendung"})

    # --- Innensicht in Texten, die auf der Seite landen --------------------
    #
    # Die Datenschutzerklärung ist Matzes Erklärung – nach außen tritt niemand
    # anders auf. Wie die Angaben intern zusammenkommen, ist ein Arbeitsablauf.
    # Steht davon etwas im Text, liest ein Besucher plötzlich von 'Steckbriefen'
    # und 'Slugs' und fragt sich, wer hier eigentlich spricht.
    #
    # Aufgefallen am 19.07.2026 beim ersten Bau der Seite: Ein 'besonderheiten'
    # sagte, der Dienst gehöre 'in die dritte Schicht der Datenschutzseite'.
    # Sachlich richtig, aber an einen Leser gerichtet, den es nicht gibt.
    #
    # Gemeldet wird nur, was tatsächlich angezeigt wird. Felder wie
    # offene_fragen oder beleg sind Arbeitsmaterial und erscheinen nie.
    INNENSICHT = re.compile(
        r"(?i)\b(steckbrief\w*|slug\w*|prompt\w*|chefbüro|chefbuero|"
        r"website-projekt|einreich\w*|umlauf|arbeitsfassung|"
        r"(erste|zweite|dritte|vierte)\s+schicht|datenschutzseite|"
        r"matze)\b")
    # 'Datenmodell' und 'Produktmodell' standen hier auch – und haben sofort
    # falsch angeschlagen: CoppiceMail speichert ein "E-Mail-Datenmodell", das
    # ist sein eigenes und nicht unseres. Zu allgemeine Wörter melden das
    # Falsche; die eindeutigen oben reichen.

    ANGEZEIGT = ("loeschung", "besonderheiten")
    ANGEZEIGT_LISTEN = {
        "auf_dem_geraet": ("was", "wo"),
        "berechtigungen": ("name", "wofuer", "hinweis"),
        "uebertragungen": ("wohin", "was", "wann"),
        "fremde_dienste": ("name", "wofuer", "wann"),
    }

    # Nur was auch angezeigt wird. Beide Meldungen unten sagen "steht auf der
    # Datenschutzseite" – bei einem Steckbrief ohne Produktseite (SchichtFuchs)
    # wäre das schlicht falsch, und eine Warnung, die nicht stimmt, erzieht
    # dazu, Warnungen zu überlesen.
    for s in steckbriefe:
        if s["art"] == "anwendung" and s["slug"] not in nach_slug:
            continue
        stellen = [(f, s.get(f)) for f in ANGEZEIGT if isinstance(s.get(f), str)]
        for feld, schluessel in ANGEZEIGT_LISTEN.items():
            for i, eintrag in enumerate(s.get(feld) or []):
                if isinstance(eintrag, dict):
                    stellen += [(f"{feld}[{i}].{k}", eintrag[k])
                                for k in schluessel if isinstance(eintrag.get(k), str)]
                elif isinstance(eintrag, str):
                    stellen.append((f"{feld}[{i}]", eintrag))

        for feld, text in stellen:
            treffer = sorted({t[0] if isinstance(t, tuple) else t
                              for t in INNENSICHT.findall(text)})
            if treffer:
                warnungen.append(
                    f"Steckbrief '{s['slug']}': '{feld}' spricht die Innensicht an "
                    f"({', '.join(treffer)}). Dieser Text steht auf der Datenschutzseite – "
                    f"dort liest ihn jemand, der von unserer Arbeitsteilung nichts weiß. "
                    f"Bitte als Aussage über das Programm umformulieren.")

            # ---- Betriebsinterna in einem Text, der öffentlich steht -------
            #
            # Bei der Durchsicht am 19.07.2026 stand in einem Abschnitt wörtlich,
            # dass die Lizenzsperre nicht scharf geschaltet ist – samt der Namen
            # der beiden Schalter. Das ist keine Datenschutzangabe mehr, sondern
            # eine Handreichung an jeden, der nicht zahlen möchte.
            #
            # Die Grenze verläuft nicht bei "unangenehm", sondern bei "nützt nur
            # dem Angreifer": DASS eine Datei liegen bleibt, muss ein Nutzer
            # wissen. DASS ihr Löschen die Testphase zurücksetzt, muss er nicht.
            for muster, was in (
                (r"\b\w+ *= *(?:true|false)\b", "Schaltervariable mit Wert"),
                (r"\b[\w/]+\.(?:dart|py|cs|kt|java|mjs|ts|nsi|csproj|xml|yaml)\b",
                 "Quelltextdatei"),
                (r"\bZeilen? *\d+(?:\s*-\s*\d+)?\b|:\d+-\d+\b", "Zeilennummer"),
                # ue/ae/oe mitdenken: Viele Zulieferungen sind umlautfrei
                # geschrieben, 'Pruefung' waere sonst durchgerutscht.
                (r"(?i)\bkeine? (?:serverseitige|wiederkehrende) (?:pr[üu]e?f|lizenzpr[üu]e?f)\w*",
                 "Hinweis, dass eine Prüfung fehlt"),
                # Nur INNERE Feldnamen. Der Dateiname license_state.json stand
                # hier auch – und hat prompt dreimal falsch gemeldet: Genau
                # dieser Name gehört in die Erklärung, sonst kann niemand die
                # Datei finden und löschen (Art. 17 DSGVO). Die Grenze verläuft
                # zwischen 'wo liegt meine Datei' (muss rein) und 'wie heißen
                # die Felder darin' (nützt nur dem, der sie manipulieren will).
                (r"(?i)\blizenz\.\w+|\b(?:lizenz|license)[._](?:key|token|fingerprint)\b",
                 "innerer Feldname der Lizenzablage"),
                (r"(?i)\bnicht scharf geschaltet\b|\bsperre .{0,20}(?:nicht|kein)\w*\b",
                 "Hinweis auf eine unwirksame Sperre"),
            ):
                if re.search(muster, text):
                    warnungen.append(
                        f"Steckbrief '{s['slug']}': '{feld}' enthält Betriebsinterna "
                        f"({was}). Dieser Text wird auf der Datenschutzseite "
                        f"veröffentlicht. Belege gehören ins Feld 'beleg' – das wird "
                        f"nicht angezeigt.")
                    break

    # --- Produkte ohne Steckbrief ------------------------------------------
    # Der wichtigste Fall: Ein Produkt steht auf der Seite, sagt aber nirgends,
    # was es mit Daten tut. Die Datenschutzseite hätte dort eine Lücke.
    vorhanden = {s["slug"] for s in steckbriefe}
    for p in produkte:
        if p["slug"] not in vorhanden:
            warnungen.append(
                f"{p['slug']}: hat eine Produktseite, aber keinen Datenschutz-Steckbrief – "
                f"auf der Datenschutzseite bliebe dieses Produkt unerwähnt.")

    return steckbriefe


BEDARF_ARTEN = {"beitrag", "geraet", "sponsoring", "zeit"}
BEDARF_STATUS = {"offen", "in-arbeit", "erfuellt"}
BEDARF_TAKTE = {"einmalig": "", "jaehrlich": " / Jahr", "monatlich": " / Monat"}
# Die Motive stehen als SVG in der Seite. Hier steht nur, welche es gibt –
# so fällt ein Tippfehler beim Erzeugen auf und nicht erst als leere Stelle
# im Browser, wo ihn niemand meldet.
BEDARF_ZEICHEN = {"siegel", "platte", "blitz", "rechner", "bildschirm",
                  "handschlag", "leute", "kabel", "werkzeug", "funke"}


def euro(n):
    """1500 → '1.500'. Punkt als Tausendertrenner, wie im Deutschen üblich."""
    return f"{n:,}".replace(",", ".")


def betrag_text(e):
    """Baut '~200–400 € / Jahr' aus von/bis/takt.

    Steht bewusst hier und nicht in der Seite: Sonst müsste dieselbe Regel in
    JavaScript noch einmal existieren – für die Werkstatt, für die Vorschau,
    für jede weitere Stelle, die den Betrag zeigen will.
    """
    if e.get("von") is None:
        return ""
    spanne = f"{euro(e['von'])}–{euro(e['bis'])}" if e.get("bis") else euro(e["von"])
    return f"~{spanne} €{BEDARF_TAKTE.get(e.get('takt'), '')}"

# Eine IBAN im Fließtext wäre kein Weltuntergang – die Bankverbindung steht
# ohnehin auf der Seite. Aber sie gehört an EINE Stelle, die aus marke.yaml
# kommt, nicht verstreut in Bedarfstexte, wo sie beim nächsten Kontowechsel
# stehen bliebe.
IBAN_MUSTER = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,}")



def pruefe_fremdziele(rohd, produkte, marke):
    """Jede fremde Adresse im Datenmodell muss in 'fremdziele' beschrieben sein.

    Am 20.07.2026 stellte sich heraus: Die Website verweist auf PayPal, GitHub
    und Google Play, und keines davon stand in der Datenschutzerklärung. Bei
    PayPal war es seit der alten Website so. Gefunden habe ich es nur, weil ich
    zufällig danach suchte — und genau darauf soll sich niemand verlassen
    müssen.

    Der Fund ist ein FEHLER und keine Warnung: Eine Datenschutzerklärung, die
    ein Ziel verschweigt, ist unvollständig, und unvollständig veröffentlicht
    ist schlimmer als gar nicht gebaut.
    """
    beschrieben = {f.get("adresse", "").lower().removeprefix("www.")
                   for f in (rohd.get("fremdziele") or [])}

    # Eigene Adressen sind keine Fremdziele.
    eigen = {"fehlerfuchs.eu", "license.fehlerfuchs.eu", "localhost"}

    # Wo überall Adressen stehen können: Produkte, Marke, Dienste. Statt jede
    # Stelle einzeln zu kennen, wird der gesamte Baum nach http-Adressen
    # durchsucht — eine neue Stelle im Modell fällt damit von selbst mit auf.
    gefunden = {}

    def suche(knoten, woher):
        if isinstance(knoten, dict):
            for k, v in knoten.items():
                suche(v, woher)
        elif isinstance(knoten, list):
            for v in knoten:
                suche(v, woher)
        elif isinstance(knoten, str):
            for treffer in re.findall(r"https?://([a-zA-Z0-9.-]+)", knoten):
                gefunden.setdefault(treffer.lower(), set()).add(woher)

    for p in produkte:
        suche(p, p.get("slug", "?"))
    suche(marke, "marke")
    # Die Dienste beschreiben sich selbst – dort steht die Erklärung des
    # Anbieters, und die IST das Fremdziel. Sie mitzuprüfen hieße, jede
    # Erklärungs-Adresse doppelt zu führen.
    suche(rohd.get("dienste") or [], "dienste")

    for adresse, woher in sorted(gefunden.items()):
        kurz = adresse.removeprefix("www.")
        if kurz in eigen or kurz.endswith(".fehlerfuchs.eu"):
            continue
        if kurz in beschrieben:
            continue
        wer = ", ".join(sorted(woher)[:4])
        melde(fehler, "fremdziele",
              f"{adresse} steht im Datenmodell ({wer}), aber nicht in "
              f"dienste.yaml unter 'fremdziele'. Damit fehlt es auf der "
              f"Datenschutzseite — ein Ziel, das niemand genannt hat.")



# Zusagen, die im Freitext stehen können. Der Schlüssel ist das Merkmal, das
# sie belegen muss.
FREITEXT_ZUSAGEN = {
    "kein-google":   (re.compile(r"(?i)ohne\s+google"), "ohne Google"),
    "keine-cloud":   (re.compile(r"(?i)(ohne|keine)\s+cloud"), "ohne Cloud"),
    "kein-konto":    (re.compile(r"(?i)(ohne|keine?)\s+(konto|anmeldung)"), "ohne Konto"),
    "werbefrei":     (re.compile(r"(?i)((ohne|keine)\s+werbung|werbefrei)"), "werbefrei"),
    "kein-tracking": (re.compile(r"(?i)(ohne|kein)\s+tracking"), "ohne Tracking"),
}


# HIER STAND EINE PRUEFUNG DES AKZENT-KONTRASTS. Sie ist am 20.07.2026 wieder
# entfernt worden, und der Weg dorthin ist lehrreicher als die Regel es war.
#
# Erste Fassung: mass die Akzentfarbe pauschal gegen hell und meldete SnapFuchs
#   mit 1,93:1. Uebersehen: Die Produktseite traegt das Theme des Produkts, und
#   SnapFuchs ist absichtlich dunkel gebaut - dort sind es 6,96:1.
#
# Zweite Fassung: mass nur noch gegen die Produktkarte, die tatsaechlich weiss
#   ist. Rechnerisch richtig, in der Sache trotzdem falsch: WCAG 1.4.11 gilt
#   fuer grafische Elemente, die zum VERSTEHEN noetig sind. Der Balken links an
#   der Karte traegt keine Information - Name, Status und Beschreibung stehen
#   daneben. Er ist Wiedererkennung, kein Bedeutungstraeger.
#
# Was bleibt: Eine Regel muss wissen, WO die Farbe landet und WOFUER sie dort
# steht. Beides hatte ich nicht geprueft, sondern eine Zahl gerechnet und
# daraus einen Befund gemacht. Wo Kontrast wirklich zaehlt - Text, Bedienung,
# Statusfarben - wird er weiterhin geprueft, in pruefe_inhalt().


PLAY_STORE = "https://play.google.com/store/apps/details?id="


def store_adresse_ableiten(p):
    """Baut links.store aus der storeId, wenn er fehlt.

    Beide Angaben sind dasselbe: Die Store-Adresse ist die Paketkennung mit
    einem festen Vorspann davor. Sie zweimal zu pflegen hat am 20.07.2026 genau
    das getan, was doppelte Angaben immer tun — SnapFuchs ging im Play Store
    live, bekam 'storeId', und auf der Produktseite stand trotzdem „Bescheid
    geben lassen", weil 'links.store' fehlte. Der Knopf zum Herunterladen war
    nicht da, obwohl die App verfuegbar war.

    OrgaFuchs hatte dieselbe Luecke, nur unbemerkt: Dort verdeckte der
    Windows-Download, dass der Play-Store-Knopf fehlte.
    """
    links = p.setdefault("links", {})
    for pl in p.get("platforms") or []:
        if pl.get("distribution") != "play-store" or not pl.get("storeId"):
            continue
        abgeleitet = PLAY_STORE + pl["storeId"]
        if not links.get("store"):
            links["store"] = abgeleitet
        elif links["store"] != abgeleitet:
            # Widerspruch: Beide stehen da und meinen Verschiedenes. Welcher
            # stimmt, kann nur ein Mensch wissen.
            melde(fehler, p["slug"],
                  f"links.store zeigt auf {links['store']}, aus storeId "
                  f"'{pl['storeId']}' ergaebe sich aber {abgeleitet}. "
                  f"Eine der beiden Angaben ist falsch.")
        return


def pruefe_freitext_zusagen(p):
    """Tagline und Beschreibung dürfen nichts versprechen, was die
    Merkmalsliste nicht deckt.

    Die Merkmale werden gegen den Datenschutz-Steckbrief geprüft, der Freitext
    bisher nicht — dabei steht die Tagline ganz oben auf der Produktseite und
    ist die sichtbarste Zusage von allen.

    Am 20.07.2026 stand bei SnapFuchs „ohne Google" in der Tagline UND als
    Merkmal, obwohl die App beim Start Google Play kontaktiert. Beim Streichen
    des Merkmals wäre die Tagline um ein Haar stehen geblieben — dann hätte die
    Seite dasselbe weiter behauptet, nur an einer Stelle, die niemand prüft.
    """
    text = f"{p.get('tagline') or ''} {p.get('description') or ''}"
    hat = set(p.get("privacy") or [])
    for tag, (muster, wortlaut) in FREITEXT_ZUSAGEN.items():
        if muster.search(text) and tag not in hat:
            melde(fehler, p["slug"],
                  f"Tagline oder Beschreibung sagt '{wortlaut}', das Merkmal "
                  f"'{tag}' fehlt aber. Entweder das Merkmal setzen — dann wird "
                  f"es gegen den Steckbrief geprüft — oder die Zusage aus dem "
                  f"Text nehmen.")


def pruefe_alle_svg():
    """Jede SVG im Bildordner auf fremde Schriften.

    Die Prüfung bei media.lockup erwischt nur Dateien, die ein Produkt
    referenziert. Am 20.07.2026 fiel auf: '404-kaffeetasse.svg' ist in Arial
    gesetzt und wird von keinem Produkt genannt – also sah sie nie jemand an,
    obwohl sie auf jeder Fehlerseite ausgeliefert wird. Dasselbe gilt für die
    App-Icons, die als Vorrat herumliegen und irgendwann eingebunden werden.

    Eine Datei, die niemand prüft, weil niemand sie referenziert, ist genau
    die, die beim Einbinden Ärger macht.
    """
    ordner = ROOT / "img"
    if not ordner.exists():
        return

    for datei in sorted(ordner.rglob("*.svg")):
        rel = datei.relative_to(ordner).as_posix()
        inhalt = datei.read_text(encoding="utf-8", errors="ignore")
        if not re.search(r"<text[\s>]", inhalt):
            continue

        alle, fremd = schriften_im_svg(inhalt)
        if fremd:
            # WARNUNG und nicht FEHLER – vorerst.
            #
            # Ein Fehler bricht den Lauf ab und schreibt nichts. Am 20.07.2026
            # hätte das die gesamte Website blockiert: fünf Dateien tragen
            # Arial, und sie werden gerade vom Projekt „Marke und Identität"
            # neu gesetzt. Eine Prüfung, die den Betrieb anhält wegen etwas,
            # das woanders schon in Arbeit ist, wird abgeschaltet – und dann
            # fehlt sie ganz.
            #
            # HOCHSTUFEN AUF FEHLER, sobald der Abschlussbericht von „Marke
            # und Identität" vorliegt. Dann ist jede fremde Schrift ein
            # Rückschritt und kein Altbestand mehr.
            melde(warnungen, "bilder",
                  f"img/{rel} ist in {', '.join(fremd)} gesetzt. Das Markenkonzept "
                  f"kennt nur Poppins und Inter – die Datei ist NEU ZU SETZEN, "
                  f"nicht zu wandeln.")
        else:
            melde(abgleich, "bilder", f"img/{rel} enthält noch echten Text "
                                      f"({', '.join(alle) or 'ohne Schriftangabe'}) – "
                                      f"vor dem nächsten Einsatz in Pfade wandeln.")


def pruefe_aktionen(eintraege, produkte):
    """Prueft die zeitlich begrenzten Aktionen.

    Aus jedem Eintrag entstehen zwei Dinge von selbst: die Seite unter
    /aktion/<id>/ und ein Abschnitt auf der Datenschutzseite. Eine neue Aktion
    braucht deshalb nichts als einen Eintrag - und genau deshalb muss dieser
    Eintrag vollstaendig sein, bevor er durchgeht.

    Der Kern ist 'zeigen_bis'. Ein Datenschutzabschnitt darf nicht mit der
    Aktion verschwinden - danach laufen noch die Speicherfristen, und wer
    wissen will, was mit seiner Adresse geschieht, muss es nachlesen koennen,
    solange sie liegt.
    """
    slugs = {p["slug"] for p in produkte}
    heute = date.today().isoformat()
    gesehen = set()

    for a in eintraege:
        kennung = a.get("id", "?")
        wo = f"Aktion '{kennung}'"

        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(kennung)):
            melde(fehler, "aktionen", f"{wo}: id nur klein, Ziffern und Bindestriche - "
                                      f"sie wird zur Adresse /aktion/{kennung}/.")
        if kennung in gesehen:
            melde(fehler, "aktionen", f"{wo}: id kommt doppelt vor.")
        gesehen.add(kennung)

        if a.get("produkt") and a["produkt"] not in slugs:
            melde(fehler, "aktionen", f"{wo}: produkt '{a['produkt']}' gibt es nicht.")

        # --- Was die Seite braucht ----------------------------------------
        for feld in ("titel", "vorspann", "was_es_gibt", "frage", "endpunkt", "danach"):
            if not str(a.get(feld) or "").strip():
                melde(fehler, "aktionen", f"{wo}: {feld} fehlt - ohne diese Angabe laesst "
                                          f"sich die Seite nicht bauen.")

        if not str(a.get("endpunkt") or "").startswith("https://"):
            melde(fehler, "aktionen", f"{wo}: endpunkt muss eine https-Adresse sein.")

        # 'gueltig_bis' ist ein Zeitstempel, kein Text: Die Seite rechnet
        # daraus, wie lange noch Zeit ist. Als Wort ginge das nicht.
        gb = a.get("gueltig_bis")
        if gb:
            try:
                ende = datetime.fromisoformat(str(gb))
            except ValueError:
                melde(fehler, "aktionen", f"{wo}: gueltig_bis '{gb}' ist kein Zeitstempel. "
                                          f"Erwartet wird etwa 2027-07-19T23:00:00+02:00.")
            else:
                if ende.tzinfo is None:
                    melde(warnungen, "aktionen",
                          f"{wo}: gueltig_bis hat keine Zeitzone. Im Sommer sind das eine "
                          f"Stunde Unterschied - genug, um jemanden zu spaet kommen zu lassen.")
                # Eine Frist ohne Erklaerung liest sich wie eine Laufzeit.
                # Genau dieses Missverstaendnis - "Pro laeuft 2027 aus" -
                # waere das teuerste an der ganzen Aktion.
                if not (a.get("dauerhaft") or "").strip():
                    melde(fehler, "aktionen",
                          f"{wo}: hat ein gueltig_bis, aber kein Feld 'dauerhaft'. "
                          f"Ohne den Satz liest sich die Frist wie eine Laufzeit - "
                          f"als wuerde die Freischaltung an dem Datum enden.")
                if ende < datetime.now(ende.tzinfo) and a.get("laeuft"):
                    melde(fehler, "aktionen",
                          f"{wo}: gueltig_bis liegt in der Vergangenheit, die Aktion steht "
                          f"aber auf laeuft: true. Dann werden Codes verteilt, die niemand "
                          f"mehr einloesen kann.")

        # Eine laufende Aktion, von der die Website nichts erzaehlt, ist eine
        # Seite, die niemand findet. Deshalb Pflicht, solange sie laeuft.
        m = a.get("meldung") or {}
        if a.get("laeuft"):
            if not m.get("titel") or not m.get("text"):
                melde(fehler, "aktionen",
                      f"{wo}: laeuft, hat aber keine 'meldung' mit titel und text. "
                      f"Ohne sie steht die Aktion auf keiner Seite ausser ihrer "
                      f"eigenen - gefunden wird sie dann nur ueber den geteilten Link.")
            elif len(str(m.get("text"))) < 40:
                melde(fehler, "aktionen", f"{wo}: meldung.text ist zu kurz.")
        # Die Meldung ist abgeleitet, nicht abgeschrieben: In meldungen.yaml
        # darf dieselbe Sache nicht ein zweites Mal stehen.
        if m and any(x.get("id") == f"aktion-{kennung}" for x in MELDUNGS_IDS):
            melde(fehler, "aktionen",
                  f"{wo}: 'aktion-{kennung}' steht auch in meldungen.yaml. "
                  f"Die Meldung entsteht aus dieser Datei - dann gibt es sie zweimal.")

        # Ein Bildpfad, der ins Leere zeigt, faellt beim Bauen nicht auf -
        # nur im Browser, als leerer Kasten. Also hier nachsehen.
        bild = a.get("bild")
        if bild:
            datei = ROOT / bild.lstrip("/")
            if not datei.exists():
                melde(fehler, "aktionen", f"{wo}: bild '{bild}' gibt es nicht unter "
                                          f"website{bild}.")
            elif not (a.get("bild_alt") or "").strip():
                melde(fehler, "aktionen", f"{wo}: bild ohne bild_alt. Ohne Beschreibung "
                                          f"ist das Motiv fuer Vorlesegeraete nicht da.")
            elif datei.suffix == ".svg":
                inhalt = datei.read_text(encoding="utf-8", errors="replace")
                # Ein Loop, der sich nicht abschalten laesst, ist auf einer
                # Seite mit Formular eine Zumutung - und ein Verstoss gegen
                # WCAG 2.2.2, sobald er laenger als fuenf Sekunden laeuft.
                if "prefers-reduced-motion" not in inhalt:
                    melde(fehler, "aktionen",
                          f"{wo}: '{bild}' ist bewegt, kennt aber kein "
                          f"prefers-reduced-motion. Wer Bewegung abgestellt hat, "
                          f"bekommt sie trotzdem.")
                if "<script" in inhalt.lower():
                    melde(fehler, "aktionen", f"{wo}: '{bild}' enthaelt ein Skript. "
                                              f"Ein Bild fuehrt nichts aus.")

        # Die Bitte ist freiwillig - aber wenn sie dasteht, darf sie keine
        # Bedingung sein. Ein Code gegen eine Bewertung waere im Play Store
        # ein Verstoss gegen die Programmrichtlinien, und unabhaengig davon
        # das Gegenteil von dem, was hier gemeint ist.
        if a.get("laeuft") and not (a.get("knopftext") or "").strip():
            melde(warnungen, "aktionen",
                  f"{wo}: kein knopftext. Der Knopf heisst dann 'Zur Aktion' - "
                  f"richtig, aber nichtssagend.")

        b = a.get("bitte") or {}
        if b:
            if not b.get("titel") or not b.get("text"):
                melde(fehler, "aktionen", f"{wo}: bitte braucht titel und text.")
            zusammen = " ".join(str(v) for v in b.values())
            for wort in ("nur wenn", "voraussetzung", "verpflichte", "muss.*bewerten",
                         "gegen eine Bewertung", "im Gegenzug"):
                if re.search(wort, zusammen, re.I):
                    melde(fehler, "aktionen",
                          f"{wo}: die bitte klingt nach einer Bedingung ('{wort}'). "
                          f"Ein Code gegen eine Bewertung ist im Play Store nicht "
                          f"erlaubt - und war hier auch nie gemeint.")

        einl = a.get("einloesen")
        if einl and not isinstance(einl, list):
            melde(warnungen, "aktionen", f"{wo}: einloesen sollte eine Liste von Schritten "
                                         f"sein, kein Fliesstext.")

        # --- Die Prueffrage ------------------------------------------------
        antworten = a.get("antworten") or []
        richtige = [x for x in antworten if isinstance(x, dict) and x.get("richtig")]
        if len(antworten) < 3:
            melde(fehler, "aktionen", f"{wo}: mindestens drei Antwortmoeglichkeiten. Bei "
                                      f"zweien raet man mit 50 Prozent richtig.")
        if len(richtige) != 1:
            melde(fehler, "aktionen", f"{wo}: genau EINE Antwort muss 'richtig: true' "
                                      f"tragen, hier sind es {len(richtige)}.")
        texte = [str(x.get("text", "")).strip() for x in antworten if isinstance(x, dict)]
        if len(set(texte)) != len(texte):
            melde(fehler, "aktionen", f"{wo}: zwei Antworten sind wortgleich.")
        if any(not t for t in texte):
            melde(fehler, "aktionen", f"{wo}: eine Antwort hat keinen Text.")

        # --- Datenschutz ---------------------------------------------------
        for feld in ("zweck", "rechtsgrundlage", "frist", "wo"):
            if not str(a.get(feld) or "").strip():
                melde(fehler, "aktionen", f"{wo}: {feld} fehlt - ohne diese Angabe ist der "
                                          f"Datenschutzabschnitt unvollstaendig.")
        if not (a.get("daten") or []):
            melde(fehler, "aktionen", f"{wo}: keine Angabe, WELCHE Daten verarbeitet werden. "
                                      f"Genau das will der Leser wissen.")

        zb = a.get("zeigen_bis")
        if not zb:
            melde(fehler, "aktionen", f"{wo}: zeigen_bis fehlt. Ohne das Datum weiss niemand, "
                                      f"wann der Abschnitt weg darf.")
        elif str(zb) < heute:
            melde(abgleich, "aktionen",
                  f"{wo}: zeigen_bis war am {zb}. Die Speicherfristen sind um - der Eintrag "
                  f"kann aus aktionen.yaml entfernt werden.")

        if a.get("ende") and a.get("laeuft"):
            melde(warnungen, "aktionen", f"{wo}: hat ein Ende, steht aber auf laeuft: true. "
                                         f"Eines von beidem stimmt nicht.")

        # --- Die richtige Antwort verlaesst das Modell ---------------------
        #
        # In der YAML steht, welche Antwort stimmt. In campaigns.json darf das
        # NICHT stehen: Die Datei wird ausgeliefert, und 'richtig: true' im
        # Quelltext waere die Antwort auf dem Silbertablett.
        #
        # Stattdessen ein SHA-256 der richtigen Antwort. Damit kann die Seite
        # eine getippte Antwort pruefen, ohne sie zu kennen. Das ist KEINE
        # Sicherheit - bei vier Moeglichkeiten hat man alle vier in einer
        # Minute durchgerechnet. Es sorgt nur dafuer, dass die Antwort nicht
        # beim ersten Blick in den Quelltext dasteht. Die eigentliche Pruefung
        # macht der Server.
        if richtige:
            wort = str(richtige[0].get("text", "")).strip().lower().rstrip(".")
            a["antwortpruefung"] = hashlib.sha256(wort.encode("utf-8")).hexdigest()
        # Die Markierung selbst raus, und mischen: Eine feste Reihenfolge
        # spricht sich sonst herum ("immer die erste").
        a["antworten"] = [str(x.get("text", "")) for x in antworten if isinstance(x, dict)]
        random.shuffle(a["antworten"])

    return eintraege


def meldungen_aus_aktionen(aktionen, meldungen):
    """Haengt jede laufende Aktion als Meldung an den Feed.

    WARUM ABGELEITET UND NICHT GESCHRIEBEN
    Eine Aktion hoert wieder auf. Stuende ihre Meldung von Hand in
    meldungen.yaml, muesste jemand daran denken, sie zu entfernen - und
    genau das ist an dieser Website schon einmal schiefgegangen. So
    verschwindet sie mit 'laeuft: false' von selbst, in einem einzigen
    Handgriff, an einer einzigen Stelle.

    Die Meldung wird NICHT geprueft wie die anderen: Sie hat kein Release,
    keine Version und kein Datum aus einem Produkt. Ihr Datum ist der Start
    der Aktion.
    """
    zusatz = []
    for a in aktionen:
        if not a.get("laeuft"):
            continue
        m = a.get("meldung") or {}
        if not m.get("titel"):
            continue
        zusatz.append({
            "id": f"aktion-{a['id']}",
            "typ": "hinweis",
            "produkt": a.get("produkt"),
            "datum": str(a.get("start") or date.today().isoformat()),
            "datumQuelle": "Start der Aktion",
            "titel": m["titel"],
            "text": m["text"],
            "hervorgehoben": True,
            # Dieselbe Form wie bei den anderen Meldungen: ein Verzeichnis
            # mit benannten Wegen, keine Liste. Eine Liste haette die Seite
            # stillschweigend uebersprungen - sie fragt nach wege.store & Co.
            "wege": {"aktion": f"/aktion/{a['id']}/"},
        })
    # Wieder nach Datum sortieren, sonst haengt die Aktion am Ende des Feeds.
    return sorted(meldungen + zusatz, key=lambda m: m["datum"], reverse=True)


# ------------------------------------------------ Namen, die nicht hierhin duerfen
#
# Dieses Repository ist oeffentlich. Am 21.07.2026 stellte sich heraus, dass in
# einem Steckbrief das Kuerzel eines Auftraggebers stand - in 'fassung' und in
# zwei Belegpfaden. Es war zwei Commits lang veroeffentlicht, bevor es auffiel.
#
# WARUM HIER NUR PRUEFSUMMEN STEHEN
# Eine Liste verbotener Woerter im Klartext waere selbst die Veroeffentlichung,
# die sie verhindern soll - und zwar in derselben Datei, die jeder lesen kann.
# Deshalb steht hier nur der SHA-256 des kleingeschriebenen Wortes. Der Pruefer
# erkennt es damit, ohne es zu kennen.
#
# Eintragen: python3 -c "import hashlib;print(hashlib.sha256('wort'.lower().encode()).hexdigest())"
# und die Zeile dann in 00_Steuerung/ vermerken - NICHT hier.
GESPERRTE_WOERTER = {
    "4b65e6600443ba9aa64d6031133670f0dca1e68606ed8eab3291dad87eb7d571":
        "Kuerzel eines Auftraggebers (SchichtFuchsHTML). Bei dieser Anwendung "
        "wird der Auftraggeber grundsaetzlich nicht benannt - weder auf der "
        "Seite noch in Datenschutzdaten oder Abgleichdokumenten.",
}


def pruefe_gesperrte_woerter():
    """Durchsucht alle Textquellen nach Woertern, die nicht veroeffentlicht werden.

    Grob und absichtlich stumpf: Jedes Wort ab drei Zeichen wird gehasht und
    gegen die Liste gehalten. Das kostet eine knappe Sekunde und faengt genau
    den Fall, der am 21.07.2026 durchgerutscht ist - ein Kuerzel, das niemand
    fuer heikel hielt, weil es nur drei Buchstaben sind.

    Binaerdateien bleiben aussen vor: In komprimierten Bilddaten steht jede
    kurze Buchstabenfolge irgendwann zufaellig, das gaebe nur Fehlalarme.
    (Nachgeprueft am 21.07.: zwei PNGs enthielten die Bytefolge, die Bilder
    selbst zeigten nichts dergleichen.)
    """
    if not GESPERRTE_WOERTER:
        return
    ordner = [SRC, ROOT / "data" / "schema"]
    for basis in ordner:
        if not basis.exists():
            continue
        for datei in basis.rglob("*"):
            if not datei.is_file() or datei.suffix not in {".yaml", ".yml", ".json", ".md"}:
                continue
            text = datei.read_text(encoding="utf-8", errors="replace")
            for wort in set(re.findall(r"[A-Za-zÄÖÜäöüß]{3,}", text)):
                schluessel = hashlib.sha256(wort.lower().encode("utf-8")).hexdigest()
                grund = GESPERRTE_WOERTER.get(schluessel)
                if grund:
                    melde(fehler, "gesperrt",
                          f"{datei.relative_to(ROOT)}: enthaelt ein Wort, das nicht "
                          f"veroeffentlicht werden darf. {grund}")


def pruefe_steckbrief_sichtbar(steckbriefe):
    """Meldet Steckbrief-Angaben, die keine Seite jemals anzeigt.

    Am 21.07.2026 stand im SnapFuchs-Steckbrief unter 'fremde_dienste' ein
    Feld 'telemetrie' mit dem Wortlaut zur Play-Abrechnungsbibliothek. Es war
    sauber gepflegt, geprueft und - unsichtbar: datenschutz.astro gab nur
    'name' und 'wofuer' aus.

    Das ist die schlechteste aller Lagen. Fehlt eine Angabe ganz, faellt es
    beim Lesen auf. Steht sie im Modell und wird nicht gezeigt, glauben alle
    Beteiligten, der Punkt sei erklaert - und die App verlinkt derweil auf
    eine 'vollstaendige Fassung', in der er fehlt.

    Deshalb: Jedes Feld, das hier gepflegt wird, muss in der Vorlage
    vorkommen. Die Pruefung ist grob (Textsuche), aber sie faengt genau den
    Fall, um den es geht: ein Feld, das niemand ausgibt.
    """
    vorlage = ROOT.parent / "astro" / "src" / "pages" / "datenschutz.astro"
    if not vorlage.exists():
        return
    inhalt = vorlage.read_text(encoding="utf-8", errors="replace")

    gesehen = set()
    for sb in steckbriefe:
        for d in sb.get("fremde_dienste") or []:
            if isinstance(d, dict):
                gesehen.update(d.keys())
        for u in sb.get("uebertragung") or []:
            if isinstance(u, dict):
                gesehen.update(u.keys())

    for feld in sorted(gesehen):
        if feld not in inhalt:
            melde(warnungen, "datenschutz",
                  f"Das Feld '{feld}' wird in Steckbriefen gepflegt, kommt aber in "
                  f"datenschutz.astro nicht vor - es steht also im Modell und auf "
                  f"keiner Seite. Entweder ausgeben oder aus den Steckbriefen "
                  f"entfernen; gepflegt und unsichtbar ist die schlechteste Lage.")


def pruefe_alte_adressen(produkte):
    """Jede 'alt_html' muss auf eine Datei zeigen, die es wirklich gibt.

    Die Weiterleitung entsteht aus diesem Feld. Steht dort ein Tippfehler,
    baut Astro eine Weiterleitung fuer eine Adresse, die nie jemand aufruft -
    und die echte alte Adresse bleibt ohne Ziel. Beides faellt nirgends auf:
    Der Bau laeuft durch, die Seite sieht gut aus, nur fremde Links landen im
    Nichts.

    Umgekehrt gilt es auch: Liegt unter apps/ eine Datei, auf die kein Produkt
    zeigt, fehlt entweder eine Weiterleitung oder das Produkt ist weg. Das
    meldet astro/tools/weiterleitungen-pruefen.mjs - hier geht es nur um die
    Richtung Modell -> Datei.
    """
    for p in produkte:
        alt = (p.get("links") or {}).get("alt_html")
        if not alt:
            continue
        if not (ROOT / alt.lstrip("/")).exists():
            melde(fehler, p["slug"],
                  f"links.alt_html zeigt auf {alt} - diese Datei gibt es nicht. "
                  f"Dann entsteht eine Weiterleitung fuer eine Adresse, die "
                  f"niemand aufruft, und die echte bleibt ohne Ziel.")
        if alt == f"/produkte/{p['slug']}/" or not alt.endswith(".html"):
            melde(fehler, p["slug"],
                  f"links.alt_html ist '{alt}'. Hier gehoert die ALTE "
                  f"Adresse hin (eine .html-Datei), nicht die heutige Seite.")


def pruefe_altbestand():
    """Wacht ueber die Grenze, die am 20.07.2026 gezogen wurde.

    Seit dem Umschalten liefert deploy-neu.yml ausschliesslich astro/dist
    aus. Was hier im Wurzelverzeichnis liegt, wird NICHT mehr veroeffentlicht
    - sieht aber aus wie eine Website und stand zuletzt auf dem Stand vom
    19.07. Genau daran ist am 21.07. jemand haengengeblieben.

    Zwei Regeln, beide aus demselben Vorfall:
    """
    # 1. Keine HTML-Datei im Wurzelverzeichnis. Sie waere entweder tot oder
    #    ein zweiter Ort fuer eine Aussage, die im Datenmodell steht.
    for datei in sorted(ROOT.glob("*.html")):
        melde(fehler, "altbestand",
              f"{datei.name} liegt im Wurzelverzeichnis. Ausgeliefert wird nur "
              f"astro/dist - die Datei ist also entweder tot oder ein zweiter Ort "
              f"fuer etwas, das im Datenmodell steht. Nach 90_Archiv/website-1.0/.")

    # 2. Der alte 1:1-Upload darf nicht in .github/workflows/ liegen. Sein
    #    push-Ausloeser war auskommentiert, workflow_dispatch aber nicht -
    #    ein Klick auf "Run workflow" haette die neue Website mit dem alten
    #    Stand ueberschrieben. Auskommentieren reicht hier nicht.
    for datei in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        if datei.name == "deploy-neu.yml":
            continue
        inhalt = datei.read_text(encoding="utf-8", errors="replace")
        if "upload-pages-artifact" in inhalt and "astro" not in inhalt:
            melde(fehler, "altbestand",
                  f".github/workflows/{datei.name} laedt das Repository direkt zu "
                  f"Pages hoch, ohne astro zu bauen. Auf Knopfdruck ueberschreibt "
                  f"das die Website mit dem Altbestand. Nach 90_Archiv/.")

    # 3. Die alten Produktseiten unter apps/ bleiben, wo sie sind.
    #
    #    Das sieht nach Altbestand aus und ist trotzdem keiner: Sie sind die
    #    BESTANDSLISTE, aus der astro/tools/weiterleitungen-pruefen.mjs
    #    ableitet, welche alten Adressen ein Ziel brauchen. Verschwinden sie,
    #    verliert der Pruefer seine Grundlage und meldet Entwarnung, waehrend
    #    fremde Links ins Leere laufen - der schlimmste aller Zustaende,
    #    weil ihn niemand bemerkt.
    #
    #    Ausgeliefert werden sie nicht (nur astro/dist geht zu Pages). Sie
    #    kosten also nichts ausser dem Platz und diesem Absatz.
    alte = list((ROOT / "apps").glob("*.html")) if (ROOT / "apps").exists() else []
    if len(alte) < 10:
        melde(fehler, "altbestand",
              f"unter apps/ liegen nur noch {len(alte)} alte Produktseiten. Sie sind "
              f"die Bestandsliste fuer weiterleitungen-pruefen.mjs - fehlen sie, "
              f"prueft er nichts mehr und meldet trotzdem 'alles gut'. "
              f"Nicht aufraeumen, auch wenn sie nach Altbestand aussehen.")

    # 4. Dieselbe Luecke hatten robots.txt, sitemap.xml und der Feed.
    #
    #    Alle drei sind unsichtbar, solange sie fehlen: Die Seite sieht gut
    #    aus, kein Prueflauf schlaegt an, nur Suchmaschinen und Feedleser
    #    finden nichts. robots.txt und sitemap.xml lagen bis zum 21.07.2026
    #    im Wurzelverzeichnis und wurden seit dem Umschalten nicht mehr
    #    ausgeliefert; einen Feed gab es nie.
    seiten = ROOT.parent / "astro" / "src" / "pages"
    if seiten.exists():
        for datei, wozu in [
            ("sitemap.xml.js", "Suchmaschinen finden die neuen Adressen nicht"),
            ("robots.txt.js", "es gibt keine Sitemap-Angabe und keine Sperre "
                              "fuer die Werkstatt"),
            ("feed.xml.js", "wer FehlerFuchs verfolgen will, braucht ein Konto "
                            "bei irgendeiner Plattform"),
        ]:
            if not (seiten / datei).exists():
                melde(fehler, "altbestand",
                      f"astro/src/pages/{datei} fehlt - {wozu}. Faellt sonst "
                      f"niemandem auf: Die Website sieht ohne sie genauso aus.")

    # 5. Es MUSS eine 404 geben. Sie lag bis zum 20.07. hier als 404.html und
    #    wurde beim Umzug schlicht vergessen - fuenf Tage lang bekam jeder
    #    Tippfehler die graue GitHub-Standardseite auf Englisch.
    astro = ROOT.parent / "astro" / "src" / "pages" / "404.astro"
    if astro.parent.exists() and not astro.exists():
        melde(fehler, "altbestand",
              "astro/src/pages/404.astro fehlt. GitHub Pages liefert dann seine "
              "eigene englische Fehlerseite aus - ohne Marke und ohne Weg zurueck.")


def pruefe_bedarf(eintraege):
    """Prüft den Betriebsbedarf für die Unterstützen-Seite.

    Wenig Regeln, aber jede davon ist an einem realen Fehler entstanden:
    Die alte Seite führte den Betrag zweimal (Zeile und 'Schätzkosten:'-Note)
    und die Wege standen als Verweise im Markup statt in den Daten. Beides
    ist hier abgeleitet – aus 'art' folgt, welche Hilfe-Wege angeboten werden.
    """
    gesehen = set()

    for e in eintraege:
        kennung = e.get("id", "?")

        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(kennung)):
            melde(fehler, "bedarf", f"'{kennung}': id nur klein, Ziffern und Bindestriche "
                                    "– sie wird zum Sprungziel in der Adresse.")
        if kennung in gesehen:
            melde(fehler, "bedarf", f"'{kennung}': id kommt doppelt vor.")
        gesehen.add(kennung)

        if e.get("art") not in BEDARF_ARTEN:
            melde(fehler, "bedarf", f"'{kennung}': art '{e.get('art')}' unbekannt. "
                                    f"Erlaubt: {', '.join(sorted(BEDARF_ARTEN))}.")
        if e.get("status") not in BEDARF_STATUS:
            melde(fehler, "bedarf", f"'{kennung}': status '{e.get('status')}' unbekannt. "
                                    f"Erlaubt: {', '.join(sorted(BEDARF_STATUS))}.")

        text = (e.get("text") or "").strip()
        if len(text) < 40:
            melde(fehler, "bedarf", f"'{kennung}': text fehlt oder ist zu kurz. "
                                    "Er soll sagen, WOZU es gebraucht wird.")
        if IBAN_MUSTER.search(text) or IBAN_MUSTER.search(e.get("titel", "")):
            melde(fehler, "bedarf", f"'{kennung}': sieht nach einer Bankverbindung aus. "
                                    "Die steht einmal in marke.yaml, sonst nirgends.")

        # FehlerFuchs ist ein Gewerbe, keine gemeinnützige Einrichtung. Wer
        # „Spende" liest, erwartet eine Zuwendungsbestätigung – die es nicht
        # geben kann. Bis zum 20.07.2026 stand „Sachspende" auf sechs
        # Merkzeichen der Unterstützen-Seite.
        if re.search(r"(?i)spende", e.get("titel", "") + " " + text):
            melde(fehler, "bedarf", f"'{kennung}': das Wort 'Spende' gehört hier nicht hin. "
                                    "FehlerFuchs kann keine Spenden im Rechtssinn "
                                    "entgegennehmen – es geht um Beitrag, Gerät, "
                                    "Sponsoring oder Zeit.")

        if e.get("zeichen") not in BEDARF_ZEICHEN:
            melde(fehler, "bedarf", f"'{kennung}': zeichen '{e.get('zeichen')}' gibt es nicht. "
                                    f"Vorhanden: {', '.join(sorted(BEDARF_ZEICHEN))}.")

        # Betrag und Art müssen zusammenpassen, sonst steht auf der Seite ein
        # Preisschild an einer Bitte um Zeit – oder umgekehrt ein Gerät ohne
        # jede Angabe, was es ungefähr kostet.
        von, bis = e.get("von"), e.get("bis")
        if e.get("art") == "zeit" and von is not None:
            melde(warnungen, "bedarf", f"'{kennung}': art ist 'zeit', trotzdem steht ein Betrag.")
        if e.get("art") in {"beitrag", "geraet"} and von is None:
            melde(warnungen, "bedarf", f"'{kennung}': kein Betrag. Ohne Größenordnung "
                                       "kann niemand einschätzen, ob er helfen kann.")

        # 'zahlbar' merkt sich, ob mit den Beträgen gerechnet werden darf.
        # Ohne diese Klammer stürzte der Lauf bei 'von: "fuenfhundert"' in
        # betrag_text ab, mit einem ValueError aus der Zahlenformatierung –
        # einem Abbruch, der nicht sagt, welcher Eintrag schuld ist. Eine
        # Prüfung, die abstürzt statt zu melden, ist keine Prüfung.
        zahlbar = True
        if von is not None:
            if not isinstance(von, int) or isinstance(von, bool) or von <= 0:
                melde(fehler, "bedarf", f"'{kennung}': von muss eine ganze Zahl über null "
                                        f"sein, steht aber als {von!r} da.")
                zahlbar = False
            if bis is not None:
                if not isinstance(bis, int) or isinstance(bis, bool):
                    melde(fehler, "bedarf", f"'{kennung}': bis muss eine ganze Zahl sein, "
                                            f"steht aber als {bis!r} da.")
                    zahlbar = False
                elif zahlbar and bis <= von:
                    melde(fehler, "bedarf", f"'{kennung}': bis ({bis}) muss größer sein als "
                                            f"von ({von}) – sonst ist es keine Spanne.")
            if e.get("takt") not in BEDARF_TAKTE:
                melde(fehler, "bedarf", f"'{kennung}': takt '{e.get('takt')}' unbekannt. "
                                        f"Erlaubt: {', '.join(BEDARF_TAKTE)}.")
                zahlbar = False
        elif e.get("takt"):
            melde(warnungen, "bedarf", f"'{kennung}': takt ohne Betrag ergibt keinen Sinn.")

        # Abgeleitet, nicht erfasst.
        e["betrag"] = betrag_text(e) if zahlbar else ""

    return eintraege


def bedarf_summen(eintraege):
    """Was insgesamt offen ist, getrennt nach Takt.

    Einmalige und laufende Kosten zu addieren wäre eine Zahl, die nichts
    bedeutet: 1.500 € für ein Gerät und 185 € im Monat sind nicht dasselbe
    Geld. Deshalb drei Summen statt einer großen.
    """
    offen = [e for e in eintraege if e.get("status") != "erfuellt"
             and isinstance(e.get("von"), int) and not isinstance(e.get("von"), bool)]
    s = {}
    for takt in BEDARF_TAKTE:
        posten = [e for e in offen if e.get("takt") == takt]
        if not posten:
            continue
        s[takt] = {
            "posten": len(posten),
            "von": sum(e["von"] for e in posten),
            "bis": sum(e.get("bis") or e["von"] for e in posten),
        }
        s[takt]["text"] = betrag_text({
            "von": s[takt]["von"],
            "bis": s[takt]["bis"] if s[takt]["bis"] != s[takt]["von"] else None,
            "takt": takt,
        })
    return s


def pruefe_wuensche(wuensche, produkte, vokabular, schema):
    """Prüft die freigegebenen Wünsche.

    Der Kern ist die Suche nach personenbezogenen Daten. Die Datei liegt in
    einem öffentlichen Repository und wird von GitHub Pages ausgeliefert –
    was hier hineingerät, ist im Netz, und zwar dauerhaft. Deshalb ist ein
    Fund hier ein FEHLER und keine Warnung: Der Lauf bricht ab, es wird
    nichts geschrieben.
    """
    slugs = {p["slug"] for p in produkte}
    gesehen = set()
    echte = 0

    for w in wuensche:
        wid = w.get("id", "?")
        wo = f"wunsch {wid}"
        pruefe_gegen_schema(w, schema, "", wo)

        if wid in gesehen:
            melde(fehler, wo, "diese id gibt es schon ein zweites Mal")
        gesehen.add(wid)
        if not w.get("platzhalter"):
            echte += 1

        # --- Kein Personenbezug in veröffentlichten Feldern ---------------
        for feld in ("titel", "text", "alias"):
            wert = w.get(feld) or ""
            for muster, was in PERSONENBEZUG:
                if muster.search(wert):
                    melde(fehler, wo, f"{feld} enthält {was}. Diese Datei wird "
                                      f"veröffentlicht – personenbezogene Angaben gehören "
                                      f"ausschließlich in die Benachrichtigungs-Mail.")
        for muster, was in PERSONENBEZUG:
            if muster.search((w.get("kommentar") or {}).get("text", "")):
                melde(fehler, wo, f"der Kommentar enthält {was} – siehe oben")

        # --- Vokabular ----------------------------------------------------
        if w.get("thema") not in vokabular.get("wunschThema", {}):
            melde(fehler, wo, f"thema '{w.get('thema')}' hat keinen Anzeigetext in "
                              f"vokabular.yaml → wunschThema")
        if w.get("status") not in vokabular.get("wunschStatus", {}):
            melde(fehler, wo, f"status '{w.get('status')}' hat keinen Anzeigetext in "
                              f"vokabular.yaml → wunschStatus")

        # --- Produktbezüge ------------------------------------------------
        if w.get("thema") == "wunsch-bestehend" and not w.get("produkt"):
            melde(warnungen, wo, "Thema ist 'Wunsch zu einer FehlerFuchs-Anwendung', "
                                 "aber es steht nicht dabei, zu welcher")
        if w.get("produkt") and w["produkt"] not in slugs:
            melde(fehler, wo, f"produkt '{w['produkt']}' gibt es im Modell nicht")
        if w.get("produkt") and w.get("thema") != "wunsch-bestehend":
            melde(warnungen, wo, "produkt gesetzt, obwohl das Thema kein Wunsch zu einer "
                                 "bestehenden Anwendung ist")
        if w.get("ergebnis"):
            if w["ergebnis"] not in slugs:
                melde(fehler, wo, f"ergebnis '{w['ergebnis']}' gibt es im Modell nicht")
            if w.get("status") != "umgesetzt":
                melde(fehler, wo, "ergebnis gesetzt, aber der Status ist nicht 'umgesetzt' – "
                                  "das widerspricht sich")

        # --- Ein Status ohne Erklärung lässt den Einreicher raten -----------
        if w.get("status") in ("umgesetzt", "nicht-umsetzbar") and not w.get("kommentar"):
            melde(warnungen, wo, f"Status '{w['status']}' ohne Kommentar. Gerade bei einem "
                                 f"Nein möchte man wissen, warum.")
        if w.get("status") == "umgesetzt" and not w.get("ergebnis"):
            melde(warnungen, wo, "als umgesetzt markiert, aber es steht nicht dabei, "
                                 "woraus – der Kreis bleibt offen")

        # --- Zeitliche Plausibilität ---------------------------------------
        k = w.get("kommentar")
        if k and w.get("eingereicht") and k["datum"] < w["eingereicht"]:
            melde(fehler, wo, f"der Kommentar ({k['datum']}) ist älter als die Einreichung "
                              f"({w['eingereicht']})")

    # --- Platzhalter sind zum Wegwerfen gedacht ---------------------------
    platzhalter = [w for w in wuensche if w.get("platzhalter")]
    if platzhalter and echte:
        melde(warnungen, "wuensche", f"{len(platzhalter)} Platzhalter stehen neben "
                                     f"{echte} echten Wünschen – die Beispiele können weg")

    return sorted(wuensche, key=lambda w: (w.get("eingereicht", ""), w.get("id", "")), reverse=True)


# --------------------------------------------------------- Abgleich mit der Website
#
# HIER STAND EINMAL abgleich_mit_website().
#
# Sie las die ausgelieferten HTML-Dateien im Wurzelverzeichnis und meldete,
# wenn Modell und Seite auseinanderliefen: fehlende Release-Links, fehlende
# Store-Adressen, nicht verlinkte Zubehoerteile, Akzentfarben.
#
# Diese Pruefung ist seit dem 20.07.2026 gegenstandslos. Die Seiten werden aus
# demselben Datenmodell erzeugt, gegen das sie geprueft haetten - sie KOENNEN
# nicht mehr auseinanderlaufen. Ein Release, das im Modell steht, steht auf der
# Seite; steht es nicht im Modell, gibt es keine Seite dafuer.
#
# Aufgefallen ist das erst, als die alten HTML-Dateien ins Archiv gingen: Die
# Funktion stuerzte mit FileNotFoundError auf downloads.html ab. Bis dahin lief
# sie taeglich mit und pruefte Dateien, die niemand mehr ausliefert - sie haette
# also jederzeit Entwarnung fuer eine Seite geben koennen, die es nicht gibt.
#
# Was von ihr sinnvoll bleibt, ist an anderer Stelle aufgehoben:
#   - "hat noch keine eigene Produktseite"  -> 'customPage' und der Slug regeln das
#   - "Release ohne Meldung"                -> pruefe_meldungen, Regel 5
#   - "Zubehoer nicht verlinkt"             -> die Elternseite leitet es ab
#   - "Store-Adresse fehlt"                 -> store_adresse_ableiten
#
# Wer hier wieder etwas gegen eine gebaute Seite pruefen will, tut das in
# astro/tools/ gegen astro/dist - nicht hier gegen Dateien im Wurzelverzeichnis.


# ------------------------------------------------------------------------- Ablauf

def main():
    nur_pruefen = "--check" in sys.argv

    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    meldung_schema = json.loads(MELDUNG_SCHEMA_FILE.read_text(encoding="utf-8"))
    wunsch_schema = json.loads(WUNSCH_SCHEMA_FILE.read_text(encoding="utf-8"))
    statuses = lies_yaml(SRC / "statuses.yaml")
    vokabular = lies_yaml(SRC / "vokabular.yaml")
    marke = lies_yaml(SRC / "marke.yaml")

    dateien = sorted((SRC / "products").glob("*.yaml"))
    if not dateien:
        sys.exit("FEHLER: keine Produktdateien unter data/src/products/ gefunden")

    produkte = []
    for f in dateien:
        try:
            p = lies_yaml(f)
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            stelle = f" (Zeile {mark.line + 1}, Spalte {mark.column + 1})" if mark else ""
            fehler.append(f"{f.name}: YAML lässt sich nicht lesen{stelle} – "
                          f"{getattr(e, 'problem', e)}. Häufigste Ursache: ein Doppelpunkt "
                          f"mitten im Text. Solche Werte in Anführungszeichen setzen "
                          f"oder als Block mit '>-' schreiben.")
            continue
        if not isinstance(p, dict) or "slug" not in p:
            fehler.append(f"{f.name}: keine gültige Produktdatei (slug fehlt)")
            continue
        if p["slug"] != f.stem:
            melde(fehler, p["slug"], f"Dateiname {f.name} passt nicht zum slug '{p['slug']}'")
        pruefe_gegen_schema(p, schema, "", p["slug"])
        produkte.append(p)

    slugs = {p["slug"] for p in produkte}
    if len(slugs) != len(produkte):
        fehler.append("mehrere Produkte teilen sich denselben slug")

    meldungen, wuensche, steckbriefe, verarbeiter, bedarf = [], [], [], [], []
    aktionen = []
    if not fehler:
        for p in produkte:
            pruefe_vokabular(p, vokabular)
            pruefe_inhalt(p, statuses, slugs, produkte)
            store_adresse_ableiten(p)
            pruefe_freitext_zusagen(p)

        roh = lies_yaml(SRC / "meldungen.yaml")
        meldungen = pruefe_meldungen(roh.get("meldungen", []), produkte, meldung_schema)
        MELDUNGS_IDS.extend(meldungen)

        rohd = lies_yaml(SRC / "dienste.yaml") or {}
        dienste = pruefe_dienste(rohd.get("dienste", []), produkte)
        # Auftragsverarbeiter stehen in derselben Datei, gehen aber nicht durch
        # pruefe_dienste: Sie haben kein 'produkte' und keinen 'stand' je Dienst.
        verarbeiter = rohd.get("auftragsverarbeiter", [])

        steckbriefe = pruefe_steckbriefe(produkte, dienste)

        rohw = lies_yaml(SRC / "wuensche.yaml")
        wuensche = pruefe_wuensche(rohw.get("wuensche", []), produkte, vokabular, wunsch_schema)

        roha = lies_yaml(SRC / "aktionen.yaml") or {}
        aktionen = pruefe_aktionen(roha.get("aktionen", []), produkte)
        meldungen = meldungen_aus_aktionen(aktionen, meldungen)

        rohb = lies_yaml(SRC / "bedarf.yaml") or {}
        bedarf = pruefe_bedarf(rohb.get("bedarf", []))

        pruefe_gesperrte_woerter()
        pruefe_steckbrief_sichtbar(steckbriefe)
        pruefe_alte_adressen(produkte)
        pruefe_altbestand()
        pruefe_alle_svg()
        pruefe_fremdziele(rohd, produkte, marke)

    # Ein Zahlungsweg ohne Datenschutzangabe.
    #
    # Am 20.07.2026 ging die neue Unterstützen-Seite mit PayPal-Knopf und
    # Bankverbindung online, und in der Datenschutzerklärung stand davon kein
    # Wort — obwohl die ALTE Seite denselben Knopf schon lange hatte. Es fiel
    # nur auf, weil ich zufällig danach suchte.
    #
    # Wer Geld entgegennimmt, verarbeitet personenbezogene Daten: Name, Betrag,
    # bei PayPal die E-Mail, bei Überweisung die IBAN. Das muss dastehen.
    u = marke.get("unterstuetzung") or {}
    if u.get("paypal") or u.get("bank"):
        d = u.get("datenschutz") or {}
        if not d.get("paypal", {}).get("name"):
            fehler.append("marke: Es gibt einen Zahlungsweg (unterstuetzung), aber keine "
                          "Angaben unter unterstuetzung.datenschutz.paypal. Ohne sie fehlt "
                          "der Abschnitt auf der Datenschutzseite.")
        if not d.get("aufbewahrung"):
            fehler.append("marke: unterstuetzung.datenschutz.aufbewahrung fehlt. "
                          "Zahlungseingänge sind Buchungsbelege — die Frist gehört "
                          "genannt, auch wenn sie unbequem ist.")

    # Die Marke verspricht etwas – die Belege dafür stehen bei den Produkten.
    pt = marke.get("person", {}).get("portrait")
    if pt:
        datei = ROOT / pt["src"].lstrip("/")
        if not datei.exists():
            fehler.append(f"marke: Porträt {pt['src']} gibt es nicht")
        else:
            echt = bildmasse(datei)
            if echt and (echt != (pt.get("width"), pt.get("height"))):
                fehler.append(f"marke: Porträt ist {echt[0]}×{echt[1]}, im Modell steht "
                              f"{pt.get('width')}×{pt.get('height')} – falsche Maße "
                              f"verzerren das Bild oder schneiden es falsch zu")
    if not marke.get("leitsaetze"):
        fehler.append("marke: keine Leitsätze hinterlegt – die Startseite hätte keine Botschaft")

    breite = 74
    for titel, liste in (("FEHLER", fehler), ("WARNUNG", warnungen), ("ABGLEICH", abgleich)):
        if liste:
            print(f"\n{titel} ({len(liste)})")
            print("-" * breite)
            for z in liste:
                print(f"  {z}")

    if fehler:
        print(f"\nAbbruch: {len(fehler)} Fehler. Es wurde nichts geschrieben.")
        return 1

    print(f"\nGeprüft: {len(produkte)} Produkte, {len(meldungen)} Meldungen, "
          f"{len(wuensche)} Wünsche, {len(bedarf)} Bedarfsposten, "
          f"{len(steckbriefe)} Steckbriefe, {len(statuses)} Statusstufen, "
          f"{sum(len(v) for v in vokabular.values())} Vokabeln — keine Fehler.")

    if nur_pruefen:
        print("Nur-Prüfen-Modus: keine Dateien geschrieben.")
        return 0

    kopf = {
        "_hinweis": "ERZEUGTE DATEI – nicht von Hand bearbeiten. Quelle: data/src/. "
                    "Neu erzeugen mit: python tools/build_data.py",
        "generiert": datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "schema": "https://fehlerfuchs.eu/data/schema/product.schema.json",
    }
    schreibe(OUT_PRODUCTS, json.dumps(
        {**kopf, "produkte": sorted(produkte, key=lambda p: (statuses[p["status"]]["order"], p["name"]))},
        ensure_ascii=False, indent=2) + "\n")
    schreibe(OUT_STATUSES, json.dumps(
        {**kopf, "statuses": statuses}, ensure_ascii=False, indent=2) + "\n")
    schreibe(OUT_VOKABULAR, json.dumps(
        {**kopf, **vokabular}, ensure_ascii=False, indent=2) + "\n")
    schreibe(OUT_MARKE, json.dumps(
        {**kopf, **marke}, ensure_ascii=False, indent=2) + "\n")
    schreibe(OUT_NEWS, json.dumps(
        {**kopf, "meldungen": meldungen}, ensure_ascii=False, indent=2) + "\n")
    # Zähler gleich mitgeben: Er wird auf der Seite gebraucht und soll nicht
    # dort noch einmal ausgerechnet werden. Platzhalter zählen nicht mit.
    echte = [w for w in wuensche if not w.get("platzhalter")]
    schreibe(OUT_WUENSCHE, json.dumps({**kopf, "wuensche": wuensche, "zaehler": {
        "gesamt": len(echte),
        "neu": sum(1 for w in echte if w["status"] == "neu"),
        "inBearbeitung": sum(1 for w in echte if w["status"] == "in-bearbeitung"),
        "umgesetzt": sum(1 for w in echte if w["status"] == "umgesetzt"),
        "nichtUmsetzbar": sum(1 for w in echte if w["status"] == "nicht-umsetzbar"),
    }}, ensure_ascii=False, indent=2) + "\n")

    schreibe(OUT_AKTIONEN, json.dumps(
        {**kopf, "aktionen": aktionen}, ensure_ascii=False, indent=2) + "\n")

    schreibe(OUT_DIENSTE, json.dumps(
        {**kopf, "dienste": dienste, "auftragsverarbeiter": verarbeiter,
         "fremdziele": rohd.get("fremdziele") or []},
        ensure_ascii=False, indent=2) + "\n")

    # Der Zähler wird hier ausgerechnet und nicht auf der Seite: Sonst steht
    # dieselbe Logik in zwei Sprachen, und beim nächsten neuen Status stimmt
    # eine von beiden nicht mehr.
    schreibe(OUT_BEDARF, json.dumps({**kopf, "bedarf": bedarf, "zaehler": {
        "gesamt": len(bedarf),
        "offen": sum(1 for b in bedarf if b["status"] == "offen"),
        "inArbeit": sum(1 for b in bedarf if b["status"] == "in-arbeit"),
        "erfuellt": sum(1 for b in bedarf if b["status"] == "erfuellt"),
    }, "summen": bedarf_summen(bedarf)},
        ensure_ascii=False, indent=2) + "\n")

    schreibe(OUT_DATENSCHUTZ, json.dumps({**kopf, "steckbriefe": sorted(
        steckbriefe, key=lambda s: (s["art"] != "anwendung", s["name"]))},
        ensure_ascii=False, indent=2) + "\n")

    print(f"Geschrieben: {OUT_PRODUCTS.relative_to(ROOT)}, {OUT_STATUSES.relative_to(ROOT)}, "
          f"{OUT_VOKABULAR.relative_to(ROOT)}, {OUT_MARKE.relative_to(ROOT)}, "
          f"{OUT_NEWS.relative_to(ROOT)}, {OUT_WUENSCHE.relative_to(ROOT)}, "
          f"{OUT_DIENSTE.relative_to(ROOT)}, {OUT_DATENSCHUTZ.relative_to(ROOT)}, "
          f"{OUT_BEDARF.relative_to(ROOT)}, {OUT_AKTIONEN.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
