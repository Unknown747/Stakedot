#!/usr/bin/env python3
"""
Stake.com Dice CLI
Mainkan dice Stake.com langsung dari terminal menggunakan API resmi.
"""

import os
import sys
import uuid
import time
import requests
from decimal import Decimal, ROUND_DOWN, InvalidOperation

# ─── Config ───────────────────────────────────────────────────────────────────

API_KEY = os.environ.get("STAKE_API_KEY", "")
API_URL = "https://stake.com/_api/graphql"
HEADERS = {
    "Content-Type": "application/json",
    "x-access-token": API_KEY,
}

MAX_CONSECUTIVE_ERRORS = 5  # Berhenti jika gagal N kali berturut-turut

# ─── Warna Terminal ────────────────────────────────────────────────────────────

R      = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
WHITE  = "\033[97m"
DIM    = "\033[2m"


def g(color, text):
    return f"{color}{text}{R}"


# ─── GraphQL ───────────────────────────────────────────────────────────────────

USER_QUERY = """
query Me {
  user {
    name
    balances {
      available {
        amount
        currency
      }
    }
  }
}
"""

DICE_MUTATION = """
mutation DiceRoll(
  $amount: Float!
  $target: Float!
  $condition: CasinoGameDiceConditionEnum!
  $currency: CurrencyEnum!
  $identifier: String!
) {
  diceRoll(
    amount: $amount
    target: $target
    condition: $condition
    currency: $currency
    identifier: $identifier
  ) {
    id
    payoutMultiplier
    amount
    payout
    currency
    result {
      result
      target
      condition
    }
    balance {
      available
      currency
    }
  }
}
"""


def gql(query, variables=None):
    """Kirim GraphQL request dan kembalikan data, atau raise Exception yang jelas."""
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    try:
        resp = requests.post(API_URL, headers=HEADERS, json=payload, timeout=15)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        raise Exception("Tidak dapat terhubung ke Stake.com. Periksa koneksi internet.")
    except requests.exceptions.Timeout:
        raise Exception("Koneksi timeout. Coba lagi.")
    except requests.exceptions.HTTPError as e:
        raise Exception(f"HTTP error {resp.status_code}: {e}")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Request error: {e}")

    try:
        data = resp.json()
    except ValueError:
        raise Exception("Response bukan JSON yang valid dari Stake.com.")

    if "errors" in data:
        msgs = [e.get("message", str(e)) for e in data["errors"]]
        # Deteksi error autentikasi agar loop bisa berhenti
        auth_keywords = ("unauthorized", "unauthenticated", "invalid token", "access denied")
        full_msg = " ".join(msgs).lower()
        if any(k in full_msg for k in auth_keywords):
            raise PermissionError(f"Auth error: {', '.join(msgs)}")
        raise Exception(", ".join(msgs))

    if "data" not in data:
        raise Exception(f"Response tidak mengandung 'data': {data}")

    return data["data"]


# ─── Helper ────────────────────────────────────────────────────────────────────

CURRENCY_LIST = {
    "1": "btc",
    "2": "eth",
    "3": "ltc",
    "4": "doge",
    "5": "xrp",
    "6": "trx",
    "7": "usdt",
    "8": "usdc",
    "9": "bnb",
}

# Presisi desimal per currency
CURRENCY_DECIMALS = {
    "btc": 8, "eth": 8, "ltc": 8, "bch": 8,
    "doge": 4, "xrp": 4, "trx": 4, "eos": 4,
    "bnb": 6, "usdt": 4, "usdc": 4,
}

# Quanta Decimal per currency (untuk ROUND_DOWN)
def _quanta(currency):
    dec = CURRENCY_DECIMALS.get(currency.lower(), 8)
    return Decimal(10) ** -dec


def to_dec(value):
    """Konversi float/string ke Decimal dengan aman."""
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return Decimal("0")


def fmt(amount, currency):
    """Format Decimal atau angka menjadi string yang rapi."""
    d = to_dec(amount)
    quanta = _quanta(currency)
    d = d.quantize(quanta, rounding=ROUND_DOWN)
    return f"{d} {currency.upper()}"


