#!/usr/bin/env python3
"""
Memecoin Paper-Trading-Bot (Solana) mit Lernmodul
- Handelt NUR mit Fake-Geld. Kein Wallet, kein Private Key, kein echtes Geld.
- Nutzt kostenlose öffentliche APIs (DexScreener, RugCheck), nur Python-Standardbibliothek.
- Start:         python3 paper_bot.py
- Ein Durchlauf: python3 paper_bot.py --once
- Notaus:        Datei namens STOP im selben Ordner anlegen -> keine neuen Käufe mehr
- Telegram (optional): Umgebungsvariablen TELEGRAM_TOKEN und TELEGRAM_CHAT_ID setzen

LERNEN:
- Nach JEDEM Trade wird eine Fehleranalyse ins Journal (journal.json) geschrieben.
- Alle LEARN_EVERY Trades wertet der Bot Gewinner und Verlierer aus und passt maximal
  2 Einstellungen um je 10 % an (innerhalb fester Grenzen). Alles steht in lern_log.txt.
- Wird es nach einer Anpassung schlechter, macht der Bot sie automatisch rückgängig.
"""
import csv
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from statistics import mean, median

# ===================== FESTE EINSTELLUNGEN (lernt der Bot NICHT) =====================
START_BUDGET_USD = 50.0        # virtuelles Startkapital
MAX_PER_TRADE_PCT = 0.10       # max. 10 % des Startkapitals pro Trade
MAX_OPEN_POSITIONS = 3         # max. gleichzeitig offene Trades
MAX_HOLD_MIN = 120             # spätestens nach 2 Stunden raus
DAILY_LOSS_LIMIT_PCT = 0.20    # Tagesverlust-Limit: danach keine neuen Käufe
COST_PER_SIDE = 0.04           # Slippage + Gebühren pro Kauf/Verkauf (4 %, realistisch)
MAX_AGE_HOURS = 72
MAX_FDV = 5_000_000
SCAN_INTERVAL_SEC = 60

# ===================== LERN-EINSTELLUNGEN =====================
LEARN_EVERY = 15               # so viele neue Trades, bevor angepasst wird
MIN_GROUP = 4                  # mindestens so viele Gewinner UND Verlierer nötig
STEP = 0.10                    # max. 10 % Änderung pro Anpassung
MAX_CHANGES_PER_ROUND = 2      # nie alles auf einmal ändern
ROLLBACK_TOLERANCE = 0.03      # wird der Schnitt um mehr als 3 %-Punkte schlechter -> zurück

# Startwerte der anpassbaren Einstellungen (werden aus learned_params.json überschrieben)
DEFAULT_P = {
    # Strategie 2 ("Bestaetigung statt Pump"): nur etablierte, liquide Coins, die gerade NICHT
    # frisch gepumpt sind, aber im Aufwaertstrend liegen. Engere Stops, kleinere Ziele.
    "stop_loss": -0.15,        # bei -15 % verkaufen
    "take_profit": 0.35,       # Rest bei +35 % verkaufen
    "tp1": 0.15,               # Teilgewinn: bei +15 % wird ein Teil verkauft ...
    "tp1_fraction": 0.5,       # ... und zwar die Haelfte der Position; danach Stop auf Einstand
    "min_liquidity": 50_000,
    "min_volume_h1": 50_000,
    "min_age_min": 360,        # mind. 6 Stunden alt
    "min_buy_sell_ratio": 1.1,
    "min_change_h1": 0,
    "max_change_h1": 30,       # nicht kaufen, wenn schon stark gepumpt
    "min_change_m5": 0,        # Kurs der letzten 5 Min darf nicht fallen
    "min_change_h6": 0,        # 6h-Trend muss positiv sein
    "trail_start": 0.0,        # 0 = Trailing-Stop aus; Bot kann ihn selbst einschalten
    "trail_gap": 0.15,
}
# harte Grenzen: der Bot darf nie ausserhalb davon landen
BOUNDS = {
    "min_liquidity": (30_000, 200_000),
    "min_volume_h1": (30_000, 200_000),
    "min_age_min": (120, 1440),
    "min_buy_sell_ratio": (1.0, 3.0),
    "min_change_h1": (0, 60),
    "max_change_h1": (15, 100),
}

