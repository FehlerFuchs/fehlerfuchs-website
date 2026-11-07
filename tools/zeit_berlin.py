"""Das heutige Datum in Berliner Zeit: eine Quelle für die Datumsprüfungen der Website.

WARUM ES DIESES MODUL GIBT
==========================
Der Deploy-Lauf von GitHub rechnet in UTC. Ein Release oder ein Steckbrief vom 07.11.
(Ortszeit) war dort bis 01:00 Uhr deutscher Zeit noch „in der Zukunft“ (06.11. UTC), und
der Deploy brach ab (07.11.2026, 00:37, Run 42313104806). `date.today()` fragt die Uhr
des Rechners, nicht die Zeit, in der die Inhalte geschrieben werden.

Dieses Modul rechnet die Berliner Ortszeit aus der UTC-Zeit selbst aus (mitteleuropäische
Zeit, Sommerzeit vom letzten Sonntag im März 01:00 UTC bis zum letzten Sonntag im Oktober
01:00 UTC). Es braucht kein `zoneinfo` und kein Zusatzpaket: Unter Windows fehlt `tzdata`,
auf dem Runner wäre es vorhanden, und beide sollen dasselbe Ergebnis liefern.

Prüfung: py -3 tools/test_zeit_berlin.py
"""
from datetime import date, datetime, timedelta, timezone


def _letzter_sonntag(jahr, monat):
    """Letzter Sonntag eines Monats mit 31 Tagen (März, Oktober)."""
    tag = date(jahr, monat, 31)
    while tag.weekday() != 6:
        tag -= timedelta(days=1)
    return tag


def berlin_jetzt(jetzt_utc=None):
    """Berliner Ortszeit als naives datetime. `jetzt_utc`: datetime mit tzinfo=UTC (nur für Tests)."""
    jetzt = jetzt_utc if jetzt_utc is not None else datetime.now(timezone.utc)
    if jetzt.tzinfo is None:
        raise ValueError("jetzt_utc braucht eine Zeitzone (UTC)")
    jetzt = jetzt.astimezone(timezone.utc)
    beginn = datetime.combine(_letzter_sonntag(jetzt.year, 3), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=1)
    ende = datetime.combine(_letzter_sonntag(jetzt.year, 10), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=1)
    versatz = timedelta(hours=2) if beginn <= jetzt < ende else timedelta(hours=1)
    return (jetzt + versatz).replace(tzinfo=None)


def heute_berlin(jetzt_utc=None):
    """Das heutige Datum in Berlin (ersetzt `date.today()` in den Datumsprüfungen)."""
    return berlin_jetzt(jetzt_utc).date()
