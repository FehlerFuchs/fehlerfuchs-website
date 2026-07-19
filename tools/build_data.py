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

import json
import re
import struct
import sys
from datetime import date, datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("FEHLER: PyYAML fehlt.  Installation:  pip install pyyaml")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "src"
SCHEMA_FILE = ROOT / "data" / "schema" / "product.schema.json"
OUT_PRODUCTS = ROOT / "data" / "products.json"
OUT_STATUSES = ROOT / "data" / "statuses.json"
OUT_VOKABULAR = ROOT / "data" / "vocabulary.json"
OUT_MARKE = ROOT / "data" / "brand.json"

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


def melde(liste, slug, text):
    liste.append(f"{slug}: {text}")


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


def pruefe_inhalt(p, statuses, alle_slugs):
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
    if "download" in st["cta"] and not hat_download and not nur_web \
            and not p.get("links", {}).get("store"):
        melde(warnungen, slug, f"Status '{p['status']}' erlaubt einen Download, "
                               f"es ist aber weder ein Release noch ein Store-Link hinterlegt")
    if st["cta"] == ["keine"] and p.get("releases"):
        melde(warnungen, slug, f"Status '{p['status']}' erlaubt keine Download-CTA, "
                               f"es sind aber Releases hinterlegt")

    # 5b. Merkmalsmatrix: Spalten müssen zu den Editionen passen
    editions_ids = {e["id"] for e in p.get("editions", [])}
    oeffentliche = {e["id"] for e in p.get("editions", []) if e["public"]}
    namen_gesehen = set()
    for gruppe in p.get("features", []):
        for item in gruppe["items"]:
            if item["name"] in namen_gesehen:
                melde(warnungen, slug, f"Merkmal '{item['name']}' kommt mehrfach vor")
            namen_gesehen.add(item["name"])
            unbekannt = set(item["values"]) - editions_ids
            if unbekannt:
                melde(fehler, slug, f"Merkmal '{item['name'][:40]}…': Spalte(n) "
                                    f"{', '.join(sorted(unbekannt))} sind keine Editionen")
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

    # 5d. Bilder müssen existieren – und die Bildmarke muss zum Namen passen
    medien = p.get("media", {})
    for bezeichnung, bild in list(medien.items()):
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

    # 5e. Ein Titel braucht eine Form: Bildmarke ODER Wortmarke. Ohne beides
    #     steht dort schlichter Text – zulässig, aber es sollte Absicht sein.
    if p["kind"] == "produkt" and not medien.get("lockup") and not p.get("wordmark"):
        melde(warnungen, slug, "weder media.lockup noch wordmark – der Titel erscheint "
                               "als schlichter Text ohne Markenbezug")

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


# --------------------------------------------------------- Abgleich mit der Website

def abgleich_mit_website(produkte):
    """Meldet, wenn Modell und ausgelieferte Seite auseinanderlaufen."""
    # Produkte ohne eigene Seite zeigen auf eine Sammelseite – dort ergeben
    # seitenbezogene Prüfungen keinen Sinn.
    sammelseiten = {"/produkte.html", "/downloads.html", "/index.html"}
    for p in produkte:
        slug = p["slug"]
        eigene_seite = p["links"]["page"] not in sammelseiten
        if not eigene_seite:
            melde(abgleich, slug, "hat noch keine eigene Produktseite "
                                  f"(verweist auf {p['links']['page']})")
            continue
        seite = ROOT / p["links"]["page"].lstrip("/")
        if not seite.exists():
            melde(abgleich, slug, f"Produktseite {p['links']['page']} existiert nicht")
            continue
        html = seite.read_text(encoding="utf-8", errors="replace")

        for r in p.get("releases", []):
            if r is p["releases"][0] and r["url"] not in html and p["links"]["page"] != "/produkte.html":
                melde(abgleich, slug, f"neuestes Release {r['version']} wird auf "
                                      f"{p['links']['page']} nicht verlinkt")

        store = p.get("links", {}).get("store")
        if store and store not in html:
            melde(abgleich, slug, f"Store-Link fehlt auf {p['links']['page']}")

        if p.get("accent") and f'--accent:{p["accent"]}' not in html.replace(" ", ""):
            melde(abgleich, slug, f"Akzentfarbe {p['accent']} steht nicht auf der Produktseite")

    # Zubehör und Editionen müssen von ihrem Hauptprodukt aus erreichbar sein.
    # Sonst steht auf der Elternseite zwar, dass es sie gibt, aber kein Weg dorthin.
    nach_slug = {p["slug"]: p for p in produkte}
    for kind in produkte:
        if not kind.get("parent"):
            continue
        elter = nach_slug.get(kind["parent"])
        if not elter:
            continue
        elternseite = ROOT / elter["links"]["page"].lstrip("/")
        if not elternseite.exists():
            continue
        html = elternseite.read_text(encoding="utf-8", errors="replace")
        ziel = kind["links"]["page"].lstrip("/").split("/")[-1]
        if ziel not in html:
            melde(abgleich, kind["slug"],
                  f"wird von der Seite des Hauptprodukts ({elter['links']['page']}) "
                  f"nicht verlinkt – Besucher finden es dort nicht")

    # Downloadseite: verlinkt sie alle aktuellen Releases?
    dl = (ROOT / "downloads.html").read_text(encoding="utf-8", errors="replace")
    for p in produkte:
        for r in p.get("releases", [])[:1]:
            if r["url"] not in dl:
                melde(abgleich, p["slug"],
                      f"aktuelles Release {r['version']} fehlt auf downloads.html")


# ------------------------------------------------------------------------- Ablauf

def main():
    nur_pruefen = "--check" in sys.argv

    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    statuses = yaml.safe_load((SRC / "statuses.yaml").read_text(encoding="utf-8"))
    vokabular = yaml.safe_load((SRC / "vokabular.yaml").read_text(encoding="utf-8"))
    marke = yaml.safe_load((SRC / "marke.yaml").read_text(encoding="utf-8"))

    dateien = sorted((SRC / "products").glob("*.yaml"))
    if not dateien:
        sys.exit("FEHLER: keine Produktdateien unter data/src/products/ gefunden")

    produkte = []
    for f in dateien:
        try:
            p = yaml.safe_load(f.read_text(encoding="utf-8"))
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

    if not fehler:
        for p in produkte:
            pruefe_vokabular(p, vokabular)
            pruefe_inhalt(p, statuses, slugs)
        abgleich_mit_website(produkte)

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

    print(f"\nGeprüft: {len(produkte)} Produkte, {len(statuses)} Statusstufen, "
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
    OUT_PRODUCTS.write_text(json.dumps(
        {**kopf, "produkte": sorted(produkte, key=lambda p: (statuses[p["status"]]["order"], p["name"]))},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_STATUSES.write_text(json.dumps(
        {**kopf, "statuses": statuses}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_VOKABULAR.write_text(json.dumps(
        {**kopf, **vokabular}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_MARKE.write_text(json.dumps(
        {**kopf, **marke}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Geschrieben: {OUT_PRODUCTS.relative_to(ROOT)}, {OUT_STATUSES.relative_to(ROOT)}, "
          f"{OUT_VOKABULAR.relative_to(ROOT)}, {OUT_MARKE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