# Dauerbetrieb (z. B. Railway): Spielstand liegt in DATA_DIR (dort ein dauerhaftes Laufwerk einhängen).
# Ohne DATA_DIR bleibt alles im Programmordner wie bisher.
DATA_DIR = os.environ.get("DATA_DIR", ".")
APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(DATA_DIR, exist_ok=True)

STATE_FILE = os.path.join(DATA_DIR, "state.json")
TRADES_FILE = os.path.join(DATA_DIR, "trades.csv")
JOURNAL_FILE = os.path.join(DATA_DIR, "journal.json")
PARAMS_FILE = os.path.join(DATA_DIR, "learned_params.json")
LEARN_LOG_FILE = os.path.join(DATA_DIR, "lern_log.txt")
STOP_FILE = os.path.join(DATA_DIR, "STOP")

SCAN_EVERY_N_CYCLES = 5        # Dauerbetrieb: offene Trades jede Minute prüfen, neue Coins nur alle 5 Minuten suchen

DEX = "https://api.dexscreener.com"
RUGCHECK = "https://api.rugcheck.xyz/v1/tokens/{}/report/summary"


def now():
    return datetime.now(timezone.utc)


def http_get_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "paper-bot/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"[warn] Abruf fehlgeschlagen: {url} ({e})")
        return None


def telegram(text):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    print(text)
    if not token or not chat:
        return
    try:
        data = json.dumps({"chat_id": chat, "text": text}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"[warn] Telegram fehlgeschlagen: {e}")


# ---------- Dateien ----------
def load_json(path, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_params():
    p = dict(DEFAULT_P)
    p.update(load_json(PARAMS_FILE, {}))
    return p


def seed_data():
    """Beim ersten Start auf einem neuen Laufwerk den bisherigen Spielstand aus dem Programmordner übernehmen."""
    if os.path.abspath(DATA_DIR) == APP_DIR or os.environ.get("SEED_OLD") != "1":
        return
    for name in ("state.json", "trades.csv", "journal.json", "learned_params.json", "lern_log.txt"):
        src, dst = os.path.join(APP_DIR, name), os.path.join(DATA_DIR, name)
        if os.path.exists(src) and not os.path.exists(dst):
            with open(src, "rb") as fi, open(dst, "wb") as fo:
                fo.write(fi.read())
            print(f"[info] {name} aus dem Programmordner übernommen")


seed_data()
P = load_params()


def save_params():
    save_json(PARAMS_FILE, P)


def load_state():
    state = load_json(STATE_FILE, {"cash": START_BUDGET_USD, "positions": [], "traded": [],
                                   "realized_by_day": {}})
    state.setdefault("learn", {"last_idx": 0, "pending": None})
    return state


def save_state(state):
    save_json(STATE_FILE, state)


def log_trade(row):
    new = not os.path.exists(TRADES_FILE)
    with open(TRADES_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["zeit", "aktion", "symbol", "adresse", "preis", "usd", "pnl_usd", "grund"])
        w.writerow(row)


def learn_log(text):
    line = f"[{now().strftime('%Y-%m-%d %H:%M')}] {text}"
    with open(LEARN_LOG_FILE, "a") as f:
        f.write(line + "\n")
    telegram("🧠 " + text)


# ---------- Daten ----------
def get_candidates():
    """Neue/gehypte Solana-Tokens von DexScreener."""
    addrs = []
    for path in ("/token-profiles/latest/v1", "/token-boosts/latest/v1"):
        data = http_get_json(DEX + path)
        if isinstance(data, list):
            for t in data:
                if t.get("chainId") == "solana" and t.get("tokenAddress"):
                    addrs.append(t["tokenAddress"])
    return list(dict.fromkeys(addrs))  # Duplikate raus, Reihenfolge behalten


def get_pair(addr):
    data = http_get_json(f"{DEX}/latest/dex/tokens/{addr}")
    if not data or not data.get("pairs"):
        return None
    pairs = [p for p in data["pairs"] if p.get("chainId") == "solana"]
    if not pairs:
        return None
    return max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)