def determine_win(roll_result: dict) -> bool:
    """
    Tentukan menang/kalah berdasarkan data game result dari API,
    bukan dari field payout (lebih akurat dan tidak bergantung pada presisi float).
    """
    rolled = Decimal(str(roll_result["result"]))
    target = Decimal(str(roll_result["target"]))
    condition = roll_result["condition"]
    if condition == "above":
        return rolled > target
    elif condition == "below":
        return rolled < target
    return False


def ask(prompt, validator=None, default=None):
    """Tanya input dengan validasi opsional."""
    while True:
        try:
            raw = input(g(YELLOW, prompt)).strip()
            if not raw and default is not None:
                return default
            if validator:
                result = validator(raw)
                if result is not None:
                    return result
                print(g(RED, "  ✗ Input tidak valid, coba lagi."))
            else:
                return raw
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)


def val_float_positive(s):
    try:
        d = Decimal(s)
        return d if d > 0 else None
    except InvalidOperation:
        return None


def val_target(s):
    try:
        v = float(s)
        return v if 1.01 <= v <= 97.99 else None
    except ValueError:
        return None


def val_int_nonneg(s):
    try:
        v = int(s)
        return v if v >= 0 else None
    except ValueError:
        return None


def val_float_nonneg_or_empty(s):
    if s == "":
        return "__empty__"
    try:
        d = Decimal(s)
        return d if d > 0 else None
    except InvalidOperation:
        return None


# ─── UI ────────────────────────────────────────────────────────────────────────

def print_banner():
    print(g(CYAN, """
╔═══════════════════════════════════════════════════╗
║   ____  _        _          ____  _               ║
║  / ___|| |_ __ _| | _____  |  _ \\(_) ___ ___     ║
║  \\___ \\| __/ _` | |/ / _ \\ | | | | |/ __/ _ \\    ║
║   ___) | || (_| |   <  __/ | |_| | | (_|  __/    ║
║  |____/ \\__\\__,_|_|\\_\\___| |____/|_|\\___\\___|    ║
║                                                   ║
║          Stake.com Dice CLI — by API              ║
╚═══════════════════════════════════════════════════╝
"""))


def print_section(title):
    print(f"\n{g(BLUE, '─' * 50)}")
    print(f"  {g(BOLD, title)}")
    print(g(BLUE, '─' * 50))


