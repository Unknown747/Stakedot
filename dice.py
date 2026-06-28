#!/usr/bin/env python3
"""
Stake.com Dice CLI
Mainkan dice Stake.com langsung dari terminal menggunakan API resmi.
"""

import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv tidak wajib — gunakan export STAKE_API_KEY=... di terminal
import sys
import uuid
import time
import random
import csv
import requests
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from datetime import datetime

# ─── Config ───────────────────────────────────────────────────────────────────

API_KEY          = os.environ.get("STAKE_API_KEY", "")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

API_URL = "https://stake.com/_api/graphql"
HEADERS = {
    "Content-Type": "application/json",
    "x-access-token": API_KEY,
}

MAX_CONSECUTIVE_ERRORS = 5  # Berhenti jika gagal N kali berturut-turut


def kirim_telegram(pesan: str):
    """
    Kirim notifikasi teks ke Telegram.
    Butuh env vars: TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID.
    Diam-diam (silent fail) jika token tidak diset — tidak crash script.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": pesan, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass  # Notifikasi gagal tidak boleh menghentikan script

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
    flagProgress {
      flag
      progress
    }
  }
}
"""

# ─── VIP Config ────────────────────────────────────────────────────────────────

# Level VIP Stake.com — urutan eksplisit untuk lookup next-level yang akurat
VIP_LEVELS = {
    "none":        {"label": "Non-VIP",      "min_usd": 0,          "next_usd": 10_000,    "color": DIM},
    "bronze":      {"label": "🥉 Bronze",    "min_usd": 10_000,     "next_usd": 50_000,    "color": "\033[33m"},
    "silver":      {"label": "🥈 Silver",    "min_usd": 50_000,     "next_usd": 100_000,   "color": "\033[37m"},
    "gold":        {"label": "🥇 Gold",      "min_usd": 100_000,    "next_usd": 250_000,   "color": "\033[93m"},
    "platinum":    {"label": "💎 Platinum",  "min_usd": 250_000,    "next_usd": 500_000,   "color": "\033[96m"},
    "platinumii":  {"label": "💎 Platinum II", "min_usd": 500_000,  "next_usd": 1_000_000, "color": "\033[96m"},
    "platinumiii": {"label": "💎 Platinum III","min_usd": 1_000_000,"next_usd": 2_500_000, "color": "\033[96m"},
    "diamond":     {"label": "👑 Diamond",   "min_usd": 25_000_000, "next_usd": None,      "color": "\033[95m"},
}