def rug_ok(addr):
    """Fail-closed: bei Fehler oder 'danger'-Risiko wird NICHT gekauft."""
    data = http_get_json(RUGCHECK.format(addr))
    if not isinstance(data, dict):
        return False, "Rug-Check nicht erreichbar"
    for risk in data.get("risks") or []:
        if str(risk.get("level", "")).lower() == "danger":
            return False, f"Rug-Risiko: {risk.get('name', '?')}"
    return True, "ok"


def features(pair):
    """Kennzahlen eines Coins zum Kaufzeitpunkt (Grundlage zum Lernen)."""
    liq = (pair.get("liquidity") or {}).get("usd") or 0
    vol = (pair.get("volume") or {}).get("h1") or 0
    chg = (pair.get("priceChange") or {}).get("h1")
    tx = (pair.get("txns") or {}).get("h1") or {}
    buys, sells = tx.get("buys", 0), tx.get("sells", 0)
    created = pair.get("pairCreatedAt")
    age = None if created is None else (now().timestamp() * 1000 - created) / 60000
    return {"liq": liq, "vol": vol, "chg": chg, "ratio": (buys / sells) if sells else None,
            "age": age, "fdv": pair.get("fdv") or 0}


def passes_filters(pair):
    f = features(pair)
    if not pair.get("priceUsd"):
        return False, "kein Preis"
    if f["age"] is None:
        return False, "Alter unbekannt"
    if f["age"] < P["min_age_min"]:
        return False, "zu neu"
    if f["age"] > MAX_AGE_HOURS * 60:
        return False, "zu alt"
    if f["liq"] < P["min_liquidity"]:
        return False, "zu wenig Liquidität"
    if f["vol"] < P["min_volume_h1"]:
        return False, "zu wenig Volumen"
    if f["fdv"] and f["fdv"] > MAX_FDV:
        return False, "zu hohe Bewertung"
    if f["chg"] is None or not (P["min_change_h1"] <= f["chg"] <= P["max_change_h1"]):
        return False, "Momentum passt nicht"
    if f["ratio"] is None or f["ratio"] < P["min_buy_sell_ratio"]:
        return False, "zu wenig Käufer"
    pc = pair.get("priceChange") or {}
    if pc.get("m5") is None or pc["m5"] < P["min_change_m5"]:
        return False, "Kurs faellt gerade (5 Min)"
    if pc.get("h6") is None or pc["h6"] < P["min_change_h6"]:
        return False, "6h-Trend negativ"
    return True, "ok"


# ---------- Trading (Fake-Geld) ----------
def equity(state, prices=None):
    total = state["cash"]
    for p in state["positions"]:
        price = (prices or {}).get(p["addr"], p["entry_price"])
        total += p["tokens"] * price * (1 - COST_PER_SIDE)
    return total


def realized_today(state):
    return state["realized_by_day"].get(now().strftime("%Y-%m-%d"), 0.0)


def can_open(state):
    if os.environ.get("BOT_STOP") == "1" or os.path.exists(STOP_FILE):
        return False, "Notaus (BOT_STOP=1 oder STOP-Datei)"
    if len(state["positions"]) >= MAX_OPEN_POSITIONS:
        return False, "max. Positionen erreicht"
    if realized_today(state) <= -DAILY_LOSS_LIMIT_PCT * START_BUDGET_USD:
        return False, "Tagesverlust-Limit erreicht"
    if state["cash"] < 1:
        return False, "kein Guthaben"
    return True, "ok"


def open_position(state, pair):
    size = min(state["cash"], START_BUDGET_USD * MAX_PER_TRADE_PCT)
    price = float(pair["priceUsd"])
    tokens = size * (1 - COST_PER_SIDE) / price
    addr = pair["baseToken"]["address"]
    sym = pair["baseToken"].get("symbol", "?")
    state["cash"] -= size
    state["traded"].append(addr)
    state["positions"].append(
        {"addr": addr, "symbol": sym, "entry_price": price, "tokens": tokens,
         "cost": size, "cost0": size, "opened": now().isoformat(), "peak": price,
         "features": features(pair)}
    )
    log_trade([now().isoformat(), "KAUF", sym, addr, price, round(size, 2), "", "Strategie-Signal"])
    telegram(f"📈 PAPIER-KAUF {sym}: ${size:.2f} @ {price:.8f}")


