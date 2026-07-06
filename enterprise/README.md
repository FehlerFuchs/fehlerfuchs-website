# enterprise/ — Update-Manifest & Download-Konvention (MobileReport Enterprise)

## `latest.json` — Single Source of Truth
Die Enterprise-App (Off-Play) prüft beim Start **fest verdrahtet** die URL
`https://fehlerfuchs.eu/enterprise/latest.json`. **Diesen Pfad und Dateinamen NICHT ändern.**

Schema (genau so lesen App):
```json
{
  "app": "MobileReport Enterprise",
  "version": "0.1.0",
  "apkUrl": "https://github.com/FehlerFuchs/fehlerfuchs-downloads/releases/download/mr-ent-v0.1.0/MobileReport-Enterprise-0.1.0.apk",
  "notes": "Kurzer Änderungstext – wird 1:1 im Update-Hinweis der App angezeigt.",
  "updatedAt": "2026-07-06"
}
```

Von der App **ausgewertet**: nur `version`, `apkUrl`, `notes`.
- `version`: nur `MAJOR.MINOR.PATCH`; Hinweis erscheint **nur**, wenn strikt höher als die installierte Version. Muss zur veröffentlichten APK passen (pubspec-Version ohne `+build`).
- `apkUrl`: direkter Download-Link (GitHub-Release-Asset). **Leer → App zeigt keinen Hinweis.**
- `notes`: 1–2 Sätze Klartext (kein Markdown), erscheint wörtlich im Banner.
- `app`, `updatedAt`: nur für Menschen (App ignoriert sie) — trotzdem pflegen.
- **Muss immer gültiges JSON sein.** Fehlt/kaputt/leer → App zeigt nichts und läuft weiter.

## APK-Hosting & URL-Konvention
Die APK wird **nicht** hier gehostet, sondern als **GitHub-Release-Asset** im Repo
`FehlerFuchs/fehlerfuchs-downloads`.
- Release-Tag: `mr-ent-v<version>` (z. B. `mr-ent-v0.1.0`)
- Asset-Dateiname: `MobileReport-Enterprise-<version>.apk`
- `apkUrl`: `https://github.com/FehlerFuchs/fehlerfuchs-downloads/releases/download/mr-ent-v<version>/MobileReport-Enterprise-<version>.apk`
- Fallback (Downloadseite, wenn `apkUrl` leer/Fetch scheitert): `https://github.com/FehlerFuchs/fehlerfuchs-downloads/releases/latest`

## Release-Checkliste (bei jedem Enterprise-Release)
1. Signierte Release-APK im App-Projekt bauen.
2. GitHub-Release im Repo `fehlerfuchs-downloads` anlegen (Tag `mr-ent-v<version>`), APK als Asset hochladen.
3. `latest.json` setzen: `version`, `apkUrl`, `notes`, `updatedAt`.
4. Push → Deploy. Test: `version` höher als installiert + gültige `apkUrl` → App zeigt beim Start das Banner mit `notes`.

*Stand 2026-07-06. Verifiziert gegen `FehlerFuchsMR_Enterprise/01_App/lib/services/update_service.dart`.*
