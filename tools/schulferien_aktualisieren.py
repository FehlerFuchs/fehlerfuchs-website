#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Schulferien-Abgleich gegen OpenHolidays (OF-F-018).

Holt die Schulferien der 16 deutschen Bundesländer von OpenHolidays
(openholidaysapi.org, Daten unter ODbL-1.0) und schreibt sie als
data/schulferien/DE-<BL>.json — GENAU im Format, das die OrgaFuchs-App erwartet:

    { "JJJJ": [ { "name": ..., "von": "YYYY-MM-DD", "bis": "YYYY-MM-DD" }, ... ] }

Schlüssel = Startjahr der Ferien; ein Jahr erscheint nur, wenn es Einträge hat.

Grundsatz (Anordnung Matthias 23.09.2026): WÖCHENTLICHER Abgleich, aber die
Website wird NUR neu ausgeliefert, wenn sich die Daten wirklich geändert haben.
Das erledigt der Workflow über `git status` — dieses Skript schreibt eine Datei
nur dann neu, wenn ihr kanonischer Inhalt vom bereits abgelegten abweicht.

Sicherheitsnetz: Eine unplausible Antwort (Netzfehler, leere/zu kurze Liste)
führt NIE dazu, dass eine gute Datei mit Müll überschrieben wird — das Land wird
übersprungen, als Fehler gemeldet und der Lauf endet mit Exit-Code 2.

Aufruf:
    python tools/schulferien_aktualisieren.py            # schreibt Änderungen
    python tools/schulferien_aktualisieren.py --pruefen  # nur prüfen, nichts schreiben