# ---------- Fehleranalyse pro Trade ----------
def diagnose(t):
    """Gibt eine kurze Ursache für einen Verlust zurück (bei Gewinn: 'Gewinn')."""
    if t["pnl"] > 0:
        return "Gewinn"
    if t["reason"] == "Stop-Loss" and t["peak_pct"] >= 0.30:
        return f"Gewinn nicht gesichert (war bei +{t['peak_pct']*100:.0f} %, dann Stop-Loss)"
    if t["reason"] == "Stop-Loss" and t["held_min"] < 15:
        return "Sofort-Absturz (vermutlich Pump gekauft)"
    if t["reason"] == "Stop-Loss":
        return "Trend hat gedreht"
    if t["reason"] in ("Zeitlimit", "Trailing-Stop"):
        return "Kein Momentum (Ausstieg mit Minus)"
    if t["reason"] == "Einstands-Stop":
        return "Kein Momentum nach Teilgewinn (Rest knapp im Minus)"
    return "Sonstiges"


def partial_sell(state, pos, price):
    """Teilgewinn mitnehmen: verkauft einen Teil der Position, der Rest läuft weiter."""
    frac = P["tp1_fraction"]
    sold = pos["tokens"] * frac
    value = sold * price * (1 - COST_PER_SIDE)
    cost_part = pos["cost"] * frac
    pnl = value - cost_part
    pos["tokens"] -= sold
    pos["cost"] -= cost_part
    pos["realized_pnl"] = pos.get("realized_pnl", 0.0) + pnl
    pos["tp1_done"] = True
    state["cash"] += value
    day = now().strftime("%Y-%m-%d")
    state["realized_by_day"][day] = state["realized_by_day"].get(day, 0.0) + pnl
    log_trade([now().isoformat(), "TEILVERKAUF", pos["symbol"], pos["addr"], price,
               round(value, 2), round(pnl, 2), "Teilgewinn"])
    telegram(f"💰 TEILGEWINN {pos['symbol']}: {frac*100:.0f} % verkauft, {pnl:+.2f} USD gesichert. "
             f"Rest läuft mit Stop auf Einstand.")


def close_position(state, pos, price, reason):
    value = pos["tokens"] * price * (1 - COST_PER_SIDE)
    pnl_rest = value - pos["cost"]                 # nur der Rest der Position
    pnl = pnl_rest + pos.get("realized_pnl", 0.0)  # plus bereits gesicherter Teilgewinn
    cost0 = pos.get("cost0", pos["cost"])          # ursprünglicher Einsatz
    state["cash"] += value
    state["positions"].remove(pos)
    day = now().strftime("%Y-%m-%d")
    state["realized_by_day"][day] = state["realized_by_day"].get(day, 0.0) + pnl_rest
    log_trade([now().isoformat(), "VERKAUF", pos["symbol"], pos["addr"], price,
               round(value, 2), round(pnl_rest, 2), reason])

    held = (now() - datetime.fromisoformat(pos["opened"])).total_seconds() / 60
    entry = {
        "zeit": now().isoformat(), "symbol": pos["symbol"], "addr": pos["addr"],
        "pnl": round(pnl, 4), "pnl_pct": round(pnl / cost0, 4), "reason": reason,
        "held_min": round(held, 1),
        "peak_pct": round(pos.get("peak", pos["entry_price"]) / pos["entry_price"] - 1, 4),
        "features": pos.get("features", {}),
        "params": dict(P),
    }
    entry["lektion"] = diagnose(entry)
    journal = load_json(JOURNAL_FILE, [])
    journal.append(entry)
    save_json(JOURNAL_FILE, journal)

    icon = "✅" if pnl >= 0 else "🔻"
    telegram(f"{icon} PAPIER-VERKAUF {pos['symbol']} ({reason}): {pnl:+.2f} USD | "
             f"Lektion: {entry['lektion']}")


