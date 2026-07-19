"""Uebernimmt die eingereichten Datenschutz-Steckbriefe ins Datenmodell.

WARUM ES DIESEN SCHRITT GIBT
============================
Die Projekte reichen ihre Steckbriefe in einem Ordner AUSSERHALB beider Repos
ein. Die Website baut ausschliesslich aus website/data/src/. Dazwischen steht
dieses Werkzeug - und das ist Absicht, kein Umweg:

  * Der Einreichordner wird von vielen Projekten beschrieben. Was dort landet,
    ist Zulieferung, nicht Veroeffentlichung.
  * website/data/src/ wird von GitHub Pages ausgeliefert. Jede Zeile, die hier
    ankommt, steht danach im Netz.

Zwischen "jemand hat etwas eingereicht" und "es steht im Netz" gehoert eine
Pruefung. Diese hier.

WAS GEPRUEFT WIRD (Fund = Abbruch, es wird NICHTS kopiert)
  1. gueltiges YAML
  2. keine IP-Adresse ausser den harmlosen Schleifenadressen
  3. keine Zugangsdaten, Schluessel, Token, Passwoerter
  4. keine internen Windows-Pfade (D:\\..., C:\\...)
  5. Slug ist bekannt - Slugs werden nicht erfunden
  6. Pflichtfelder vorhanden
  7. 'stand' liegt nicht in der Zukunft

Aufruf (PowerShell). 'py -3' statt 'python' - auf diesem Rechner zeigt
'python' auf den Store-Alias und laeuft ins Leere:

    cd D:\\Claude-Projekte\\FehlerFuchs\\FehlerFuchs_WEBSEITE\\website
    py -3 tools\\steckbriefe_uebernehmen.py            # nur zeigen
    py -3 tools\\steckbriefe_uebernehmen.py --uebernehmen
    py -3 tools\\build_data.py                         # danach neu bauen
"""

import re
import sys
from datetime import date
from pathlib import Path

import yaml

HIER = Path(__file__).resolve().parent
WEBSITE = HIER.parent
ZIEL = WEBSITE / "data" / "src" / "datenschutz"


def finde_quelle():
    """Sucht den Einreichordner an den Stellen, an denen er liegen kann.

    Der Regelfall ist der erste Kandidat. Die weiteren fangen ab, dass der
    Ordner je nach Umgebung anders eingehaengt ist - ein hart verdrahteter
    Pfad waere hier eine Fehlerquelle ohne Nutzen.
    """
    for arg in sys.argv[1:]:
        if arg.startswith("--quelle="):
            return Path(arg.split("=", 1)[1])

    kandidaten = [
        WEBSITE.parent.parent / "_Produktdoku_und_Vertrieb",
        WEBSITE.parent.parent.parent / "FehlerFuchs" / "_Produktdoku_und_Vertrieb",
        WEBSITE.parent.parent / "FehlerFuchs" / "_Produktdoku_und_Vertrieb",
    ]
    for k in kandidaten:
        ordner = k / "Datenschutz-Steckbriefe"
        if ordner.is_dir():
            return ordner
    return kandidaten[0] / "Datenschutz-Steckbriefe"


QUELLE = finde_quelle()

PFLICHT = ["slug", "name", "stand", "geprueft_von", "fassung"]

IP = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
HARMLOS = {"127.0.0.1", "0.0.0.0", "255.255.255.255"}

