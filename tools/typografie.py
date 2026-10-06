"""Typografie-Regeln der Website: eine Quelle für build_data, Steckbriefe-Spiegelung und Sichtung.

Regeln: „…“ statt „…" oder "…"; Gedankenstrich „ – “ statt „ - “ oder „ — “.
Ausnahme: Code-Schreibweisen in geraden Anführungszeichen (siehe code_artig) –
z. B. allowBackup="false", "file_picker", "config.py".
(Webseiten-Sichtung 26.09.2026, Befund 16; geschärft 04.10.2026 nach Befund 1 der Sichtung vom 04.10.)
"""
import re

TYPO_MISCH = re.compile(r'„([^“”"\n]{1,160})"')
TYPO_GERADE = re.compile(r'(?<![„\w\\])"([^"\n\\]{1,160}?)"')
TYPO_STRICH = re.compile(r"(?<=\S) (-|—) (?=\S)")


def code_artig(innen, davor):
    # Code: steht hinter „=“, enthält „_“, enthält = / : . ohne Leerzeichen (config.py,
    # image/png) oder ist ein YAML-Schlüssel (uebertragungen: []). NICHT Code: ein kleines
    # Wort wie "gefunden" oder ein Titel wie "Info / Datenschutz" – das ist Fließtext.
    return (davor.rstrip().endswith("=") or "_" in innen
            or (not re.search(r"\s", innen) and any(c in innen for c in "=/:."))
            or re.fullmatch(r"[a-z_]+:\s*\S*", innen) is not None
            or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", innen) is not None)   # Kennung: kein-tracking


def funde(s):
    """Liste der Beanstandungen in einem Text (leer = sauber)."""
    raus = [f"„…\" statt „…“: „{m.group(1)[:40]}\"" for m in TYPO_MISCH.finditer(s)]
    raus += [f"gerade \"…\": \"{m.group(1)[:40]}\"" for m in TYPO_GERADE.finditer(s)
             if not code_artig(m.group(1), s[:m.start()])]
    raus += [f"„ {m.group(1)} “ statt „ – “: …{s[max(0, m.start() - 20):m.end() + 12]}…"
             for m in TYPO_STRICH.finditer(s)]
    return raus
