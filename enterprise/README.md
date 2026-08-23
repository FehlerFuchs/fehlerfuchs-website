# enterprise/ — Update-Manifest & Download-Konvention (MobileReport Enterprise)

## `latest.json` — ausgeliefertes, erzeugtes Manifest
Die Enterprise-App (Off-Play) prüft beim Start **fest verdrahtet** die URL
`https://fehlerfuchs.eu/enterprise/latest.json`. **Diesen Pfad und Dateinamen NICHT ändern.**

Die fachliche Quelle ist `data/src/products/mobilereport-enterprise.yaml`.
`tools/build_manifests.py` erzeugt daraus `enterprise/latest.json`; die JSON-Datei nicht
von Hand pflegen.

Schema (genau so lesen App):
```json
{
  "app": "MobileReport Enterprise",
  "version": "1.0.2",
  "apkUrl": "https://github.com/FehlerFuchs/fehlerfuchs-downloads/releases/download/mobilereport-enterprise-v1.0.2/MobileReport-Enterprise-1.0.2.apk",
  "notes": "Kurzer Änderungstext – wird 1:1 im Update-Hinweis der App angezeigt.",
  "updatedAt": "2026-08-18"
}
```

Von der App **ausgewertet**: nur `version`, `apkUrl`, `notes`.
- `version`: nur `MAJOR.MINOR.PATCH`; Hinweis erscheint **nur**, wenn strikt höher als die installierte Version. Muss zur veröffentlichten APK passen (pubspec-Version ohne `+build`).
- `apkUrl`: direkter Download-Link (GitHub-Release-Asset). **Leer → App zeigt keinen Hinweis.**
- `notes`: 1–2 Sätze Klartext (kein Markdown), erscheint wörtlich im Banner.
- `app`, `updatedAt`: nur für Menschen (App ignoriert sie) — trotzdem pflegen.
- **Muss immer gültiges JSON sein.** Fehlt/kaputt/leer → App zeigt nichts und läuft weiter.

## APK-Hosting & URL-Beleg
Die APK wird **nicht** hier gehostet, sondern als **GitHub-Release-Asset** im Repo
`FehlerFuchs/fehlerfuchs-downloads`.
- Aktueller Release-Tag: `mobilereport-enterprise-v1.0.2`
- Historische Tags 1.0.0/1.0.1: `mr-ent-v1.0.0` und `mr-ent-v1.0.1`
- Asset-Dateiname: `MobileReport-Enterprise-<version>.apk`
- Den Tag nicht aus einer vermeintlichen Konvention ableiten: die konkrete URL im Produkt-YAML
  muss per HTTP/API gegen das vorhandene Release-Asset geprüft werden.
- Fallback (Downloadseite, wenn `apkUrl` leer/Fetch scheitert): `https://github.com/FehlerFuchs/fehlerfuchs-downloads/releases/latest`

## Release-Checkliste (bei jedem Enterprise-Release)
1. Freigegebene Release-APK im App-Projekt erstellen und die Prüfdaten übernehmen.
2. Matthias legt das Release im Repo `fehlerfuchs-downloads` an; Tag und Asset danach real abfragen.
3. Produkt-YAML setzen und `python tools/build_manifests.py` zunächst ohne `--write` prüfen.
4. Nach bestätigtem Diff mit `--write` erzeugen; JSON parsen und die konkrete `apkUrl` per HEAD/API prüfen.
5. Commit, Push und Deploy ausschließlich nach den aktuellen Hausregeln und Freigaben.

*Stand 2026-08-23. Manifestpfad gegen den aktiven Daten- und Deploy-Fluss geprüft.*
