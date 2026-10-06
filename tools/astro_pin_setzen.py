#!/usr/bin/env python3
"""Setzt website/astro-ref.txt auf den aktuellen Astro-Commit (Entscheidung Matthias E7 Nr. 3, #4812).

Ablauf bei jedem Deploy, der Astro-Änderungen enthält:
  1. astro committen und pushen (ein Astro-Push veröffentlicht nichts)
  2. py -3 tools/astro_pin_setzen.py      (dieses Werkzeug)
  3. astro-ref.txt im website-Commit mitnehmen, website pushen = Deploy (nur auf Matthias' Wort)

Das Werkzeug weigert sich, wenn astro ungepushte oder uncommittete Quelländerungen hat: Der Pin muss auf
einen Stand zeigen, den der Deploy auch auschecken kann. Mit --pruefen wird nur verglichen (Exit 1 bei Abweichung).
"""
import subprocess
import sys
from pathlib import Path

WEBSITE = Path(__file__).resolve().parents[1]
ASTRO = WEBSITE.parent / "astro"
PIN = WEBSITE / "astro-ref.txt"


def git(*args):
    r = subprocess.run(["git", "-C", str(ASTRO), *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        sys.exit("FEHLER: git " + " ".join(args) + ": " + r.stderr.strip())
    return r.stdout.strip()


def main():
    kopf = git("rev-parse", "HEAD")
    ungepusht = git("rev-list", "--count", "@{u}..HEAD")
    geaendert = [z for z in git("status", "--porcelain", "--untracked-files=no").splitlines() if z.strip()]
    alt = PIN.read_text(encoding="utf-8").strip() if PIN.exists() else "(fehlt)"
    if "--pruefen" in sys.argv:
        print(f"Pin {alt[:8]} · astro HEAD {kopf[:8]} · ungepusht {ungepusht}")
        return 0 if alt == kopf else 1
    if ungepusht != "0":
        sys.exit(f"ABBRUCH: astro hat {ungepusht} ungepushte Commits. Erst astro pushen, sonst kann der Deploy den Stand nicht auschecken.")
    if geaendert:
        sys.exit("ABBRUCH: astro hat uncommittete Änderungen an versionierten Dateien:\n  " + "\n  ".join(geaendert))
    PIN.write_text(kopf + "\n", encoding="utf-8")
    print(f"astro-ref.txt: {alt[:8]} -> {kopf[:8]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