def check_positions(state):
    prices = {}
    for pos in list(state["positions"]):
        pair = get_pair(pos["addr"])
        if not pair or not pair.get("priceUsd"):
            continue
        price = float(pair["priceUsd"])
        prices[pos["addr"]] = price
        pos["peak"] = max(pos.get("peak", pos["entry_price"]), price)
        change = price / pos["entry_price"] - 1
        peak_change = pos["peak"] / pos["entry_price"] - 1
        held_min = (now() - datetime.fromisoformat(pos["opened"])).total_seconds() / 60
        if (not pos.get("tp1_done") and P["tp1"] and change >= P["tp1"]
                and change < P["take_profit"]):
            partial_sell(state, pos, price)   # Teilgewinn sichern, Rest läuft weiter
            continue
        if pos.get("tp1_done") and change <= 0:
            close_position(state, pos, price, "Einstands-Stop")
        elif not pos.get("tp1_done") and change <= P["stop_loss"]:
            close_position(state, pos, price, "Stop-Loss")
        elif change >= P["take_profit"]:
            close_position(state, pos, price, "Take-Profit")
        elif (P["trail_start"] and peak_change >= P["trail_start"]
              and price <= pos["peak"] * (1 - P["trail_gap"])):
            close_position(state, pos, price, "Trailing-Stop")
        elif held_min >= MAX_HOLD_MIN:
            close_position(state, pos, price, "Zeitlimit")
    return prices


# ---------- Lernen ----------
def clamp(key, value):
    lo, hi = BOUNDS[key]
    return round(min(max(value, lo), hi), 2)


def med(trades, feat):
    vals = [t["features"].get(feat) for t in trades if t.get("features", {}).get(feat) is not None]
    return median(vals) if vals else None


