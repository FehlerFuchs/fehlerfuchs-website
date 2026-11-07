"""Prüft tools/zeit_berlin.py gegen bekannte Zeitpunkte. Aufruf: py -3 tools/test_zeit_berlin.py (Rückgabe 0 = in Ordnung)."""
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from zeit_berlin import berlin_jetzt, heute_berlin  # noqa: E402

UTC = timezone.utc
FAELLE = [
    # (UTC-Zeitpunkt, erwartetes Berliner Datum, erwartete Berliner Uhrzeit, Bemerkung)
    (datetime(2026, 11, 6, 23, 37, tzinfo=UTC), date(2026, 11, 7), "00:37", "der Fall vom 07.11.2026: Winterzeit, Runner noch am 06.11."),
    (datetime(2026, 11, 6, 22, 59, 59, tzinfo=UTC), date(2026, 11, 6), "23:59", "eine Sekunde vor Mitternacht Winterzeit"),
    (datetime(2026, 11, 6, 23, 0, 0, tzinfo=UTC), date(2026, 11, 7), "00:00", "Mitternacht Winterzeit"),
    (datetime(2026, 7, 14, 22, 0, 0, tzinfo=UTC), date(2026, 7, 15), "00:00", "Sommerzeit: UTC+2"),
    (datetime(2026, 7, 14, 21, 59, 0, tzinfo=UTC), date(2026, 7, 14), "23:59", "Sommerzeit, eine Minute vor Mitternacht"),
    # Umstellung 2026: Sommerzeit ab Sonntag 29.03. 01:00 UTC, Winterzeit ab Sonntag 25.10. 01:00 UTC
    (datetime(2026, 3, 29, 0, 59, 59, tzinfo=UTC), date(2026, 3, 29), "01:59", "eine Sekunde vor der Umstellung auf Sommerzeit"),
    (datetime(2026, 3, 29, 1, 0, 0, tzinfo=UTC), date(2026, 3, 29), "03:00", "Umstellung auf Sommerzeit"),
    (datetime(2026, 10, 25, 0, 59, 59, tzinfo=UTC), date(2026, 10, 25), "02:59", "eine Sekunde vor der Umstellung auf Winterzeit"),
    (datetime(2026, 10, 25, 1, 0, 0, tzinfo=UTC), date(2026, 10, 25), "02:00", "Umstellung auf Winterzeit"),
    (datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC), date(2027, 1, 1), "01:00", "Jahreswechsel"),
]


def main():
    fehler = 0
    for utc, datum, uhr, was in FAELLE:
        b = berlin_jetzt(utc)
        ok = b.date() == datum and b.strftime("%H:%M") == uhr and heute_berlin(utc) == datum
        if not ok:
            fehler += 1
        print(("ok     " if ok else "FEHLER ") + f"{utc.isoformat()} -> {b.isoformat()} (erwartet {datum} {uhr}) {was}")
    jetzt = heute_berlin()
    if not isinstance(jetzt, date):
        fehler += 1
        print("FEHLER heute_berlin() liefert kein Datum")
    try:
        berlin_jetzt(datetime(2026, 1, 1))
        fehler += 1
        print("FEHLER: ein datetime ohne Zeitzone wurde angenommen")
    except ValueError:
        print("ok     datetime ohne Zeitzone wird abgelehnt")
    print(f"{fehler} Fehler" if fehler else "alles in Ordnung")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