"""

import json
import sys
import urllib.request
import urllib.error
from datetime import date, datetime
from pathlib import Path

BASIS = "https://openholidaysapi.org/SchoolHolidays"
LAND = "DE"
SPRACHE = "DE"

# ISO-3166-2-Codes der 16 Bundesländer (GROSS) — genau die Dateinamen, die die
# App abruft: fehlerfuchs.eu/data/schulferien/DE-<BL>.json
BUNDESLAENDER = [
    "DE-BW", "DE-BY", "DE-BE", "DE-BB", "DE-HB", "DE-HH", "DE-HE", "DE-MV",
    "DE-NI", "DE-NW", "DE-RP", "DE-SL", "DE-SN", "DE-ST", "DE-SH", "DE-TH",
]

# Fenster: aktuelles Jahr minus 1 bis plus 5 — abgestimmt auf den von [32]
# gelieferten Stand (Stand 2026-07-18: 2024 nur als Rand-Überlappung aus der
# 2025-Abfrage, dann 2025–2030/2031). So reproduziert der Abgleich die vorhandenen
# Dateien, wenn sich oben bei der Quelle nichts geändert hat, und schlägt nur bei
# ECHTEN Datenänderungen an. Das Fenster wächst mit dem Jahr automatisch mit.
_HEUTE = date.today()
JAHR_VON = _HEUTE.year - 1
JAHR_BIS = _HEUTE.year + 5

# Untergrenze der Plausibilität: so wenige Ferien hat kein Bundesland über acht
# Jahre. Weniger ⇒ Antwort verdächtig ⇒ Datei NICHT überschreiben.
MIN_EINTRAEGE = 20

ZIEL = Path(__file__).resolve().parent.parent / "data" / "schulferien"


def _hole_jahr(bl: str, jahr: int) -> list:
    params = (
        f"?countryIsoCode={LAND}&languageIsoCode={SPRACHE}"
        f"&subdivisionCode={bl}"
        f"&validFrom={jahr}-01-01&validTo={jahr}-12-31"
    )
    req = urllib.request.Request(BASIS + params, headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as antwort:
        return json.load(antwort)


def hole(bl: str) -> list:
    """Rohliste der Ferien eines Bundeslandes — Jahr für Jahr abgefragt und über
    die id dedupliziert (die API begrenzt die Zeitspanne je Abruf; ein Ferienblock
    an der Jahresgrenze taucht in zwei Jahresabfragen auf)."""
    nach_id: dict[str, dict] = {}
    for jahr in range(JAHR_VON, JAHR_BIS + 1):
        for e in _hole_jahr(bl, jahr):
            eid = e.get("id")
            if eid and eid not in nach_id:
                nach_id[eid] = e
    return list(nach_id.values())


def deutscher_name(eintrag: dict) -> str:
    namen = eintrag.get("name", [])
    for n in namen:
        if n.get("language") == "DE" and n.get("text"):
            return n["text"]
    return namen[0]["text"] if namen and namen[0].get("text") else "Ferien"


def kanonisch(roh: list) -> dict:
    """Rohliste → {JJJJ:[{name,von,bis}]}, nach Startjahr gruppiert.

    Dedupliziert nach INHALT (name, von, bis): OpenHolidays liefert denselben
    Ferienblock teils mehrfach mit verschiedenen ids (Datenquirk) — die id-Dedup
    in hole() fängt das nicht. ECHTE Varianten (z. B. zwei Sommerferien mit gleichem
    Start, aber unterschiedlichem Ende) bleiben erhalten, weil sich 'bis' unterscheidet.
    Sortiert NUR nach 'von' und stabil, damit die Reihenfolge der Quelle bei
    gleichem Startdatum erhalten bleibt (reproduziert den [32]-Stand exakt)."""
    nach_jahr: dict[str, list] = {}
    gesehen = set()
    for e in roh:
        von = e.get("startDate")
        bis = e.get("endDate")
        if not von or not bis:
            continue
        eintrag = {"name": deutscher_name(e), "von": von, "bis": bis}
        schluessel = (eintrag["name"], von, bis)
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        nach_jahr.setdefault(von[:4], []).append(eintrag)
    for jahr in nach_jahr:
        nach_jahr[jahr].sort(key=lambda x: x["von"])
    return {jahr: nach_jahr[jahr] for jahr in sorted(nach_jahr)}


def als_text(daten: dict) -> str:
    # 2 Leerzeichen Einrückung, echte Umlaute, LF, KEIN abschließender Zeilenumbruch
    # — exakt wie die von [32] gelieferten Dateien (sonst difft jeder Lauf).
    return json.dumps(daten, ensure_ascii=False, indent=2)


def main() -> int:
    nur_pruefen = "--pruefen" in sys.argv
    geaendert, unveraendert, fehler = [], [], []

    for bl in BUNDESLAENDER:
        pfad = ZIEL / f"{bl}.json"
        try:
            roh = hole(bl)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as ex:
            fehler.append(f"{bl}: Abruf fehlgeschlagen ({ex})")
            continue

        if len(roh) < MIN_EINTRAEGE:
            fehler.append(f"{bl}: nur {len(roh)} Einträge (< {MIN_EINTRAEGE}) — verdächtig, übersprungen")
            continue

        neu_text = als_text(kanonisch(roh))
        alt_text = pfad.read_text(encoding="utf-8") if pfad.exists() else None

        if alt_text == neu_text:
            unveraendert.append(bl)
            continue

        geaendert.append(bl)
        if not nur_pruefen:
            pfad.write_text(neu_text, encoding="utf-8", newline="")

    print(f"Schulferien-Abgleich {datetime.now().isoformat(timespec='seconds')} "
          f"(Fenster {JAHR_VON}–{JAHR_BIS})")
    print(f"  unverändert: {len(unveraendert)}")
    print(f"  geändert:    {len(geaendert)}" + (f" -> {', '.join(geaendert)}" if geaendert else ""))
    if fehler:
        print(f"  FEHLER:      {len(fehler)}")
        for f in fehler:
            print(f"    - {f}")

    # Exit-Code: 2 bei Fehlern (Workflow wird rot, wir sehen es), sonst 0.
    # „Geändert" ist KEIN Fehler — ob deployt wird, entscheidet der Workflow per git.
    return 2 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
