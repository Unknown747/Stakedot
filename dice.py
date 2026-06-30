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

API_KEY = os.environ.get("STAKE_API_KEY", "")

API_URL = "https://stake.com/_api/graphql"
HEADERS = {
    "Content-Type": "application/json",
    "x-access-token": API_KEY,
    "Connection": "keep-alive",
}

# Session tunggal yang reuse koneksi TCP/TLS — menghilangkan overhead
# handshake per bet (hemat ~1-3 dtk/bet dibanding requests.post() biasa)
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

MAX_CONSECUTIVE_ERRORS = 5  # Berhenti jika gagal N kali berturut-turut

# ─── Warna Terminal ────────────────────────────────────────────────────────────

R      = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BLUE   = "\033[94m"
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
        resp = SESSION.post(API_URL, json=payload, timeout=30)
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


def idr_k(val):
    """Format IDR compact: 177187.74 → '177.188' (integer, titik ribuan, tanpa desimal)."""
    try:
        return f"{int(round(float(to_dec(val)))):,}".replace(",", ".")
    except Exception:
        return "N/A"


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


# ─── UI ────────────────────────────────────────────────────────────────────────

CSV_LOG          = "log_sesi.csv"   # File log aktif
CSV_LOG_MAX_ROWS = 500              # Baris maks sebelum rotasi
CSV_LOG_MAX_ARSIP = 10             # Jumlah arsip lama yang disimpan
CSV_LOG_ARSIP_DIR = "log_arsip"    # Folder tempat arsip disimpan

CSV_FIELDNAMES = [
    "tanggal", "ronde", "volume_idr", "loss_idr",
    "win_rate_pct", "net_idr", "vip_flag", "vip_progress_pct",
]