# Urutan level eksplisit — dipakai untuk lookup next-level yang benar
VIP_ORDER = ["none", "bronze", "silver", "gold", "platinum", "platinumii", "platinumiii", "diamond"]

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
    state {
      ... on CasinoGameDice {
        result
        target
        condition
      }
    }
    user {
      balances {
        available {
          amount
          currency
        }
      }
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
        msgs      = [e.get("message", str(e)) for e in data["errors"]]
        err_types = [e.get("errorType", "") for e in data["errors"]]
        full_msg  = " ".join(msgs).lower()
        # Deteksi session expired / auth error → PermissionError agar loop berhenti
        auth_keywords  = ("unauthorized", "unauthenticated", "invalid token",
                          "access denied", "session has expired", "disabledsession")
        auth_err_types = ("disabledSession", "forbidden", "unauthorized")
        if (any(k in full_msg for k in auth_keywords)
                or any(t in auth_err_types for t in err_types)):
            raise PermissionError(
                "API Key expired atau tidak valid. "
                "Generate API Key baru di Stake.com → Settings → API, "
                "lalu update Secret STAKE_API_KEY di Replit."
            )
        raise Exception(", ".join(msgs))

    if "data" not in data:
        raise Exception(f"Response tidak mengandung 'data': {data}")

    return data["data"]


# ─── Helper ────────────────────────────────────────────────────────────────────

CURRENCY_LIST = {
    "1":  "btc",
    "2":  "eth",
    "3":  "ltc",
    "4":  "doge",
    "5":  "xrp",
    "6":  "trx",
    "7":  "usdt",
    "8":  "usdc",
    "9":  "bnb",
    "10": "idr",
}

# Presisi desimal per currency
CURRENCY_DECIMALS = {
    "btc": 8, "eth": 8, "ltc": 8, "bch": 8,
    "doge": 4, "xrp": 4, "trx": 4, "eos": 4,
    "bnb": 6, "usdt": 4, "usdc": 4,
    "idr": 2,   # Rupiah — 2 desimal
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
    Tentukan menang/kalah berdasarkan data game result dari API.
    Aman terhadap dict kosong — fallback ke False jika field tidak lengkap.
    """
    if not roll_result:
        return False
    try:
        rolled    = Decimal(str(roll_result["result"]))
        target    = Decimal(str(roll_result["target"]))
        condition = roll_result["condition"]
        if condition == "above":
            return rolled > target
        elif condition == "below":
            return rolled < target
    except (KeyError, TypeError, InvalidOperation):
        pass
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

CSV_LOG = "log_sesi.csv"   # File log sesi otomatis


def print_vip_status(flag_progress: dict):
    """
    Tampilkan status VIP akun secara visual di atas CLI.
    Selalu dipanggil otomatis sebelum sesi Strategy VIP dimulai.
    """
    flag     = (flag_progress.get("flag") or "none").lower().replace(" ", "")
    progress = float(flag_progress.get("progress") or 0)  # 0.0 – 1.0

    info  = VIP_LEVELS.get(flag, VIP_LEVELS["none"])
    color = info["color"]
    label = info["label"]
    pct   = progress * 100

    # Progress bar 30 karakter
    bar_len = 30
    filled  = int(progress * bar_len)
    bar     = f"{color}{'█' * filled}{R}{DIM}{'░' * (bar_len - filled)}{R}"

    # Hitung sisa wager USD ke level berikutnya (gunakan VIP_ORDER untuk lookup akurat)
    next_usd = info["next_usd"]
    min_usd  = info["min_usd"]
    if next_usd:
        gap_total = next_usd - min_usd
        sisa_usd  = gap_total - (gap_total * progress)
        # Cari label next level via urutan eksplisit, bukan exact min_usd match
        cur_idx    = VIP_ORDER.index(flag) if flag in VIP_ORDER else 0
        next_key   = VIP_ORDER[cur_idx + 1] if cur_idx + 1 < len(VIP_ORDER) else None
        next_label = VIP_LEVELS[next_key]["label"] if next_key else "Level Max"
        sisa_str   = f"  Sisa ke {next_label}: ~${sisa_usd:,.0f} USD wager"
    else:
        sisa_str = "  Level tertinggi tercapai!"

    print(f"  {g(CYAN, '◆')} {g(BOLD, 'VIP STATUS')}")
    print(f"  {g(CYAN, '─' * 52)}")
    print(f"  {'Level':<14} {color}{g(BOLD, label)}{R}")
    print(f"  {'Progress':<14} [{bar}] {g(BOLD, f'{pct:.1f}%')}")
    print(f"  {g(DIM, sisa_str.strip())}")
    print(f"  {g(CYAN, '─' * 52)}")


def simpan_log_csv(sesi: dict):
    """
    Simpan ringkasan satu sesi ke file log_sesi.csv.
    Kolom: tanggal, ronde, volume_idr, loss_idr, win_rate_pct, net_idr, vip_flag, vip_progress_pct
    File dibuat otomatis jika belum ada, header ditulis sekali.
    """
    file_baru = not os.path.exists(CSV_LOG)
    with open(CSV_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "tanggal", "ronde", "volume_idr", "loss_idr",
            "win_rate_pct", "net_idr", "vip_flag", "vip_progress_pct",
        ])
        if file_baru:
            writer.writeheader()   # Tulis header hanya jika file baru
        writer.writerow(sesi)


def print_banner():
    now = datetime.now().strftime("%d %b %Y  %H:%M")
    print(g(CYAN, """
  ╔═════════════════════════════════════════════════════╗
  ║  ____  _        _          ____  _                  ║
  ║ / ___|| |_ __ _| | _____  |  _ \\(_) ___ ___       ║
  ║ \\___ \\| __/ _` | |/ / _ \\ | | | | |/ __/ _ \\     ║
  ║  ___) | || (_| |   <  __/ | |_| | | (_|  __/       ║
  ║ |____/ \\__\\__,_|_|\\_\\___| |____/|_|\\___\\___|      ║
  ╠═════════════════════════════════════════════════════╣
  ║       Stake.com Official API  ·  Auto Bet Bot       ║
  ╚═════════════════════════════════════════════════════╝"""))
    print(g(DIM, f"\n  ⏰  {now}\n"))


def print_section(title):
    print(f"\n  {g(CYAN, '◆')} {g(BOLD, title)}")
    print(f"  {g(CYAN, '─' * 52)}")


def print_summary(stats, currency):
    print_section("RINGKASAN SESI")
    total    = stats["total"]
    wins     = stats["wins"]
    losses   = stats["losses"]
    profit   = stats["profit"]
    win_rate = (Decimal(wins) / Decimal(total) * 100) if total > 0 else Decimal("0")

    profit_color = GREEN if profit >= 0 else RED
    sign         = "+" if profit >= 0 else ""

    max_ws = stats["max_win_streak"]
    max_ls = stats["max_loss_streak"]
    sep    = g(CYAN, "─" * 52)
    print(f"  {'Ronde dimainkan':<18} {g(BOLD, str(total))}")
    print(f"  {'Menang':<18} {g(GREEN, '✅  ' + str(wins))}")
    print(f"  {'Kalah':<18} {g(RED, '❌  ' + str(losses))}")
    print(f"  {'Win Rate':<18} {g(BOLD, str(win_rate.quantize(Decimal('0.1'))) + '%')}")
    print(f"  {'Max Win Streak':<18} {g(GREEN, '🔥 ' + str(max_ws))}")
    print(f"  {'Max Loss Streak':<18} {g(RED, '💧 ' + str(max_ls))}")
    print(f"  {sep}")
    print(f"  {'Total Profit':<18} {g(profit_color, BOLD + sign + fmt(profit, currency) + R)}")
    print(f"  {sep}")


# ─── Strategy VIP ─────────────────────────────────────────────────────────────

def rest_countdown(menit: int = 60):
    """
    Countdown istirahat antar sesi untuk VPS mode.
    Menampilkan progress bar + waktu sisa secara real-time.
    Ctrl+C kapan saja = skip istirahat dan langsung lanjut.
    """
    total_secs = menit * 60
    resume_at  = datetime.fromtimestamp(
        datetime.now().timestamp() + total_secs
    ).strftime("%H:%M")

    print()
    print(g(CYAN,  f"  ⏸  Istirahat {menit} menit — sesi berikutnya ± pukul {resume_at}"))
    print(g(DIM,   "     Ctrl+C untuk skip istirahat dan langsung lanjut.\n"))

    bar_len = 35
    try:
        for sisa in range(total_secs, 0, -1):
            elapsed  = total_secs - sisa
            filled   = int(elapsed / total_secs * bar_len)
            bar      = g(CYAN, "█" * filled) + g(DIM, "░" * (bar_len - filled))
            mnt, dtk = divmod(sisa, 60)
            print(
                f"\r  ⏰  [{bar}]  {g(BOLD, f'{mnt:02d}:{dtk:02d}')} tersisa   ",
                end="", flush=True
            )
            time.sleep(1)
        print(f"\r  {g(GREEN, '✅')}  Istirahat selesai! Memulai sesi berikutnya...{' ' * 20}")
    except KeyboardInterrupt:
        print(f"\n\n  {g(YELLOW, '⏩')}  Skip istirahat — langsung lanjut sesi baru.\n")


def jalankan_strategy_vip(user: dict, vps_mode: bool = False):
    """
    Auto-bet Strategy VIP: 98% Win Chance, flat bet IDR 600.

    Tujuan  : Mengumpulkan volume wager secepat mungkin untuk naik VIP
              dengan modal ketat Rp 100.000.

    Logika istirahat:
      - Setiap Rp 5.000.000 wager kumulatif → istirahat 15 menit, lanjut otomatis
      - Stop-loss Rp 45.000 → istirahat 5–10 menit, lanjut sesi baru

    Log terminal setiap spin: nomor bet, wager, saldo, loss, W/L, dan durasi bot berjalan.

    Returns True jika ingin lanjut sesi baru, False jika user Ctrl+C.
    """

    # ── Konfigurasi strategi ──────────────────────────────────────────────────
    currency            = "idr"
    base_bet            = Decimal("600")       # ← Ubah di sini jika ingin Rp 400 / 800 / 1000
    rest_setiap_volume  = Decimal("5000000")   # Istirahat 15 menit setiap Rp 5 juta wager
    rest_menit_volume   = 15                   # Durasi istirahat setelah checkpoint volume
    max_loss_limit      = Decimal("45000")     # Stop-loss: berhenti jika loss ≥ Rp 45 ribu
    topup_alert_idr     = Decimal("75000")     # ← Kirim alert Telegram jika saldo < X (Rp 75 ribu)
    win_chance_pct      = Decimal("98")
    condition           = "below"
    target_num          = 98.0
    multiplier          = (Decimal("99") / win_chance_pct).quantize(
                              Decimal("0.000001"), rounding=ROUND_DOWN)

    # ── Tampilkan VIP status otomatis di atas CLI ─────────────────────────────
    flag_progress = user.get("flagProgress") or {"flag": "none", "progress": 0}
    print_vip_status(flag_progress)

    # ── Info konfigurasi sesi ─────────────────────────────────────────────────
    print_section("STRATEGY VIP — 98% WIN CHANCE  (SPEED MODE)")
    print(f"  Currency      : {g(BOLD, 'IDR (Rupiah)')}")
    print(f"  Base Bet      : {g(BOLD, fmt(base_bet, currency))}  {g(DIM, '← ubah variabel base_bet')}")
    print(f"  Win Chance    : {g(BOLD, '98%')}  |  Multiplier: {g(BOLD, f'{multiplier}x')}")
    print(f"  Rest Checkpoint : setiap {g(CYAN, fmt(rest_setiap_volume, currency))} wager → {g(CYAN, str(rest_menit_volume) + ' menit')}")
    print(f"  Stop-Loss     : {g(RED, fmt(max_loss_limit, currency))} loss → istirahat 5–10 mnt lalu lanjut")
    print(f"  Delay         : {g(DIM, 'random 0.2–0.8 detik (speed mode)')}")
    print(f"  Log terminal  : {g(DIM, 'setiap spin (dengan durasi berjalan)')}")
    print(g(DIM, "\n  Tekan Ctrl+C untuk berhenti kapan saja.\n"))

    # ── State tracker ────────────────────────────────────────────────────────
    total_volume         = Decimal("0")
    total_loss           = Decimal("0")
    wins                 = 0
    losses               = 0
    consecutive_err      = 0
    ronde                = 0
    stopped_by_user      = False
    next_rest_checkpoint = rest_setiap_volume     # Checkpoint volume berikutnya
    next_million_notif   = Decimal("1000000")     # Notifikasi Telegram tiap Rp1 juta wager
    _topup_notified      = False                  # Agar alert top-up hanya kirim sekali per sesi
    sesi_mulai           = datetime.now()         # Timer durasi bot berjalan

    try:
        while True:

            # ── Kirim taruhan ke Stake via API ────────────────────────────────
            identifier = str(uuid.uuid4())
            try:
                api_result = gql(DICE_MUTATION, {
                    "amount":     float(base_bet),
                    "target":     target_num,
                    "condition":  condition,
                    "currency":   currency,
                    "identifier": identifier,
                })
                roll            = api_result["diceRoll"]
                consecutive_err = 0
            except PermissionError as e:
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

            # ── Parse state ───────────────────────────────────────────────────
            state      = roll.get("state") or {}
            payout     = to_dec(roll.get("payout", 0))
            amount     = to_dec(roll.get("amount", 0))
            profit     = (payout - amount).quantize(_quanta(currency), rounding=ROUND_DOWN)

            won_state  = determine_win(state)
            won_payout = payout > amount
            won        = won_payout if not state else won_state

            # ── Update statistik ──────────────────────────────────────────────
            total_volume += base_bet
            total_loss   -= profit   # negatif jika menang, positif jika kalah

            if won:
                wins += 1
            else:
                losses += 1

            # ── Ambil saldo terkini ───────────────────────────────────────────
            user_bals  = roll.get("user", {}).get("balances", [])
            bal_amount = next(
                (b["available"]["amount"] for b in user_bals
                 if b["available"]["currency"] == currency), None)

            # ── Top-Up Alert: saldo < threshold → notif Telegram sekali ──────
            if (
                bal_amount is not None
                and not _topup_notified
                and to_dec(bal_amount) < topup_alert_idr
            ):
                _topup_notified = True
                print(g(RED,
                    f"\n  ⚠️  Saldo hampir habis! "
                    f"Sisa: {fmt(bal_amount, currency)} "
                    f"(batas alert: {fmt(topup_alert_idr, currency)})\n"
                ))
                kirim_telegram(
                    f"⚠️ <b>SALDO HAMPIR HABIS!</b>\n"
                    f"Sisa saldo: {fmt(bal_amount, currency)}\n"
                    f"Bet #{ronde} | Wager sesi: {fmt(total_volume, currency)}\n"
                    f"Segera top up agar bot tidak berhenti."
                )

            # ── Log setiap spin — termasuk durasi bot berjalan ────────────────
            elapsed     = datetime.now() - sesi_mulai
            total_sec   = int(elapsed.total_seconds())
            jam, sisa   = divmod(total_sec, 3600)
            mnt, dtk    = divmod(sisa, 60)
            durasi_str  = f"{jam:02d}:{mnt:02d}:{dtk:02d}"
            win_rate    = Decimal(wins) / Decimal(ronde) * 100
            bal_str     = fmt(bal_amount, currency) if bal_amount is not None else "N/A"
            ikon        = g(GREEN, "✅") if won else g(RED, "❌")
            loss_color  = RED if total_loss > 0 else DIM
            print(
                f"  {ikon} #{ronde}  │  "
                f"Wager: {g(CYAN, fmt(total_volume, currency))}  │  "
                f"Saldo: {g(CYAN, bal_str)}  │  "
                f"Loss: {g(loss_color, fmt(total_loss, currency))}  │  "
                f"W/L: {g(GREEN, str(wins))}/{g(RED, str(losses))} "
                f"{g(DIM, f'({win_rate:.1f}%)')}  │  "
                f"⏱ {g(DIM, durasi_str)}"
            )

            # ── Notifikasi Telegram setiap Rp1 juta wager ────────────────────
            if total_volume >= next_million_notif:
                next_million_notif += Decimal("1000000")
                kirim_telegram(
                    f"📈 <b>Wager {fmt(total_volume, currency)}</b>\n"
                    f"Bet #{ronde} | W/L: {wins}/{losses} ({win_rate:.1f}%)\n"
                    f"Loss sesi: {fmt(total_loss, currency)}\n"
                    f"Saldo: {bal_str}\n"
                    f"⏱ Durasi: {durasi_str}"
                )

            # ── Cek stop-loss ─────────────────────────────────────────────────
            if total_loss >= max_loss_limit:
                jeda = random.randint(5, 10)
                print(g(RED,
                    f"\n  🛑 Stop-loss {fmt(max_loss_limit, currency)} tercapai di bet #{ronde}. "
                    f"Istirahat {jeda} menit untuk mengamankan modal..."
                ))
                kirim_telegram(
                    f"🛑 <b>STOP-LOSS</b>\n"
                    f"Bet #{ronde} | Loss: {fmt(total_loss, currency)}\n"
                    f"Wager sesi: {fmt(total_volume, currency)}\n"
                    f"Istirahat {jeda} menit lalu lanjut otomatis."
                )
                rest_countdown(jeda)
                break

            # ── Cek checkpoint volume → istirahat 15 menit lalu lanjut ───────
            if total_volume >= next_rest_checkpoint:
                next_rest_checkpoint += rest_setiap_volume
                win_rate_now = Decimal(wins) / Decimal(ronde) * 100 if ronde > 0 else Decimal("0")
                print(g(CYAN,
                    f"\n  ✅ Checkpoint {fmt(total_volume, currency)} wager tercapai! "
                    f"Istirahat {rest_menit_volume} menit..."
                ))
                kirim_telegram(
                    f"✅ <b>CHECKPOINT</b> {fmt(total_volume, currency)}\n"
                    f"Bet #{ronde} | W/L: {wins}/{losses} ({win_rate_now:.1f}%)\n"
                    f"Loss sesi: {fmt(total_loss, currency)}\n"
                    f"Istirahat {rest_menit_volume} menit lalu lanjut otomatis."
                )
                rest_countdown(rest_menit_volume)
                print(g(GREEN, "  ▶  Lanjut betting...\n"))
                continue   # ← lanjut, bukan break

            # ── Delay cepat (speed mode) ──────────────────────────────────────
            time.sleep(random.uniform(0.2, 0.8))

    except KeyboardInterrupt:
        print(g(YELLOW, "\n\n  ⏹  Dihentikan oleh pengguna."))
        stopped_by_user = True

    # ── Ringkasan akhir sesi VIP ──────────────────────────────────────────────
    total    = wins + losses
    win_rate = (Decimal(wins) / Decimal(total) * 100) if total > 0 else Decimal("0")
    net      = -total_loss  # positif = untung, negatif = rugi

    print_section("RINGKASAN STRATEGY VIP")
    net_color = GREEN if net >= 0 else RED
    net_sign  = "+" if net >= 0 else ""
    print(f"  {'Ronde dimainkan':<18} {g(BOLD, str(total))}")
    print(f"  {'Menang':<18} {g(GREEN, f'✅  {wins}')}")
    print(f"  {'Kalah':<18} {g(RED, f'❌  {losses}')}")
    print(f"  {'Win Rate':<18} {g(BOLD, f'{win_rate:.1f}%')}")
    print(f"  {'Total Volume':<18} {g(CYAN, fmt(total_volume, currency))}")
    print(f"  {g(CYAN, '─' * 52)}")
    print(f"  {'Net Profit/Loss':<18} {g(net_color, BOLD + net_sign + fmt(net, currency) + R)}")
    print(f"  {g(CYAN, '─' * 52)}")

    # ── Refresh VIP progress dari API setelah sesi selesai ───────────────────
    flag_before = flag_progress.get("flag", "none")
    prog_before = float(flag_progress.get("progress", 0))
    try:
        fresh_user   = gql(USER_QUERY)["user"]
        flag_after   = fresh_user.get("flagProgress") or {"flag": "none", "progress": 0}
        flag_now     = flag_after.get("flag", "none")
        prog_now     = float(flag_after.get("progress", 0))

        print()
        print(g(BOLD, "  📊 VIP Progress setelah sesi:"))
        print_vip_status(flag_after)

        # ── Alert naik level ──────────────────────────────────────────────────
        if flag_now != flag_before:
            print(g(GREEN, f"""
  ╔══════════════════════════════════════════╗
  ║  🎉  SELAMAT! LEVEL VIP NAIK!           ║
  ║  {flag_before.upper():<10} → {flag_now.upper():<10}              ║
  ╚══════════════════════════════════════════╝"""))
            kirim_telegram(
                f"🎉 <b>VIP NAIK!</b>\n"
                f"{flag_before.upper()} → {flag_now.upper()}\n"
                f"Wager sesi ini: {fmt(total_volume, currency)}"
            )
        else:
            gain = (prog_now - prog_before) * 100
            print(g(DIM, f"  Progress naik: +{gain:.2f}% dalam sesi ini"))
            kirim_telegram(
                f"📊 <b>Sesi Selesai</b>\n"
                f"Bet: {total} | W/L: {wins}/{losses} ({win_rate:.1f}%)\n"
                f"Wager: {fmt(total_volume, currency)}\n"
                f"Net: {('+' if net >= 0 else '') + fmt(net, currency)}\n"
                f"VIP Progress: +{gain:.2f}%"
            )

    except Exception:
        pass  # Jika gagal refresh, lanjut tanpa crash

    # ── Simpan log sesi ke CSV ────────────────────────────────────────────────
    if total > 0:
        simpan_log_csv({
            "tanggal":          datetime.now().strftime("%Y-%m-%d %H:%M"),
            "ronde":            total,
            "volume_idr":       str(total_volume),
            "loss_idr":         str(total_loss),
            "win_rate_pct":     f"{win_rate:.1f}",
            "net_idr":          str(net),
            "vip_flag":         flag_before,
            "vip_progress_pct": f"{prog_before * 100:.2f}",
        })
        print(g(DIM, f"\n  📄 Log sesi disimpan ke {CSV_LOG}"))

    # ── VPS mode: auto-continue, istirahat dikelola oleh caller ─────────────
    if vps_mode:
        return not stopped_by_user  # False jika user Ctrl+C = berhenti total

    # ── Tanya apakah mau mulai sesi baru (mode normal) ───────────────────────
    print()
    try:
        jawab = input(g(YELLOW, "  🔁 Mulai sesi baru? (y/n): ")).strip().lower()
        return jawab in ("y", "ya", "yes", "1")
    except (EOFError, KeyboardInterrupt):
        return False


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

    # ── Statistik kumulatif dari CSV ──────────────────────────────────────────
    if os.path.exists(CSV_LOG):
        try:
            with open(CSV_LOG, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            if rows:
                total_sesi    = len(rows)
                total_vol     = sum(Decimal(r["volume_idr"])  for r in rows)
                total_net     = sum(Decimal(r["net_idr"])     for r in rows)
                total_ronde   = sum(int(r["ronde"])           for r in rows)
                last          = rows[-1]
                print_section("STATISTIK KUMULATIF SEMUA SESI")
                print(f"  Total sesi      : {g(BOLD, str(total_sesi))}")
                print(f"  Total ronde     : {g(BOLD, str(total_ronde))}")
                print(f"  Total volume    : {g(CYAN, fmt(total_vol, 'idr'))}")
                net_c = GREEN if total_net >= 0 else RED
                net_s = "+" if total_net >= 0 else ""
                print(f"  Total net P/L   : {g(net_c, net_s + fmt(total_net, 'idr'))}")
                print(f"  Sesi terakhir   : {g(DIM, last['tanggal'])} "
                      f"— VIP {last['vip_flag'].upper()} {last['vip_progress_pct']}%")
        except Exception:
            pass  # Jika CSV rusak, lanjut tanpa crash

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

    # ── Pilih mode ────────────────────────────────────────────────────────────
    print_section("PILIH MODE")
    print(f"  {g(BOLD, '1.')} Dice Biasa       — atur sendiri currency, bet, target, dll")
    print(f"  {g(BOLD, '2.')} Strategy VIP IDR — auto-bet 98% win, Rp 600/roll, stop-loss Rp 45rb")
    print(f"  {g(BOLD, '3.')} {g(CYAN, 'VPS Auto-Run')}    — seperti mode 2, tapi jalan terus 24/7 tanpa input")
    print(g(DIM, "             Mode 3 cocok untuk VPS/server — setiap sesi selesai"))
    print(g(DIM, "             otomatis istirahat lalu mulai sesi baru tanpa perlu diawasi."))

    def val_mode_main(s):
        return s if s in ("1", "2", "3") else None

    mode_main = ask("\nPilih mode (1/2/3): ", validator=val_mode_main)

    # ── Strategy VIP: loop manual (tanya y/n tiap sesi) ──────────────────────
    if mode_main == "2":
        sesi_ke = 1
        while True:
            print(g(CYAN, f"\n  ═══ SESI #{sesi_ke} ═══"))

            try:
                user = gql(USER_QUERY)["user"]
            except Exception as e:
                print(g(YELLOW, f"  ⚠️  Gagal refresh data user: {e} — lanjut dengan data sesi sebelumnya."))

            lanjut = jalankan_strategy_vip(user=user)
            if not lanjut:
                print(g(YELLOW, "\n  Sampai jumpa! 👋"))
                break
            sesi_ke += 1
        return

    # ── VPS Auto-Run: jalan 24/7, istirahat otomatis antar sesi ──────────────
    if mode_main == "3":
        print_section("VPS AUTO-RUN — KONFIGURASI")
        print(g(DIM, "  Setiap sesi selesai (stop-loss atau checkpoint 5 juta), script akan"))
        print(g(DIM, "  istirahat otomatis lalu mulai sesi baru. Ctrl+C saat istirahat = skip.\n"))
        print(g(DIM, "  Ctrl+C saat sedang betting = sesi berhenti & keluar program.\n"))

        rest_menit = 60

        print()
        print(g(GREEN, f"  ✅ VPS Auto-Run aktif — istirahat {rest_menit} menit antar sesi"))
        print(g(DIM,   "  Script berjalan sampai Ctrl+C saat betting atau terjadi auth error.\n"))

        sesi_ke = 1
        while True:
            waktu_mulai = datetime.now().strftime("%d/%m %H:%M")
            print(g(CYAN, f"\n  ╔═══ SESI #{sesi_ke}  ·  {waktu_mulai} ═══╗"))

            try:
                user = gql(USER_QUERY)["user"]
            except Exception as e:
                print(g(YELLOW, f"  ⚠️  Gagal refresh data user: {e} — lanjut dengan data sesi sebelumnya."))

            lanjut = jalankan_strategy_vip(user=user, vps_mode=True)
            if not lanjut:
                print(g(YELLOW, "\n  VPS Auto-Run dihentikan oleh pengguna. Sampai jumpa! 👋"))
                break

            sesi_ke += 1
            rest_countdown(rest_menit)

        return

    # ── Mode Dice Biasa (lanjut konfigurasi manual) ───────────────────────────

    # Pilih currency
    print_section("KONFIGURASI BET")
    print(g(WHITE, "  Pilih currency:"))
    for k, v in CURRENCY_LIST.items():
        print(f"    {k:>2}. {v.upper()}")

    def val_currency(s):
        return CURRENCY_LIST.get(s)

    currency = ask("\nPilihan currency (1-10): ", validator=val_currency)
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

            # ── Parse state dengan aman — lindungi dari KeyError/TypeError ────
            state      = roll.get("state") or {}
            payout     = to_dec(roll.get("payout", 0))
            amount_dec = to_dec(roll.get("amount", 0))
            profit     = (payout - amount_dec).quantize(_quanta(currency), rounding=ROUND_DOWN)

            # Tentukan menang dari state; fallback ke payout jika state tidak lengkap
            won_state  = determine_win(state)
            won_payout = payout > amount_dec
            if state and won_state != won_payout:
                print(g(YELLOW, f"  ⚠️  State/payout mismatch ronde {ronde}, pakai payout."))
            won = won_payout if not state else won_state

            stats["profit"] += profit

            rolled_num  = float(state.get("result", 0))
            # Ambil saldo currency aktif dari user.balances
            user_bals   = roll.get("user", {}).get("balances", [])
            bal_amount  = next(
                (b["available"]["amount"] for b in user_bals
                 if b["available"]["currency"] == currency), None)
            balance_str = fmt(bal_amount, currency) if bal_amount is not None else "N/A"

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
                f"  {g(DIM, f'#{ronde:>04}')}  "
                f"🎲 {g(BOLD, f'{rolled_num:>6.2f}')}  "
                f"{result_icon}  {profit_str}  "
                f"{g(DIM, '│')}  Saldo: {g(CYAN, balance_str)}"
            )
            print(
                f"         "
                f"▸ W/L {g(GREEN, str(stats['wins']))}{g(DIM, '/')}{g(RED, str(stats['losses']))} "
                f"{g(DIM, f'({win_rate:.1f}%)')}  "
                f"{g(DIM, '·')}  Total: {g(total_profit_color, total_sign + fmt(stats['profit'], currency))}"
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
