# Memecoin Papier-Bot (nur Fake-Geld)

Testet eine Memecoin-Strategie auf Solana, ohne echtes Geld und ohne Wallet.

## Starten
1. Python 3 installieren (python.org, kostenlos). Mehr braucht es nicht.
2. `python3 paper_bot.py` starten (oder `python3 paper_bot.py --once` für einen einzelnen Durchlauf).
3. Ergebnisse stehen in `trades.csv` (alle Käufe/Verkäufe) und `state.json` (Kontostand).

## Strategie (alles oben in der Datei einstellbar)
- Kandidaten: neue/gehypte Solana-Coins (DexScreener)
- Filter: genug Liquidität und Volumen, Alter 30 Min bis 24 Std, mehr Käufer als Verkäufer, Momentum +10 % bis +150 % in der letzten Stunde
- Rug-Check (RugCheck): bei "danger"-Risiko oder Fehler wird nicht gekauft
- Risiko: max. 10 % des Budgets pro Trade, max. 3 Positionen, Stop-Loss -25 %, Take-Profit +60 %, Zeitlimit 2 Std, Tagesverlust-Limit 20 %
- 4 % Kosten pro Kauf/Verkauf eingerechnet (Slippage + Gebühren), damit die Ergebnisse nicht zu schön sind

## Lernen aus Fehlern
- **Nach jedem Trade:** Der Bot schreibt eine Lektion ins `journal.json` und schickt sie dir per Telegram, z. B. "Sofort-Absturz (vermutlich Pump gekauft)" oder "Gewinn nicht gesichert (war bei +35 %, dann Stop-Loss)".
- **Alle 15 Trades:** Er vergleicht Gewinner und Verlierer (Liquidität, Volumen, Käufer/Verkäufer, Alter, Kursplus) und ändert maximal 2 Einstellungen um je 10 %. Er kann auch selbst einen Trailing-Stop einschalten, wenn zu viele Verlierer vorher schon im Plus waren.
- **Sicherung:** Wird es nach einer Änderung merklich schlechter, setzt er sie automatisch zurück. Es gibt feste Grenzen, die er nie überschreitet. Stop-Loss, Budget und Tageslimit lernt er bewusst NICHT selbst, das bleibt deine Entscheidung.
- Alle Änderungen stehen in `lern_log.txt`, die aktuellen Werte in `learned_params.json`. Zum Zurücksetzen diese Datei löschen.
- **Grenze:** Mit wenigen Trades ist vieles Zufall. Der Bot wird nicht automatisch profitabel, er wird nur vorsichtig besser. Aussagekräftig wird es erst nach 100+ Trades.

## Notaus
Lege im Ordner eine leere Datei namens `STOP` an: dann kauft der Bot nichts Neues mehr.

## Handy-Benachrichtigungen (optional, kostenlos)
1. In Telegram mit @BotFather einen Bot anlegen und den Token kopieren.
2. Dem Bot schreiben, dann deine Chat-ID über @userinfobot herausfinden.
3. Vor dem Start setzen: `TELEGRAM_TOKEN=...` und `TELEGRAM_CHAT_ID=...`

## Wichtig
- Mindestens 2 bis 4 Wochen laufen lassen und `trades.csv` auswerten, bevor an echtes Geld gedacht wird.
- Ein positives Papier-Ergebnis garantiert nichts: Echte Trades haben mehr Slippage, Verzögerung und Honeypots.
- Gewinne aus Krypto sind steuerpflichtig.