# Gesucht wird ein GEHEIMNIS, nicht das WORT dafuer.
#
# Erster Versuch war eine Wortliste (passwort, token, secret ...). Die hat am
# 19.07.2026 bei neun von zwanzig Dateien angeschlagen - und kein einziges Mal
# zu Recht: FuchsBau ist ein Passwortmanager, OrgaFuchs beschreibt sein
# Gruppen-Passwort, GewerbePro nennt die Felder seiner Mailkonten. Alle drei
# sagen, WAS sie speichern; keine verraet einen Wert. Eine Regel, die bei jeder
# ehrlichen Beschreibung anschlaegt, wird nach dem dritten Mal weggeklickt.
#
# Also andersherum: Es zaehlt, was wie ein Wert AUSSIEHT.
VERDAECHTIG = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "privater Schluessel (PEM)"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "JWT"),
    # Zuweisung eines langen, zusammenhaengenden Werts: SECRET=..., token: ...
    (re.compile(r"(?i)\b(secret|token|api[-_]?key|passwor[dt]|kennwort|salt)\b"
                r"\s*[:=]\s*[\"']?[A-Za-z0-9+/_-]{16,}"), "Zuweisung eines Geheimnisses"),
    # Lange Hex-Kette. Faengt Schluessel; Pruefsummen sind hier zwar auch
    # betroffen, aber in einem Steckbrief hat beides nichts verloren.
    (re.compile(r"\b[0-9a-fA-F]{40,}\b"), "lange Hex-Kette"),
]
PFAD = re.compile(r"\b[A-Za-z]:\\\\?[A-Za-z0-9_]")

# Kennungen, die es im Produktmodell (noch) nicht gibt, deren Steckbrief aber
# trotzdem gilt. Wer hier etwas eintraegt, muss sagen warum - deshalb ist der
# Grund Pflichttext und keine leere Zeichenkette.
OHNE_PRODUKTSEITE = {
    "schichtfuchs": "Auftragsarbeit fuer einen Kunden, bekommt bewusst keine "
                    "Produktseite (Entscheidung Matze 19.07.2026).",
    "up2date": "Als eigenes Produkt beschlossen, die Produkteinschreibung "
               "steht noch aus.",
    "gewerbepro-companion": "Ausbaustufe von gewerbepro (parent), eigene "
                            "Produktdatei folgt mit der Einschreibung.",
}


def slugs_der_website():
    ordner = WEBSITE / "data" / "src" / "products"
    return {p.stem for p in ordner.glob("*.yaml")}


def dienst_kennungen():
    datei = WEBSITE / "data" / "src" / "dienste.yaml"
    roh = yaml.safe_load(datei.read_text(encoding="utf-8"))
    return {d["id"] for d in roh.get("dienste", [])}


def pruefe(text, daten, erlaubte_kennungen):
    """Gibt (Beanstandungen, Hinweise) zurueck.

    Beanstandung = Abbruch, es wird nichts uebernommen.
    Hinweis      = anzeigen, aber durchlassen.
    """
    funde, hinweise = [], []

    for treffer in sorted(set(IP.findall(text)) - HARMLOS):
        funde.append(f"IP-Adresse '{treffer}' - dieser Ordner wird ausgeliefert")

    for nr, zeile in enumerate(text.splitlines(), 1):
        for muster, was in VERDAECHTIG:
            if muster.search(zeile):
                funde.append(f"Zeile {nr}: {was} - {zeile.strip()[:70]}")
        if PFAD.search(zeile) and not zeile.lstrip().startswith("#"):
            hinweise.append(f"Zeile {nr}: interner Pfad - {zeile.strip()[:70]}")

    fehlt = [f for f in PFLICHT if not daten.get(f)]
    if fehlt:
        funde.append(f"Pflichtfelder fehlen: {', '.join(fehlt)}")

    kennung = daten.get("slug")
    if kennung and kennung not in erlaubte_kennungen:
        if kennung in OHNE_PRODUKTSEITE:
            hinweise.append(f"keine Produktdatei: {OHNE_PRODUKTSEITE[kennung]}")
        else:
            funde.append(
                f"Kennung '{kennung}' ist unbekannt. Slugs werden nicht erfunden - "
                f"entweder einschreiben oder in OHNE_PRODUKTSEITE begruenden."
            )

    stand = str(daten.get("stand", ""))
    if stand > date.today().isoformat():
        funde.append(f"'stand' liegt in der Zukunft ({stand})")

    return funde, hinweise


