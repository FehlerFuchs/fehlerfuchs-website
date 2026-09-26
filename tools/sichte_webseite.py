#!/usr/bin/env python3
"""
FehlerFuchs — Webseiten-Sichtung: der maschinelle Teil.

Holt jede öffentliche Seite von fehlerfuchs.eu (Sitemap + alle internen Links),
legt ihren sichtbaren Text ab und prüft, was sich zuverlässig maschinell prüfen
lässt. Das Lesen auf Rechtschreibung und Inhalt macht danach die Routine
„[FF_10] Webseiten-Sichtung" selbst — dieses Werkzeug liefert ihr den Stoff.

Aufruf (aus dem Ordner website/):
    py -3 tools/sichte_webseite.py                 # schreibt nach ..\\99_Logs\\Webseiten-Sichtung\\<Datum>\\
    py -3 tools/sichte_webseite.py --basis URL     # andere Adresse (z. B. lokale Vorschau)

Ergebnis im Tagesordner:
    texte\\<seite>.txt   sichtbarer Text je Seite (zum Lesen)
    befunde.json         alle maschinellen Befunde
    bericht.md           dieselben Befunde, lesbar, dazu die Seitenliste
    aenderungen.md       welche Seitentexte sich seit dem letzten Lauf geändert haben

Das Werkzeug ÄNDERT NICHTS an der Website, am Repo oder an Manifesten.
Gesperrte Wörter werden nie im Klartext ausgegeben, nur ihre Prüfsumme (D4-Geist).
"""
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

WEBSITE = Path(__file__).resolve().parents[1]
PROJEKT = WEBSITE.parent
AUSGABE = PROJEKT / "99_Logs" / "Webseiten-Sichtung"
BASIS = "https://fehlerfuchs.eu"
AGENT = "FehlerFuchs-Webseiten-Sichtung/1.0 (+https://fehlerfuchs.eu)"
MAX_SEITEN = 300

# Ersatzschreibungen: GENAU die Prüfung des Steckbrief-Einlesens (Wortstämme, Ausnahmen für
# Dateinamen, Adressen, Kennungen und freigegebene technische Werte) – eine Quelle, nicht zwei.
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("steckbriefe_uebernehmen", WEBSITE / "tools" / "steckbriefe_uebernehmen.py")
_steck = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_steck)
ersatzschreibungen = _steck.ersatzschreibungen

# Gesperrte Wörter: nur die Prüfsummen aus build_data.py (dort ist die einzige Liste).
_bd = (WEBSITE / "tools" / "build_data.py").read_text(encoding="utf-8")
_block = re.search(r"GESPERRTE_WOERTER = \{(.*?)\n\}", _bd, re.S)
GESPERRT = set(re.findall(r'"([0-9a-f]{64})"', _block.group(1))) if _block else set()

PLATZHALTER = re.compile(r"\b(TODO|FIXME|XXX|TBD|lorem ipsum|undefined|NaN|\[object Object\]|null)\b|\{\{|\}\}")
# Nur innerhalb einer Zeile und bei gleicher Schreibung: Überschrift + Name in der nächsten
# Zeile oder „ein Ein-…“ sind kein Fehler. „die die“ bleibt als Hinweis (oft richtig, Relativsatz).
DOPPELWORT = re.compile(r"\b(\w{2,})[ \t]+\1\b")
DATUM_DE = re.compile(r"\b(\d{2})\.(\d{2})\.(20\d{2})\b")
DATUM_ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")


class Seite(HTMLParser):
    """Sichtbarer Text, Links, Anker-IDs und eingebundene Dateien einer HTML-Seite."""
    STUMM = {"script", "style", "noscript", "template", "svg"}
    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "section",
             "article", "header", "footer", "summary", "details", "td", "th", "dt", "dd", "figcaption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.links, self.ids, self.dateien = [], [], set(), []
        self.titel, self._stumm, self._im_titel = "", 0, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.STUMM:
            self._stumm += 1
        if tag == "title":
            self._im_titel = True
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag in ("img", "script", "source") and a.get("src"):
            self.dateien.append(a["src"])
        if tag == "link" and a.get("href") and a.get("rel") in ("stylesheet", "icon", "preload"):
            self.dateien.append(a["href"])
        if tag == "img" and a.get("alt"):
            self.text.append(f" [Bild: {a['alt']}] ")
        if tag in self.BLOCK:
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag in self.STUMM and self._stumm:
            self._stumm -= 1
        if tag == "title":
            self._im_titel = False
        if tag in self.BLOCK:
            self.text.append("\n")

    def handle_data(self, data):
        if self._im_titel:
            self.titel += data
        elif not self._stumm:
            self.text.append(data)

    def sichtbar(self):
        roh = "".join(self.text)
        zeilen = [re.sub(r"[ \t ]+", " ", z).strip() for z in roh.split("\n")]
        return "\n".join(z for z in zeilen if z)


