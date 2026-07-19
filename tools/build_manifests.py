#!/usr/bin/env python3
"""
FehlerFuchs — Update-Manifeste aus dem zentralen Datenmodell erzeugen.

Erzeugt aus data/products.json:
    updates/<slug>/latest.json    In-App-Updater (derzeit GewerbePro)
    enterprise/latest.json        MobileReport Enterprise (Pfad ist in der App fest verdrahtet)
    versions.json                 Sammelübersicht für den Update-Helfer Up2Date

Aufruf (aus dem Ordner website/):
    python tools/build_manifests.py            # Trockenlauf: zeigt nur, was sich ändern würde
    python tools/build_manifests.py --write    # schreibt tatsächlich

**Der Trockenlauf ist Absicht.** Diese Dateien werden von ausgelieferten Apps gelesen.
Ein falscher Wert erreicht Nutzer sofort und ohne Umweg über die Website. Deshalb wird
jede Abweichung erst gezeigt und muss bewusst bestätigt werden.

Feste Zusagen, die hier nicht gebrochen werden dürfen (siehe enterprise/README.md):
  * Pfad und Dateiname von enterprise/latest.json sind in der App fest verdrahtet.
  * Die App wertet nur version, apkUrl und notes aus.
  * notes erscheint wörtlich im Update-Banner.
  * version muss strikt MAJOR.MINOR.PATCH sein und zur veröffentlichten Datei passen.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS = ROOT / "data" / "products.json"

# Produkte, die ein In-App-Update-Manifest unter updates/<slug>/ bekommen.
# Bewusst eine ausdrückliche Liste: ein Manifest entsteht nur, wenn die App es
# auch abfragt. Sonst liegen tote Dateien herum, die niemand pflegt.
UPDATE_FEEDS = {
    "gewerbepro": {"channel": "beta", "os": "windows"},
}

unterschiede = []


def neuestes_release(p, channel=None, os_=None):
    kandidaten = [r for r in p.get("releases", [])
                  if (channel is None or r["channel"] == channel)
                  and (os_ is None or r["os"] == os_)]
    if not kandidaten:
        return None
    return max(kandidaten, key=lambda r: (r["date"], r["version"]))


def vergleiche(pfad, neu, relevante_felder):
    """Vergleicht die erzeugte Fassung mit der vorhandenen Datei."""
    rel = pfad.relative_to(ROOT)
    if not pfad.exists():
        unterschiede.append((rel, "NEU", [f"Datei existiert noch nicht"]))
        return True

    try:
        alt = json.loads(pfad.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        unterschiede.append((rel, "KAPUTT", [f"vorhandene Datei ist kein gültiges JSON: {e}"]))
        return True

    def ausschnitt(a, b, breite=110):
        """Zeigt beide Werte gekürzt – aber um die erste Abweichung herum.
        Bei langen Texten steht der Unterschied fast immer am Ende; ein Anschnitt
        vom Anfang würde zwei scheinbar identische Zeilen zeigen."""
        sa, sb = str(a), str(b)
        if len(sa) <= breite and len(sb) <= breite:
            return sa, sb
        i = 0
        while i < min(len(sa), len(sb)) and sa[i] == sb[i]:
            i += 1
        start = max(0, i - breite // 3)
        def schnitt(s):
            teil = s[start:start + breite]
            return ("…" if start > 0 else "") + teil + ("…" if start + breite < len(s) else "")
        return schnitt(sa), schnitt(sb)

    zeilen = []
    for k in sorted(set(alt) | set(neu)):
        a, n = alt.get(k, "<fehlt>"), neu.get(k, "<fehlt>")
        if a == n:
            continue
        # Listen von Einträgen (z. B. products in versions.json) je Eintrag vergleichen,
        # sonst wird die Ausgabe unlesbar.
        if isinstance(a, list) and isinstance(n, list) \
                and all(isinstance(x, dict) and "slug" in x for x in a + n):
            alt_map = {x["slug"]: x for x in a}
            neu_map = {x["slug"]: x for x in n}
            for s in sorted(set(alt_map) | set(neu_map)):
                if s not in alt_map:
                    zeilen.append(f"{k}: '{s}' kommt neu hinzu")
                elif s not in neu_map:
                    zeilen.append(f"{k}: '{s}' fällt weg")
                else:
                    for feld in sorted(set(alt_map[s]) | set(neu_map[s])):
                        av, nv = alt_map[s].get(feld), neu_map[s].get(feld)
                        if av != nv:
                            xa, xb = ausschnitt(av, nv)
                            zeilen.append(f"{k}[{s}].{feld}\n"
                                          f"      alt: {xa}\n"
                                          f"      neu: {xb}")
            continue
        warnung = "  ← von der App ausgewertet!" if k in relevante_felder else ""
        xa, xb = ausschnitt(a, n)
        zeilen.append(f"{k}{warnung}\n      alt: {xa}\n      neu: {xb}")
    if zeilen:
        unterschiede.append((rel, "GEÄNDERT", zeilen))
        return True
    return False


def main():
    schreiben = "--write" in sys.argv

    if not PRODUCTS.exists():
        sys.exit("FEHLER: data/products.json fehlt. Erst 'python tools/build_data.py' ausführen.")

    # Schutz gegen den häufigsten Fehlgriff: YAML bearbeitet, aber build_data.py
    # vergessen. Die Manifeste würden dann aus veralteten Daten entstehen.
    veraltet = [f.name for f in (ROOT / "data" / "src").rglob("*.yaml")
                if f.stat().st_mtime > PRODUCTS.stat().st_mtime]
    if veraltet:
        sys.exit("FEHLER: data/products.json ist älter als die Quelldateien "
                 f"({', '.join(sorted(veraltet))}).\n"
                 "        Erst 'python tools/build_data.py' ausführen, dann erneut versuchen.")

    daten = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    produkte = {p["slug"]: p for p in daten["produkte"]}

    stand = datetime.now().astimezone().date().isoformat()
    geplant = []          # (Pfad, Inhalt, ausgewertete Felder)

    # ---------------------------------------------------------- updates/<slug>/
    for slug, cfg in UPDATE_FEEDS.items():
        p = produkte.get(slug)
        if not p:
            sys.exit(f"FEHLER: Produkt '{slug}' steht in UPDATE_FEEDS, fehlt aber im Datenmodell.")
        r = neuestes_release(p, cfg.get("channel"), cfg.get("os"))
        if not r:
            print(f"Hinweis: {slug} hat kein Release im Kanal '{cfg.get('channel')}' – übersprungen.")
            continue
        geplant.append((
            ROOT / "updates" / slug / "latest.json",
            {"version": r["version"], "download_url": r["url"], "notes": r.get("notes", "")},
            {"version", "download_url", "notes"},
        ))

    # ---------------------------------------------------------- enterprise/
    ent = produkte.get("mobilereport-enterprise")
    if ent:
        r = neuestes_release(ent, "stable", "android")
        if r:
            geplant.append((
                ROOT / "enterprise" / "latest.json",
                {"app": ent["name"], "version": r["version"], "apkUrl": r["url"],
                 "notes": r.get("notes", ""), "updatedAt": r["date"]},
                {"version", "apkUrl", "notes"},
            ))

    # ---------------------------------------------------------- versions.json
    # Sammelübersicht über alles, was einen direkten Download hat.
    # ACHTUNG: Das Schema ist ein VORSCHLAG. Up2Date erwartet diese Datei laut
    # Baseline-Doku, das erwartete Format ist dort aber nicht festgehalten.
    # Vor dem Scharfschalten mit dem Up2Date-Projekt abstimmen.
    eintraege = []
    for p in sorted(produkte.values(), key=lambda x: x["name"]):
        r = neuestes_release(p)
        if not r:
            continue
        eintraege.append({
            "slug": p["slug"],
            "name": p["fullName"],
            "version": r["version"],
            "date": r["date"],
            "channel": r["channel"],
            "os": r["os"],
            "url": r["url"],
            "filename": r["filename"],
            "sizeLabel": r["size"]["label"],
            "sha256": r["sha256"],
            "signed": r["signed"],
            "page": "https://fehlerfuchs.eu" + p["links"]["page"],
            "notes": r.get("notes", ""),
        })
    geplant.append((
        ROOT / "versions.json",
        {"schemaVersion": 1, "updatedAt": stand, "products": eintraege},
        set(),
    ))

    # ---------------------------------------------------------- Vergleich
    aenderungen = False
    for pfad, inhalt, felder in geplant:
        if vergleiche(pfad, inhalt, felder):
            aenderungen = True

    if not aenderungen:
        print(f"Alle {len(geplant)} Manifeste stimmen bereits mit dem Datenmodell überein.")
        return 0

    print(f"\n{len(unterschiede)} von {len(geplant)} Manifesten weichen ab:")
    for rel, art, zeilen in unterschiede:
        print(f"\n  {rel}  [{art}]")
        for z in zeilen:
            print(f"    - {z}")

    if not schreiben:
        print("\nTrockenlauf – es wurde nichts geschrieben.")
        print("Wenn die Abweichungen oben richtig sind:  python tools/build_manifests.py --write")
        return 0

    for pfad, inhalt, _ in geplant:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_text(json.dumps(inhalt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Geschrieben: {pfad.relative_to(ROOT)}")

    print("\nNicht vergessen: Der GitHub-Release muss VOR dem Website-Push existieren,")
    print("sonst laufen die Download-Links ins Leere.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