def sammle(ordner, erlaubte, unterordner=""):
    ergebnis = []
    if not ordner.is_dir():
        return ergebnis
    for datei in sorted(ordner.glob("*.yaml")):
        # Zulieferungen zu fremden Slugs gehoeren NIE ins Datenmodell. Sie sind
        # Rohmaterial fuer den Eigentuemer, nicht die gueltige Fassung - und sie
        # tragen denselben Slug, wuerden die echte Datei also verdraengen.
        # Aufgefallen am 19.07.2026: Eine solche Datei stand im Uebernahmeplan.
        if "_HINWEIS_" in datei.name:
            ergebnis.append((datei, unterordner, None, [],
                             ["Zulieferung, noch nicht eingearbeitet - wird nicht "
                              "uebernommen. Nach dem Einarbeiten nach _erledigt\\ legen."]))
            continue
        text = datei.read_text(encoding="utf-8")
        try:
            daten = yaml.safe_load(text)
        except yaml.YAMLError as e:
            ergebnis.append((datei, unterordner, None, [f"kein gueltiges YAML: {e}"], []))
            continue
        if not isinstance(daten, dict):
            ergebnis.append((datei, unterordner, None, ["kein YAML-Mapping"], []))
            continue
        funde, hinweise = pruefe(text, daten, erlaubte)
        ergebnis.append((datei, unterordner, daten, funde, hinweise))
    return ergebnis


def main():
    uebernehmen = "--uebernehmen" in sys.argv

    if not QUELLE.is_dir():
        print(f"\nEinreichordner nicht gefunden:\n  {QUELLE}\n")
        return 1

    anwendungen = sammle(QUELLE, slugs_der_website())
    dienste = sammle(QUELLE / "Dienste", dienst_kennungen(), "dienste")
    alle = anwendungen + dienste

    if not alle:
        print("\nKeine Steckbriefe im Einreichordner.\n")
        return 1

    beanstandet = [x for x in alle if x[3]]
    mit_hinweis = [x for x in alle if x[4] and not x[3]]

    print()
    print(f"  {len(anwendungen)} Anwendungen, {len(dienste)} Dienste")
    print(f"  Quelle: {QUELLE}")
    print(f"  Ziel:   {ZIEL}")
    print()

    for datei, _, _, _, hinweise in mit_hinweis:
        print(f"  Hinweis zu {datei.name}")
        for h in hinweise:
            print(f"      {h}")
    if mit_hinweis:
        print()

    if beanstandet:
        for datei, _, _, funde, _ in beanstandet:
            print(f"  {datei.name}")
            for f in funde:
                print(f"      {f}")
            print()
        print(f"{len(beanstandet)} Datei(en) beanstandet. Es wurde NICHTS uebernommen.\n")
        return 1

    # ---- Was wuerde sich aendern? ------------------------------------------
    neu, geaendert, gleich = [], [], []
    for datei, unter, daten, _, _ in alle:
        if daten is None:
            continue
        ziel = (ZIEL / unter / datei.name) if unter else (ZIEL / datei.name)
        if not ziel.exists():
            neu.append((datei, ziel))
        elif ziel.read_text(encoding="utf-8") != datei.read_text(encoding="utf-8"):
            geaendert.append((datei, ziel))
        else:
            gleich.append((datei, ziel))

    for bezeichnung, liste in (("NEU", neu), ("GEAENDERT", geaendert)):
        for quelle, _ in liste:
            print(f"  {bezeichnung:10} {quelle.name}")
    if gleich:
        print(f"  {'unveraendert':10} {len(gleich)} Datei(en)")
    print()

    if not uebernehmen:
        if neu or geaendert:
            print("Alles sauber. Uebernehmen mit:")
            print("  py -3 tools\\steckbriefe_uebernehmen.py --uebernehmen\n")
        else:
            print("Alles sauber, nichts zu tun.\n")
        return 0

    for quelle, ziel in neu + geaendert:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(quelle.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"Uebernommen: {len(neu)} neu, {len(geaendert)} geaendert.")
    print("Jetzt neu bauen:  py -3 tools\\build_data.py\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