def adapt(state):
    journal = load_json(JOURNAL_FILE, [])
    ln = state.setdefault("learn", {"last_idx": 0, "pending": None})
    batch = journal[ln["last_idx"]:]
    if len(batch) < LEARN_EVERY:
        return
    ln["last_idx"] = len(journal)
    batch_avg = mean(t["pnl_pct"] for t in batch)

    # 1) Letzte Anpassung prüfen: war sie schlecht, wird sie zurückgenommen
    pending = ln.get("pending")
    if pending:
        ln["pending"] = None
        if batch_avg < pending["prev_avg"] - ROLLBACK_TOLERANCE:
            P.clear()
            P.update(pending["prev_params"])
            save_params()
            learn_log(f"ZURÜCKGESETZT: letzte Anpassung half nicht (Schnitt pro Trade "
                      f"{batch_avg*100:+.1f} % statt vorher {pending['prev_avg']*100:+.1f} %). "
                      f"Alte Einstellungen sind wieder aktiv.")
            return
        learn_log(f"Letzte Anpassung behalten (Schnitt pro Trade {batch_avg*100:+.1f} % "
                  f"statt vorher {pending['prev_avg']*100:+.1f} %).")

    # 2) Gewinner und Verlierer vergleichen
    wins = [t for t in batch if t["pnl"] > 0]
    losses = [t for t in batch if t["pnl"] <= 0]
    gründe = {}
    for t in losses:
        gründe[t["lektion"]] = gründe.get(t["lektion"], 0) + 1
    top = ", ".join(f"{k} ({v}x)" for k, v in sorted(gründe.items(), key=lambda x: -x[1])[:3])
    learn_log(f"Auswertung {len(batch)} Trades: {len(wins)} Gewinner, {len(losses)} Verlierer, "
              f"Schnitt {batch_avg*100:+.1f} % pro Trade. Häufigste Fehler: {top or '-'}")
    if len(wins) < MIN_GROUP or len(losses) < MIN_GROUP:
        learn_log("Zu wenig Gewinner oder Verlierer für eine sinnvolle Anpassung. Keine Änderung.")
        return

    candidates = []  # (Stärke, Einstellung, neuer Wert, Begründung)

    def higher_is_better(key, feat, label):
        mw, ml = med(wins, feat), med(losses, feat)
        if mw and ml is not None and ml < 0.85 * mw:
            strength = mw / ml if ml > 0 else 3
            new = clamp(key, P[key] * (1 + STEP))
            candidates.append((strength, key, new,
                               f"Verlierer hatten {label} ~{ml:.2f}, Gewinner ~{mw:.2f}"))

    higher_is_better("min_liquidity", "liq", "Liquidität")
    higher_is_better("min_volume_h1", "vol", "Volumen")
    higher_is_better("min_buy_sell_ratio", "ratio", "Käufer/Verkäufer")
    higher_is_better("min_age_min", "age", "Alter (Min)")
    higher_is_better("min_change_h1", "chg", "Kursplus 1h")

    mw, ml = med(wins, "chg"), med(losses, "chg")
    if mw and ml is not None and ml > 1.15 * mw:
        candidates.append((ml / mw, "max_change_h1", clamp("max_change_h1", P["max_change_h1"] * (1 - STEP)),
                           f"Verlierer hatten schon Kursplus 1h ~{ml:.0f} %, Gewinner ~{mw:.0f} %"))

    late = [t for t in losses if t["peak_pct"] >= 0.30]
    if len(late) / len(losses) >= 0.3 and not P["trail_start"]:
        candidates.append((3, "trail_start", 0.30,
                           f"{len(late)} von {len(losses)} Verlierern waren vorher schon bei +30 % oder mehr"))

    candidates = [c for c in candidates if c[2] != P.get(c[1])]
    if not candidates:
        learn_log("Keine Anpassung nötig.")
        return
    candidates.sort(key=lambda c: -c[0])
    prev = dict(P)
    for _, key, new, why in candidates[:MAX_CHANGES_PER_ROUND]:
        old = P[key]
        P[key] = new
        learn_log(f"ANPASSUNG {key}: {old} -> {new} ({why})")
    save_params()
    ln["pending"] = {"prev_params": prev, "prev_avg": batch_avg}


def scan_for_entries(state):
    ok, why = can_open(state)
    if not ok:
        print(f"[info] keine neuen Käufe: {why}")
        return
    for addr in get_candidates():
        if addr in state["traded"] or any(p["addr"] == addr for p in state["positions"]):
            continue
        pair = get_pair(addr)
        if not pair:
            continue
        good, _ = passes_filters(pair)
        if not good:
            continue
        safe, why = rug_ok(addr)
        if not safe:
            print(f"[skip] {pair['baseToken'].get('symbol')}: {why}")
            continue
        open_position(state, pair)
        ok, _ = can_open(state)
        if not ok:
            break


def print_summary(state, prices):
    eq = equity(state, prices)
    print(f"[{now().strftime('%H:%M:%S')}] Wert: ${eq:.2f} (Start ${START_BUDGET_USD:.2f}) | "
          f"offen: {len(state['positions'])} | realisiert heute: {realized_today(state):+.2f}")


def run_cycle(state, scan=True):
    prices = check_positions(state)
    adapt(state)
    if scan:
        scan_for_entries(state)
    save_state(state)
    print_summary(state, prices)


def main():
    state = load_state()
    if "--once" in sys.argv:
        run_cycle(state)  # z. B. für GitHub Actions: kein Start-Spam alle 5 Minuten
        return
    telegram(f"🤖 Papier-Bot gestartet. Fake-Budget: ${START_BUDGET_USD:.2f}")
    try:
        n = 0
        while True:
            try:
                run_cycle(state, scan=(n % SCAN_EVERY_N_CYCLES == 0))
            except Exception as e:  # ein Fehler darf den Dauerbetrieb nicht beenden
                print(f"[fehler] Durchlauf fehlgeschlagen: {e!r}")
            n += 1
            time.sleep(SCAN_INTERVAL_SEC)
    except KeyboardInterrupt:
        save_state(state)
        print("Bot beendet.")


if __name__ == "__main__":
    main()