def rotasi_log_csv():
    """
    Periksa jumlah baris log_sesi.csv.
    Jika sudah mencapai CSV_LOG_MAX_ROWS:
      1. Pindahkan file aktif ke folder log_arsip/ dengan nama bertimestamp.
      2. Hapus arsip terlama jika jumlah arsip melebihi CSV_LOG_MAX_ARSIP.
    Dipanggil otomatis sebelum setiap penulisan sesi baru.
    """
    if not os.path.exists(CSV_LOG):
        return

    try:
        with open(CSV_LOG, newline="", encoding="utf-8") as f:
            baris = sum(1 for _ in f) - 1   # kurangi 1 untuk header
    except Exception:
        return

    if baris < CSV_LOG_MAX_ROWS:
        return

    os.makedirs(CSV_LOG_ARSIP_DIR, exist_ok=True)
    stempel = datetime.now().strftime("%Y%m%d_%H%M%S")
    nama_arsip = os.path.join(CSV_LOG_ARSIP_DIR, f"log_sesi_{stempel}.csv")

    try:
        os.rename(CSV_LOG, nama_arsip)
        print(g(CYAN,
            f"\n  🗂  Log dirotasi → {nama_arsip} ({baris} baris)"
        ))
    except Exception as e:
        print(g(YELLOW, f"  ⚠️  Gagal rotasi log: {e}"))
        return

    try:
        arsip_list = sorted([
            os.path.join(CSV_LOG_ARSIP_DIR, f)
            for f in os.listdir(CSV_LOG_ARSIP_DIR)
            if f.startswith("log_sesi_") and f.endswith(".csv")
        ])
        while len(arsip_list) > CSV_LOG_MAX_ARSIP:
            hapus = arsip_list.pop(0)
            os.remove(hapus)
            print(g(DIM, f"  🗑  Arsip lama dihapus: {hapus}"))
    except Exception:
        pass


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
    Rotasi otomatis jika baris sudah mencapai CSV_LOG_MAX_ROWS.
    File dibuat otomatis jika belum ada, header ditulis sekali.
    """
    rotasi_log_csv()   # Cek & rotasi dulu sebelum tulis
    file_baru = not os.path.exists(CSV_LOG)
    with open(CSV_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        if file_baru:
            writer.writeheader()
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
    base_bet            = Decimal("200")       # ← Ubah di sini jika ingin Rp 200 / 400 / 600 / 800 / 1000
    rest_setiap_volume  = Decimal("5000000")   # Istirahat 15 menit setiap Rp 5 juta wager
    rest_menit_volume   = 15                   # Durasi istirahat setelah checkpoint volume
    max_loss_limit      = Decimal("45000")     # Stop-loss: berhenti jika loss ≥ Rp 45 ribu
    topup_alert_idr     = Decimal("75000")     # ← Warning terminal jika saldo < X (Rp 75 ribu)
    win_chance_pct      = Decimal("98")
    condition           = "below"
    target_num          = 98.0
    multiplier          = (Decimal("99") / win_chance_pct).quantize(
                              Decimal("0.000001"), rounding=ROUND_DOWN)

    # ── Konfigurasi Recovery (Martingale Kilat — 1 Level Only) ──────────────────
    # Desain: Kalah → tembak 1× bet besar untuk menutup loss → apapun hasilnya,
    #         langsung kembali ke base_bet. TIDAK ada eskalasi berlanjut.
    # Ref catatan: "Taruhan besar HANYA boleh bernyawa selama 1 klik."
    recovery_enabled       = False             # ← False = flat bet tanpa recovery
    recovery_factor        = Decimal("50")     # ← Recovery bet = base_bet × 50 (5.000% dari base)
    recovery_max_bet       = Decimal("20000")  # ← Safety cap — bet recovery tidak boleh melebihi ini
    recovery_delay_min_sec = 3                 # ← Jeda minimum sebelum tembak recovery (detik)
    recovery_delay_max_sec = 5                 # ← Jeda maksimum sebelum tembak recovery (detik)

    # ── Konfigurasi Anti-Spiral Protection ───────────────────────────────────
    rcv_skip_after       = 2            # Jumlah spin hukuman setelah rcv gagal
    rcv_fail_streak_max  = 2            # Streak Guard aktif setelah N bet Rp10k gagal berturut-turut
    rcv_fail_pause_sec   = 15           # Pause setelah 1× recovery gagal (detik)
    rcv_streak_pause_min = 1            # Cooldown menit setelah streak Rp10k gagal
    rcv_mega_limit       = 5            # Mega cooldown setiap N bet Rp10k gagal (counter reset setelah cooldown)
    rcv_mega_pause_min   = 5            # Durasi mega cooldown (menit)

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
    if recovery_enabled:
        _rbbet = min(base_bet * recovery_factor, recovery_max_bet).quantize(
                     _quanta(currency), rounding=ROUND_DOWN)
        print(f"  Recovery      : {g(GREEN, 'AKTIF')}  "
              f"{g(DIM, f'1 level only · bet recovery: {fmt(_rbbet, currency)}')}  "
              f"{g(DIM, f'· delay {recovery_delay_min_sec}–{recovery_delay_max_sec}d')}")
        print(f"  Anti-Spiral   : {g(GREEN, 'AKTIF')}  "
              f"{g(DIM, f'rcv gagal → pause {rcv_fail_pause_sec}d + skip {rcv_skip_after} spin')}")
        print(f"  Streak Guard  : {g(GREEN, 'AKTIF')}  "
              f"{g(DIM, f'{rcv_fail_streak_max}× beruntun gagal → cooldown {rcv_streak_pause_min} mnt')}")
        print(f"  Mega Cooldown : {g(GREEN, 'AKTIF')}  "
              f"{g(DIM, f'rcv gagal {rcv_mega_limit}× total → istirahat {rcv_mega_pause_min} mnt')}")
    else:
        print(f"  Recovery      : {g(DIM, 'nonaktif (flat bet)')}")
    print(f"  Delay         : {g(DIM, 'tanpa delay — API Stake sebagai natural throttle')}")
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
    next_million_notif   = Decimal("1000000")     # Milestone print di terminal tiap Rp1 juta wager
    _topup_notified      = False                  # Agar alert top-up hanya kirim sekali per sesi
    sesi_mulai           = datetime.now()         # Timer durasi bot berjalan
    take_profit_idr      = Decimal("5000")        # Jeda 5 dtk setiap kelipatan profit ini
    next_take_profit     = take_profit_idr        # Threshold profit berikutnya

    # ── Recovery state ────────────────────────────────────────────────────────
    current_bet       = base_bet        # Bet aktif saat ini
    in_recovery       = False           # True = giliran bet recovery sekarang (maks 1 klik)
    rcv_triggered     = 0               # Berapa kali recovery terpicu
    rcv_wins          = 0               # Recovery berhasil (menang)
    rcv_losses        = 0               # Recovery gagal (kalah lagi)
    rcv_total_saved   = Decimal("0")    # Total loss yang berhasil diselamatkan recovery

    # ── Anti-Spiral state counters (config ada di blok konfigurasi di atas) ──
    rcv_skip_spins       = 0            # Sisa spin hukuman — turun 1 tiap spin (WIN maupun LOSE)
    rcv_fail_streak      = 0            # Counter bet Rp10k gagal berturut-turut (tanpa rcv menang di antara)
    rcv_mega_counter     = 0            # Counter khusus Lapis 3 — reset ke 0 setelah mega cooldown selesai

    # ── Profit Lock & Balance Tracking ───────────────────────────────────────
    saldo_awal           = None              # Saldo sesi (dicatat dari bal pertama)
    profit_lock_idr      = Decimal("20000")  # Stop-loss naik setiap saldo bertambah Rp 20.000
    profit_lock_level    = 0                 # Sudah berapa kali profit lock naik
    prev_bal             = None              # Saldo bet sebelumnya (validasi post-recovery)

    try:
        while True:

            # ── Kirim taruhan ke Stake via API ────────────────────────────────
            identifier = str(uuid.uuid4())
            try:
                api_result = gql(DICE_MUTATION, {
                    "amount":     float(current_bet),
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

            won_state      = determine_win(state)
            won_payout     = payout > amount
            won            = won_payout if not state else won_state
            was_recovery   = in_recovery  # Capture sebelum state machine mengubahnya

            # ── Update statistik ──────────────────────────────────────────────
            total_volume += current_bet
            total_loss   -= profit   # negatif jika menang, positif jika kalah

            if won:
                wins += 1
            else:
                losses += 1

            # ── Recovery State Machine ────────────────────────────────────────
            # Desain: 1 level only — bet besar diizinkan HANYA 1 klik.
            # Apapun hasilnya (menang/kalah), langsung kembali ke base_bet.
            if in_recovery:
                # Giliran ini ADALAH bet recovery — resolusi wajib
                in_recovery = False
                current_bet = base_bet
                if won:
                    rcv_wins        += 1
                    rcv_total_saved += profit   # profit positif = loss tertutupi
                    rcv_fail_streak  = 0        # Reset streak karena recovery berhasil
                    print(g(GREEN, f"  ✅ RECOVERY BERHASIL — kembali ke Base Bet {fmt(base_bet, currency)}"))
                else:
                    rcv_losses      += 1
                    rcv_fail_streak += 1
                    rcv_mega_counter += 1
                    rcv_skip_spins   = rcv_skip_after  # Kunci recovery N spin ke depan
                    print(g(RED,
                        f"  ⚠️  Recovery kalah — loss diterima. "
                        f"Reset ke Base Bet {fmt(base_bet, currency)}  "
                        f"(kunci recovery {rcv_skip_after} spin berikutnya)"
                    ))
                    # Lapis 1 — Pause wajib setelah recovery gagal
                    print(g(YELLOW, f"  ⏸  Anti-Spiral: jeda {rcv_fail_pause_sec}d..."))
                    time.sleep(rcv_fail_pause_sec)

                    # Lapis 2 — Streak Guard: N× bet Rp10k gagal berturut-turut tanpa rcv menang
                    if rcv_fail_streak >= rcv_fail_streak_max:
                        print(g(RED,
                            f"\n  🌡️  STREAK GUARD: {rcv_fail_streak}× bet Rp10k gagal beruntun — "
                            f"cooldown {rcv_streak_pause_min} menit...\n"
                        ))
                        rest_countdown(rcv_streak_pause_min)
                        rcv_fail_streak = 0   # Reset streak, bukan rcv_mega_counter

                    # Lapis 3 — Mega Cooldown: setiap rcv_mega_limit kali gagal (counter reset setelah istirahat)
                    if rcv_mega_counter >= rcv_mega_limit:
                        print(g(RED,
                            f"\n  🛑  MEGA COOLDOWN: {rcv_mega_counter}× recovery gagal — "
                            f"istirahat {rcv_mega_pause_min} menit...\n"
                        ))
                        rest_countdown(rcv_mega_pause_min)
                        rcv_mega_counter = 0  # Reset setelah cooldown selesai
            else:
                # Giliran ini adalah bet normal
                if rcv_skip_spins > 0:
                    # ── Spin hukuman aktif: turun 1 tiap spin (WIN maupun LOSE) ──
                    # Recovery DIKUNCI. Kalau kalah, cukup terima -Rp200, tidak tembak Rp10k.
                    rcv_skip_spins -= 1
                    if not won:
                        print(g(DIM,
                            f"  ⏭  Spin hukuman: recovery dikunci "
                            f"({rcv_skip_spins} spin sisa) — loss Rp200 diterima"
                        ))
                elif not won and recovery_enabled:
                    # ── Normal: kalah → tembak recovery ──────────────────────────
                    raw_rb      = base_bet * recovery_factor
                    current_bet = min(raw_rb, recovery_max_bet).quantize(
                                      _quanta(currency), rounding=ROUND_DOWN)
                    in_recovery   = True
                    rcv_triggered += 1
                    delay_sek     = random.uniform(recovery_delay_min_sec, recovery_delay_max_sec)
                    print(g(YELLOW,
                        f"\n  ⚡ KALAH — jeda {delay_sek:.1f}d lalu tembak "
                        f"Recovery Bet {fmt(current_bet, currency)}...\n"
                    ))
                    time.sleep(delay_sek)

            # ── Ambil saldo terkini ───────────────────────────────────────────
            user_bals  = roll.get("user", {}).get("balances", [])
            bal_amount = next(
                (b["available"]["amount"] for b in user_bals
                 if b["available"]["currency"] == currency), None)

            bal_dec = to_dec(bal_amount) if bal_amount is not None else None

            # ── Catat saldo awal sesi (sekali saja dari bet pertama) ──────────
            if saldo_awal is None and bal_dec is not None:
                saldo_awal = bal_dec

            # ── Poin 4: Re-check Balance setelah Recovery (Anti-Lag) ─────────
            # Setelah recovery bet selesai, pause 2 dtk + validasi saldo sinkron.
            if was_recovery and bal_dec is not None:
                if prev_bal is not None and bal_dec == prev_bal:
                    print(g(YELLOW,
                        "  ⚠️  Saldo tidak berubah post-recovery — "
                        "kemungkinan lag server. Pause 2 detik..."
                    ))
                else:
                    print(g(DIM, "  ⏳ Stabilisasi data post-recovery (2 detik)..."))
                time.sleep(2)

            # ── Poin 5: Profit Lock — naikkan stop-loss saat surplus +Rp20.000 ─
            if saldo_awal is not None and bal_dec is not None:
                surplus = bal_dec - saldo_awal
                target_lock = profit_lock_idr * (profit_lock_level + 1)
                if surplus >= target_lock:
                    profit_lock_level += 1
                    # Naikkan stop-loss mengikuti saldo baru
                    max_loss_limit = total_loss + profit_lock_idr
                    print(g(GREEN,
                        f"\n  🔒 PROFIT LOCK #{profit_lock_level}: "
                        f"Surplus +{idr_k(surplus)} IDR — "
                        f"Stop-loss dinaikkan ke {fmt(max_loss_limit, currency)}\n"
                    ))

            # Simpan saldo ini untuk validasi recovery berikutnya
            if bal_dec is not None:
                prev_bal = bal_dec

            # ── Top-Up Alert: saldo < threshold → cetak sekali di terminal ─────
            if (
                bal_amount is not None
                and not _topup_notified
                and to_dec(bal_amount) < topup_alert_idr
            ):
                _topup_notified = True
                print(g(RED,
                    f"\n  ⚠️  SALDO HAMPIR HABIS! "
                    f"Sisa: {fmt(bal_amount, currency)} "
                    f"(batas: {fmt(topup_alert_idr, currency)}) — segera top up!\n"
                ))

            # ── Log setiap spin — durasi, kecepatan, ETA ─────────────────────
            elapsed      = datetime.now() - sesi_mulai
            elapsed_sek  = elapsed.total_seconds()
            total_sec    = int(elapsed_sek)
            jam, sisa    = divmod(total_sec, 3600)
            mnt, dtk     = divmod(sisa, 60)
            durasi_str   = f"{jam:02d}:{mnt:02d}:{dtk:02d}"
            win_rate     = Decimal(wins) / Decimal(ronde) * 100
            ikon         = g(GREEN, "✅") if won else g(RED, "❌")
            loss_color   = RED if total_loss > 0 else DIM

            # Hitung kecepatan (bet/menit) dan ETA ke Rp1 Juta wager
            elapsed_mnt  = elapsed_sek / 60
            bet_per_mnt  = ronde / elapsed_mnt if elapsed_mnt >= 0.05 else 0
            TARGET_WAGER = Decimal("1000000")
            sisa_wager   = TARGET_WAGER - total_volume
            if bet_per_mnt > 0 and sisa_wager > 0:
                sisa_bet_eta = float(sisa_wager) / float(base_bet)
                eta_sek      = (sisa_bet_eta / bet_per_mnt) * 60
                if eta_sek >= 3600:
                    eta_str = f"{eta_sek/3600:.1f}j"
                elif eta_sek >= 60:
                    eta_str = f"{eta_sek/60:.0f}m"
                else:
                    eta_str = f"{eta_sek:.0f}d"
                speed_str = f"{g(YELLOW, f'{bet_per_mnt:.1f}')} b/m  │  ETA 1Jt: {g(CYAN, eta_str)}"
            elif sisa_wager <= 0:
                speed_str = f"{g(YELLOW, f'{bet_per_mnt:.1f}')} b/m  │  {g(GREEN, '✅ 1Jt!')}"
            else:
                speed_str = f"-- b/m"

            bal_k  = idr_k(bal_amount) if bal_amount is not None else "N/A"
            loss_k = idr_k(total_loss)

            # Tandai apakah spin ini adalah bet recovery (pakai was_recovery — dicapture sebelum state machine)
            bet_label = (g(YELLOW, f"RCV {idr_k(amount)}") if was_recovery
                         else g(DIM, f"Bet {idr_k(amount)}"))

            print(
                f"  {ikon} #{ronde} · {bet_label} · "
                f"Wgr {g(CYAN, idr_k(total_volume))} · "
                f"Sld {g(CYAN, bal_k)} · "
                f"Loss {g(loss_color, loss_k)} · "
                f"W/L {g(GREEN, str(wins))}/{g(RED, str(losses))} "
                f"{g(DIM, f'({win_rate:.1f}%)')}"
            )
            print(f"          {speed_str} · ⏱ {g(DIM, durasi_str)}")

            # ── Milestone setiap Rp1 juta wager ──────────────────────────────
            if total_volume >= next_million_notif:
                next_million_notif += Decimal("1000000")
                print(g(CYAN,
                    f"\n  📈 Milestone {fmt(total_volume, currency)} wager tercapai! "
                    f"({bet_per_mnt:.1f} b/m)\n"
                ))

            # ── Cek take-profit: jeda 5 dtk setiap kelipatan Rp 5.000 profit ──
            net_sesi = -total_loss
            if net_sesi >= next_take_profit:
                next_take_profit += take_profit_idr
                print(g(GREEN,
                    f"\n  💰 Profit +{idr_k(net_sesi)} IDR — jeda 5 detik...\n"
                ))
                time.sleep(5)

            # ── Cek stop-loss ─────────────────────────────────────────────────
            if total_loss >= max_loss_limit:
                jeda = random.randint(5, 10)
                print(g(RED,
                    f"\n  🛑 Stop-loss {fmt(max_loss_limit, currency)} tercapai di bet #{ronde}. "
                    f"Istirahat {jeda} menit untuk mengamankan modal..."
                ))
                rest_countdown(jeda)
                break

            # ── Cek checkpoint volume → istirahat 15 menit lalu lanjut ───────
            if total_volume >= next_rest_checkpoint:
                next_rest_checkpoint += rest_setiap_volume
                print(g(CYAN,
                    f"\n  ✅ Checkpoint {fmt(total_volume, currency)} wager! "
                    f"W/L: {wins}/{losses} ({win_rate:.1f}%) | {bet_per_mnt:.1f} b/m"
                    f"\n  Istirahat {rest_menit_volume} menit..."
                ))
                rest_countdown(rest_menit_volume)
                print(g(GREEN, "  ▶  Lanjut betting...\n"))
                continue   # ← lanjut dalam sesi yang sama, bukan break

            # ── Auto-throttle: sisipkan sleep jika bot terlalu cepat ────────────
            # Threshold: 30 b/m → sleep 1 dtk | >50 b/m → sleep 2 dtk
            # Melindungi dari rate-limit Stake jika API tiba-tiba sangat responsif.
            if bet_per_mnt > 50:
                time.sleep(2)
            elif bet_per_mnt > 30:
                time.sleep(1)

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

    # ── Statistik Recovery ────────────────────────────────────────────────────
    if recovery_enabled and rcv_triggered > 0:
        rcv_rate     = (rcv_wins / rcv_triggered * 100) if rcv_triggered > 0 else 0
        saved_color  = GREEN if rcv_total_saved > 0 else DIM
        saved_sign   = "+" if rcv_total_saved >= 0 else ""
        print(f"\n  {g(CYAN, '◆')} {g(BOLD, 'STATISTIK RECOVERY')}")
        print(f"  {g(CYAN, '─' * 52)}")
        print(f"  {'Terpicu':<18} {g(BOLD, str(rcv_triggered))} kali")
        print(f"  {'Berhasil':<18} {g(GREEN, f'✅  {rcv_wins}')}  {g(DIM, f'({rcv_rate:.0f}%)')}")
        print(f"  {'Gagal':<18} {g(RED,   f'⚠️   {rcv_losses}')}")
        print(f"  {'Loss Diselamatkan':<18} {g(saved_color, saved_sign + fmt(rcv_total_saved, currency))}")
        if rcv_losses > 0:
            streak_guard_ct = rcv_losses // rcv_fail_streak_max
            mega_ct         = rcv_losses // rcv_mega_limit
            print(f"  {'Streak Guard':<18} {g(YELLOW, str(streak_guard_ct))} kali terpicu")
            print(f"  {'Mega Cooldown':<18} {g(YELLOW, str(mega_ct))} kali terpicu")
        print(f"  {g(CYAN, '─' * 52)}")
    elif recovery_enabled and rcv_triggered == 0:
        print(g(DIM, f"\n  🛡  Recovery: tidak ada loss dalam sesi ini — 0 kali terpicu"))

    # ── Refresh VIP progress dari API setelah sesi selesai ───────────────────
    flag_before = flag_progress.get("flag") or "none"
    prog_before = float(flag_progress.get("progress") or 0)   # guard: API bisa kirim null
    try:
        fresh_user   = gql(USER_QUERY)["user"]
        flag_after   = fresh_user.get("flagProgress") or {"flag": "none", "progress": 0}
        flag_now     = flag_after.get("flag") or "none"
        prog_now     = float(flag_after.get("progress") or 0)  # guard: API bisa kirim null

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
        else:
            gain = (prog_now - prog_before) * 100
            print(g(DIM, f"  Progress naik: +{gain:.2f}% dalam sesi ini"))

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

    # ── Statistik kumulatif dari CSV (aktif + semua arsip) ────────────────────
    try:
        semua_file = []
        if os.path.exists(CSV_LOG):
            semua_file.append(CSV_LOG)
        if os.path.isdir(CSV_LOG_ARSIP_DIR):
            semua_file += sorted([
                os.path.join(CSV_LOG_ARSIP_DIR, f)
                for f in os.listdir(CSV_LOG_ARSIP_DIR)
                if f.startswith("log_sesi_") and f.endswith(".csv")
            ])

        if semua_file:
            rows = []
            for path in semua_file:
                try:
                    with open(path, newline="", encoding="utf-8") as f:
                        rows.extend(list(csv.DictReader(f)))
                except Exception:
                    pass

            if rows:
                total_sesi  = len(rows)
                total_vol   = sum(Decimal(r["volume_idr"]) for r in rows)
                total_net   = sum(Decimal(r["net_idr"])    for r in rows)
                total_ronde = sum(int(r["ronde"])          for r in rows)
                last        = rows[-1]
                # Hitung arsip secara eksplisit — jangan kurangi 1 karena
                # log_sesi.csv mungkin tidak ada (habis dirotasi)
                n_arsip = len([f for f in semua_file if f != CSV_LOG])

                print_section("STATISTIK KUMULATIF SEMUA SESI")
                print(f"  Total sesi      : {g(BOLD, str(total_sesi))}"
                      + (g(DIM, f"  ({n_arsip} file arsip)") if n_arsip > 0 else ""))
                print(f"  Total ronde     : {g(BOLD, str(total_ronde))}")
                print(f"  Total volume    : {g(CYAN, fmt(total_vol, 'idr'))}")
                net_c = GREEN if total_net >= 0 else RED
                net_s = "+" if total_net >= 0 else ""
                print(f"  Total net P/L   : {g(net_c, net_s + fmt(total_net, 'idr'))}")
                print(f"  Sesi terakhir   : {g(DIM, last['tanggal'])} "
                      f"— VIP {last['vip_flag'].upper()} {last['vip_progress_pct']}%")
                if n_arsip > 0:
                    print(f"  Log arsip       : {g(DIM, CSV_LOG_ARSIP_DIR + '/')} "
                          f"{g(DIM, f'({n_arsip}/{CSV_LOG_MAX_ARSIP} file)')}")
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

    # ── VPS Auto-Run: jalan 24/7, otomatis tanpa input ───────────────────────
    print(g(GREEN, "  ✅ VPS Auto-Run aktif — sesi baru otomatis setelah setiap sesi selesai"))
    print(g(DIM,   "  Ctrl+C saat betting = keluar. Ctrl+C saat istirahat = skip jeda.\n"))

    rest_menit = 15
    sesi_ke    = 1
    while True:
        waktu_mulai = datetime.now().strftime("%d/%m %H:%M")
        print(g(CYAN, f"\n  ╔═══ SESI #{sesi_ke}  ·  {waktu_mulai} ═══╗"))

        try:
            user = gql(USER_QUERY)["user"]
        except Exception as e:
            print(g(YELLOW, f"  ⚠️  Gagal refresh data user: {e} — lanjut dengan data sesi sebelumnya."))

        lanjut = jalankan_strategy_vip(user=user, vps_mode=True)
        if not lanjut:
            print(g(YELLOW, "\n  VPS Auto-Run dihentikan. Sampai jumpa! 👋"))
            break

        sesi_ke += 1
        rest_countdown(rest_menit)



if __name__ == "__main__":
    RESTART_DELAY = 60  # detik tunggu sebelum restart setelah crash tak terduga
    while True:
        try:
            main()
            break  # main() selesai normal (user keluar) — tidak perlu restart
        except SystemExit:
            break  # sys.exit() dipanggil — keluar bersih
        except KeyboardInterrupt:
            print(g(YELLOW, "\n\n  ⏹  Dihentikan oleh pengguna."))
            break
        except PermissionError as e:
            # Auth error: API Key tidak valid — restart tidak akan membantu
            print(g(RED, f"\n  ❌ Auth error fatal: {e}"))
            print(g(RED, "  Script dihentikan — perbarui STAKE_API_KEY lalu jalankan ulang."))
            break
        except Exception as e:
            print(g(RED, f"\n  💥 Bot crash tak terduga: {e}"))
            print(g(YELLOW,
                f"  🔄 Auto-restart dalam {RESTART_DELAY} detik... "
                f"(Ctrl+C untuk batalkan)"
            ))
            try:
                time.sleep(RESTART_DELAY)
            except KeyboardInterrupt:
                print(g(YELLOW, "\n  ⏹  Restart dibatalkan."))
                break
            print(g(CYAN, "\n  ▶  Memulai ulang bot...\n"))
            # lanjut iterasi while → main() dipanggil lagi