def print_summary(stats, currency):
    print_section("RINGKASAN SESI")
    total = stats["total"]
    wins  = stats["wins"]
    losses = stats["losses"]
    profit = stats["profit"]
    win_rate = (Decimal(wins) / Decimal(total) * 100) if total > 0 else Decimal("0")

    profit_color = GREEN if profit >= 0 else RED
    sign = "+" if profit >= 0 else ""

    print(f"  Ronde dimainkan  : {g(BOLD, str(total))}")
    print(f"  Menang           : {g(GREEN, str(wins))}")
    print(f"  Kalah            : {g(RED, str(losses))}")
    print(f"  Win Rate         : {g(BOLD, f'{win_rate:.1f}%')}")
    print(f"  Max Win Streak   : {g(GREEN, str(stats['max_win_streak']))}")
    print(f"  Max Loss Streak  : {g(RED, str(stats['max_loss_streak']))}")
    print(f"  Total Profit     : {g(profit_color, sign + fmt(profit, currency))}")
    print(g(BLUE, '─' * 50))


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not API_KEY:
        print(g(RED, "❌ STAKE_API_KEY tidak ditemukan di environment."))
        print(g(YELLOW, "   Set secret STAKE_API_KEY di Replit Secrets."))
        sys.exit(1)

    print_banner()

    # Login check
    print(g(YELLOW, "⏳ Menghubungkan ke Stake.com..."))
    try:
        user = gql(USER_QUERY)["user"]
    except PermissionError as e:
        print(g(RED, f"❌ API Key tidak valid: {e}"))
        sys.exit(1)
    except Exception as e:
        print(g(RED, f"❌ Gagal login: {e}"))
        sys.exit(1)

    print(g(GREEN, f"✅ Login sebagai: {g(BOLD, user['name'])}"))

    # Tampilkan saldo
    print_section("SALDO AKUN")
    balances = {
        b["available"]["currency"]: b["available"]["amount"]
        for b in user["balances"]
        if Decimal(str(b["available"]["amount"])) > 0
    }
    if balances:
        for cur, amt in balances.items():
            print(f"  {cur.upper():<6} : {g(GREEN, fmt(amt, cur))}")
    else:
        print(g(DIM, "  (semua saldo kosong)"))

    # Pilih currency
    print_section("KONFIGURASI BET")
    print(g(WHITE, "  Pilih currency:"))
    for k, v in CURRENCY_LIST.items():
        print(f"    {k}. {v.upper()}")

    def val_currency(s):
        return CURRENCY_LIST.get(s)

    currency = ask("\nPilihan currency (1-9): ", validator=val_currency)
    print(g(DIM, f"  → {currency.upper()} dipilih\n"))

    # Jumlah bet
    bet_amount: Decimal = ask(
        f"Jumlah bet ({currency.upper()}): ",
        validator=val_float_positive,
    )

    # Target
    print(g(DIM, "\n  Target: angka 1.01 s/d 97.99"))
    target = ask("Target number: ", validator=val_target)

    # Over / Under
    print(g(WHITE, "\n  Kondisi:"))
    print("    1. Over  — hasil LEBIH BESAR dari target")
    print("    2. Under — hasil LEBIH KECIL dari target")

    def val_cond(s):
        return {"1": "above", "2": "below"}.get(s)

    condition = ask("Pilih (1/2): ", validator=val_cond)

    # Hitung peluang & multiplier
    if condition == "above":
        win_chance = Decimal(str(round(100 - target - 0.0001, 4)))
    else:
        win_chance = Decimal(str(round(target - 0.0001, 4)))

    multiplier = (Decimal("99") / win_chance).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    profit_per_win = (bet_amount * multiplier - bet_amount).quantize(_quanta(currency), rounding=ROUND_DOWN)

    print(g(CYAN, f"""
  ┌─────────────────────────────────────────┐
  │  Win Chance  : {win_chance:.4f}%
  │  Multiplier  : {multiplier:.4f}x
  │  Profit/Win  : {fmt(profit_per_win, currency)}
  └─────────────────────────────────────────┘"""))

    # Mode auto / manual
    print_section("MODE BERMAIN")
    print("  1. Manual — tekan Enter tiap ronde")
    print("  2. Auto   — otomatis beberapa ronde")

    def val_mode(s):
        return s if s in ("1", "2") else None

    mode = ask("Pilih mode (1/2): ", validator=val_mode)

    rounds_target = None
    delay = Decimal("1.0")
    stop_profit = None
    stop_loss   = None

    if mode == "2":
        rounds_raw = ask("\nJumlah ronde (0 = tanpa batas): ", validator=val_int_nonneg)
        rounds_target = None if rounds_raw == 0 else rounds_raw

        delay_raw = ask("Jeda antar bet dalam detik (default 1.0): ", default="1.0")
        try:
            delay = max(Decimal("0.1"), Decimal(delay_raw))
        except InvalidOperation:
            delay = Decimal("1.0")

        sp = ask(
            f"\nStop jika profit ≥ (kosong = skip): ",
            validator=val_float_nonneg_or_empty,
            default="",
        )
        stop_profit = None if sp in ("__empty__", "") else Decimal(str(sp))

        sl = ask(
            f"Stop jika loss ≥ (kosong = skip): ",
            validator=val_float_nonneg_or_empty,
            default="",
        )
        stop_loss = None if sl in ("__empty__", "") else Decimal(str(sl))

    # ─── Loop Bermain ──────────────────────────────────────────────────────────

    print_section("BERMAIN")
    print(g(DIM, "  Tekan Ctrl+C untuk berhenti kapan saja.\n"))

    stats = {
        "total": 0,
        "wins": 0,
        "losses": 0,
        "profit": Decimal("0"),
        "max_win_streak": 0,
        "max_loss_streak": 0,
        "_cur_win": 0,
        "_cur_loss": 0,
    }

    ronde           = 0
    consecutive_err = 0

    try:
        while True:
            # Cek batas ronde
            if rounds_target is not None and ronde >= rounds_target:
                print(g(YELLOW, f"\n✅ {rounds_target} ronde selesai."))
                break

            # Manual: tunggu Enter
            if mode == "1":
                try:
                    input(g(YELLOW, f"  [Ronde {ronde + 1}] Tekan Enter untuk bet..."))
                except (EOFError, KeyboardInterrupt):
                    print()
                    break

            # Kirim bet ke Stake
            identifier = str(uuid.uuid4())
            try:
                api_result = gql(DICE_MUTATION, {
                    "amount": float(bet_amount),   # API mengharapkan Float
                    "target": target,
                    "condition": condition,
                    "currency": currency,
                    "identifier": identifier,
                })
                roll = api_result["diceRoll"]
                consecutive_err = 0  # reset error counter
            except PermissionError as e:
                # Auth error: tidak ada gunanya retry
                print(g(RED, f"\n  ❌ Auth error, sesi dihentikan: {e}"))
                break
            except Exception as e:
                consecutive_err += 1
                print(g(RED, f"  ❌ Error API ({consecutive_err}/{MAX_CONSECUTIVE_ERRORS}): {e}"))
                if consecutive_err >= MAX_CONSECUTIVE_ERRORS:
                    print(g(RED, "  🛑 Terlalu banyak error berturut-turut. Sesi dihentikan."))
                    break
                time.sleep(2)
                continue

            ronde += 1
            stats["total"] = ronde

            # Tentukan menang/kalah dari data game result (bukan dari payout float)
            won = determine_win(roll["result"])

            # Hitung profit dengan Decimal untuk presisi tinggi
            payout     = to_dec(roll["payout"])
            amount_dec = to_dec(roll["amount"])
            profit     = (payout - amount_dec).quantize(_quanta(currency), rounding=ROUND_DOWN)

            stats["profit"] += profit

            rolled_num  = float(roll["result"]["result"])
            balance_raw = roll.get("balance")
            balance_str = fmt(balance_raw["available"], currency) if balance_raw else "N/A"

            if won:
                stats["wins"] += 1
                stats["_cur_win"] += 1
                stats["_cur_loss"] = 0
                stats["max_win_streak"] = max(stats["max_win_streak"], stats["_cur_win"])
                result_icon = g(GREEN, "✅ MENANG")
                profit_str  = g(GREEN, f"+{fmt(profit, currency)}")
            else:
                stats["losses"] += 1
                stats["_cur_loss"] += 1
                stats["_cur_win"] = 0
                stats["max_loss_streak"] = max(stats["max_loss_streak"], stats["_cur_loss"])
                result_icon = g(RED, "❌ KALAH ")
                profit_str  = g(RED, fmt(profit, currency))   # profit sudah negatif

            total_profit_color = GREEN if stats["profit"] >= 0 else RED
            total_sign = "+" if stats["profit"] >= 0 else ""
            win_rate   = Decimal(stats["wins"]) / Decimal(ronde) * 100

            print(
                f"  {g(DIM, f'#{ronde:<4}')} "
                f"Roll: {g(BOLD, f'{rolled_num:>6.2f}')} | "
                f"{result_icon} {profit_str:<28} | "
                f"Saldo: {g(CYAN, balance_str)}"
            )
            print(
                f"         "
                f"W/L: {g(GREEN, str(stats['wins']))}/{g(RED, str(stats['losses']))} "
                f"({win_rate:.1f}%) | "
                f"Total: {g(total_profit_color, total_sign + fmt(stats['profit'], currency))}"
            )
            print()

            # Cek stop conditions
            if stop_profit is not None and stats["profit"] >= stop_profit:
                print(g(GREEN, f"  🎯 Target profit tercapai! +{fmt(stats['profit'], currency)}"))
                break
            if stop_loss is not None and stats["profit"] <= -abs(stop_loss):
                print(g(RED, f"  🛑 Batas loss tercapai! {fmt(stats['profit'], currency)}"))
                break

            if mode == "2":
                time.sleep(float(delay))

    except KeyboardInterrupt:
        print(g(YELLOW, "\n\n  ⏹  Dihentikan oleh pengguna."))

    print_summary(stats, currency)


if __name__ == "__main__":
    main()
