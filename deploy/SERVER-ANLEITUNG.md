# Bot auf einem kostenlosen Server laufen lassen (nur mit dem iPhone)

Voraussetzung: Telegram-Bot (Token + Chat-ID), sonst siehst du vom Server aus nichts. Anleitung in README.md.

1. Oracle Cloud "Always Free" Konto anlegen (cloud.oracle.com). Es braucht eine Kreditkarte zur Prüfung. Bleib bei den Always-Free-Ressourcen.
2. Compute -> Instances -> Create instance. Image: Ubuntu (24.04 oder 22.04). Shape: eine als "Always Free eligible" markierte.
3. Unter "Advanced options" -> "Management" -> "Cloud-init script" den Inhalt von `deploy/cloud-init.sh` einfügen. Vorher die beiden Zeilen mit TELEGRAM_TOKEN und TELEGRAM_CHAT_ID ausfüllen.
4. SSH-Schlüssel erzeugen lassen und herunterladen (auch wenn du ihn selten brauchst). Create.
5. Nach 3 bis 5 Minuten kommt in Telegram "Papier-Bot gestartet".
6. WICHTIG: Danach auf GitHub unter Actions -> Papier-Bot -> "..." -> Disable workflow, damit nicht zwei Bots gleichzeitig laufen.

Hinweise
- Spielstand (state.json, trades.csv, journal.json) liegt ab jetzt auf dem Server, nicht mehr im Repo.
- Der Bot-Code aktualisiert sich jede Nacht um 04:00 UTC automatisch aus diesem Repo.
- Oracle kann ungenutzte Always-Free-Server nach einiger Zeit zurückfordern und hat manchmal keine freie Kapazität.