def hole(url, nur_kopf=False):
    """(Status, End-Adresse, Kopfzeilen, Inhalt). Folgt Weiterleitungen."""
    req = urllib.request.Request(url, headers={"User-Agent": AGENT}, method="HEAD" if nur_kopf else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.geturl(), dict(r.headers), (b"" if nur_kopf else r.read())
    except urllib.error.HTTPError as e:
        if nur_kopf and e.code in (403, 405):          # manche Hosts mögen kein HEAD
            return hole(url, nur_kopf=False)
        return e.code, url, dict(e.headers or {}), b""
    except Exception as e:                             # Netz, Zeitüberschreitung, TLS
        return 0, url, {"fehler": str(e)}, b""


def seitenname(pfad):
    p = pfad.strip("/") or "startseite"
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", p)


def main():
    basis = BASIS
    if "--basis" in sys.argv:
        basis = sys.argv[sys.argv.index("--basis") + 1].rstrip("/")
    host = urllib.parse.urlparse(basis).netloc
    heute = date.today()
    ziel = AUSGABE / heute.isoformat()
    (ziel / "texte").mkdir(parents=True, exist_ok=True)
    befunde = []

    def befund(art, seite, text, schwere="mittel"):
        befunde.append({"art": art, "seite": seite, "befund": text, "schwere": schwere})

    # 1) Seiten sammeln: Sitemap + alle internen Links (Breitensuche)
    st, _, _, xml = hole(basis + "/sitemap.xml")
    sitemap = [urllib.parse.urlparse(u).path or "/" for u in re.findall(r"<loc>([^<]+)</loc>", xml.decode("utf-8", "replace"))]
    if st != 200:
        befund("sitemap", "/sitemap.xml", f"Sitemap nicht abrufbar (HTTP {st})", "hoch")
    offen, gesehen, seiten = list(sitemap) or ["/"], set(), {}
    while offen and len(seiten) < MAX_SEITEN:
        pfad = offen.pop(0)
        if pfad in gesehen:
            continue
        gesehen.add(pfad)
        st, end, kopf, inhalt = hole(basis + pfad)
        if st != 200:
            befund("seite", pfad, f"Seite antwortet mit HTTP {st}" + (f" ({kopf.get('fehler')})" if kopf.get("fehler") else ""), "hoch")
            continue
        if "text/html" not in kopf.get("Content-Type", kopf.get("content-type", "")):
            continue
        s = Seite()
        s.feed(inhalt.decode("utf-8", "replace"))
        seiten[pfad] = s
        for href in s.links:
            u = urllib.parse.urlparse(urllib.parse.urljoin(basis + pfad, href))
            if u.netloc == host and u.scheme in ("http", "https"):
                p = u.path or "/"
                if (p.endswith("/") or "." not in p.rsplit("/", 1)[-1]) and p not in gesehen:
                    offen.append(p)

    for pfad in seiten:
        if pfad not in sitemap and pfad != "/":
            befund("sitemap", pfad, "Seite ist verlinkt, steht aber nicht in der Sitemap", "niedrig")

    # 2) Texte ablegen, Textprüfungen
    for pfad, s in seiten.items():
        text = s.sichtbar()
        (ziel / "texte" / f"{seitenname(pfad)}.txt").write_text(f"# {pfad}\n# Titel: {s.titel.strip()}\n\n{text}\n", encoding="utf-8")
        for w in ersatzschreibungen({"text": text}):
            befund("umlaut", pfad, f"Ersatzschreibung statt Umlaut: „{w}“")
        for m in DOPPELWORT.finditer(text):
            befund("doppelwort", pfad, f"Wort doppelt: „{m.group(0)}“", "niedrig")
        for m in PLATZHALTER.finditer(text):
            befund("platzhalter", pfad, f"Platzhalter oder technischer Rest im Text: „{m.group(0)}“", "hoch")
        for wort in set(re.findall(r"\w+", text.lower())):
            if hashlib.sha256(wort.encode("utf-8")).hexdigest() in GESPERRT:
                befund("gesperrt", pfad, "Gesperrtes Wort gefunden (Prüfsumme "
                       + hashlib.sha256(wort.encode()).hexdigest()[:8] + "…, Wort siehe VERTRAULICH-Liste)", "hoch")
        for d, mo, j in DATUM_DE.findall(text):
            try:
                if date(int(j), int(mo), int(d)) > heute:
                    befund("datum", pfad, f"Datum in der Zukunft: {d}.{mo}.{j}", "niedrig")
            except ValueError:
                befund("datum", pfad, f"Ungültiges Datum: {d}.{mo}.{j}")
        for j, mo, d in DATUM_ISO.findall(text):
            try:
                if date(int(j), int(mo), int(d)) > heute:
                    befund("datum", pfad, f"Datum in der Zukunft: {j}-{mo}-{d}", "niedrig")
            except ValueError:
                befund("datum", pfad, f"Ungültiges Datum: {j}-{mo}-{d}")

    # 3) Links, Anker und eingebundene Dateien
    geprueft = {}

    def status(url):
        if url not in geprueft:
            geprueft[url] = hole(url, nur_kopf=True)
        return geprueft[url]

    for pfad, s in seiten.items():
        for href in s.links + s.dateien:
            if href.startswith(("mailto:", "tel:", "javascript:", "data:")):
                continue
            voll = urllib.parse.urljoin(basis + pfad, href)
            u = urllib.parse.urlparse(voll)
            if u.scheme not in ("http", "https"):
                continue
            ohne_anker = voll.split("#")[0]
            intern = u.netloc == host
            st = 200 if (intern and (u.path or "/") in seiten) else status(ohne_anker)[0]
            if st != 200:
                befund("link-intern" if intern else "link-extern", pfad,
                       f"Link ins Leere: {voll} (HTTP {st})", "hoch" if intern or "fehlerfuchs-downloads" in voll else "mittel")
            if u.fragment and intern and (u.path or "/") in seiten:
                if u.fragment not in seiten[u.path or "/"].ids:
                    befund("anker", pfad, f"Sprungmarke fehlt: {u.path or '/'}#{u.fragment}")

    # 4) Manifeste: Version, Download erreichbar, Größe
    st, _, _, vj = hole(basis + "/versions.json")
    versionen = {}
    if st == 200:
        for p in json.loads(vj).get("products", []):
            versionen[p["slug"]] = p.get("version")
            s2, _, kopf, _ = status(p["url"])
            if s2 != 200:
                befund("manifest", "/versions.json", f"{p['slug']} {p.get('version')}: Download antwortet HTTP {s2}", "hoch")
    else:
        befund("manifest", "/versions.json", f"versions.json nicht abrufbar (HTTP {st})", "hoch")
    for latest in sorted((WEBSITE / "updates").glob("*/latest.json")):
        slug = latest.parent.name
        st, _, _, lj = hole(f"{basis}/updates/{slug}/latest.json")
        if st != 200:
            befund("manifest", f"/updates/{slug}/latest.json", f"nicht abrufbar (HTTP {st})", "hoch")
            continue
        d = json.loads(lj)
        s2 = status(d.get("download_url", ""))[0]
        if s2 != 200:
            befund("manifest", f"/updates/{slug}/latest.json", f"Download antwortet HTTP {s2}", "hoch")
        if slug in versionen and versionen[slug] != d.get("version"):
            befund("manifest", f"/updates/{slug}/latest.json",
                   f"Version {d.get('version')} weicht von versions.json ({versionen[slug]}) ab", "hoch")

    # 5) Ausgabe
    (ziel / "befunde.json").write_text(json.dumps(befunde, ensure_ascii=False, indent=2), encoding="utf-8")
    vorher = sorted([p for p in AUSGABE.iterdir() if p.is_dir() and p.name < heute.isoformat()], reverse=True)
    geaendert = []
    if vorher:
        alt = vorher[0] / "texte"
        for f in sorted((ziel / "texte").glob("*.txt")):
            a = alt / f.name
            if not a.exists():
                geaendert.append(f"- NEU: {f.name}")
            elif a.read_text(encoding="utf-8") != f.read_text(encoding="utf-8"):
                geaendert.append(f"- geändert: {f.name}")
        for a in sorted(alt.glob("*.txt")):
            if not (ziel / "texte" / a.name).exists():
                geaendert.append(f"- WEG: {a.name}")
    (ziel / "aenderungen.md").write_text(
        f"# Änderungen seit {vorher[0].name if vorher else '— (erster Lauf)'}\n\n" + ("\n".join(geaendert) or "keine") + "\n",
        encoding="utf-8")
    zeilen = [f"# Webseiten-Sichtung — maschineller Teil", "",
              f"**Lauf:** {datetime.now().astimezone().isoformat(timespec='seconds')} · **Basis:** {basis}",
              f"**Seiten:** {len(seiten)} · **Links/Dateien geprüft:** {len(geprueft)} · **Befunde:** {len(befunde)}", "",
              "| Schwere | Art | Seite | Befund |", "|---|---|---|---|"]
    for b in sorted(befunde, key=lambda b: ({"hoch": 0, "mittel": 1, "niedrig": 2}[b["schwere"]], b["seite"])):
        zeilen.append(f"| {b['schwere']} | {b['art']} | `{b['seite']}` | {b['befund']} |")
    zeilen += ["", "## Seiten", ""] + [f"- `{p}` — {s.titel.strip()}" for p, s in sorted(seiten.items())]
    (ziel / "bericht.md").write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    print(f"Seiten: {len(seiten)} | Links/Dateien: {len(geprueft)} | Befunde: {len(befunde)} "
          f"| Änderungen seit letztem Lauf: {len(geaendert)}")
    print(f"Ordner: {ziel}")


if __name__ == "__main__":
    main()
