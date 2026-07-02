#!/usr/bin/env python3
"""
Stake.com Limbo CLI
Mainkan Limbo Stake.com langsung dari terminal menggunakan API resmi.
"""

import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv tidak wajib — gunakan export STAKE_API_KEY=... di terminal
import sys
import json
import uuid
import time
import random
import csv
import requests
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from math import comb
from datetime import datetime
from typing import Optional

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

# ─── Konfigurasi strategi (dimuat dari config.json) ────────────────────────────
# Semua nilai yang sering diubah (bet, stop-loss, dll) ada di config.json,
# TIDAK lagi hardcode di dalam kode. Edit config.json untuk mengubah setting.

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

_DEFAULT_CONFIG = {
    "currency":                        "idr",
    "base_bet":                        "500",
    "win_chance_pct":                  "98",
    "rest_setiap_volume":              "2500000",
    "rest_menit_volume":               15,
    "max_loss_limit":                  "22500",
    "topup_alert_idr":                 "37500",
    "profit_lock_idr":                 "10000",
    "take_profit_idr":                 "2500",
    "session_take_profit_idr":         "10000",
    "on_loss_multiply_enabled":        True,
    "on_loss_multiply_pct":            "2",
    "on_loss_multiply_cap_multiplier": "5",
    "rest_menit_antar_sesi":           15,
    "max_consecutive_errors":          5,
    "restart_delay_detik":             60,
    "max_restart_attempts":            10,

    # ── Strategi Mines (opsional, dipilih lewat menu saat start) ────────────
    # Dua profil: Normal (aman, ranjau sedikit) & Agresif (ranjau lebih banyak,
    # multiplier lebih besar, tapi lebih sering kalah). Dipilih lewat submenu.
    "mines_profiles": {
        "normal": {
            "mines_count":                  1,
            "tile_indices":                 [0, 24],
            "loss_multiplier":              "1.5",
            "cap_multiplier":               "5",
            "double_loss_rest_menit":       1,
            "throttle":                     True,
            "instant_reset":                False,
        },
        "agresif": {
            "mines_count":                  3,
            "tile_indices":                 [0, 24],
            "loss_multiplier":              "1.3",
            "cap_multiplier":               "6",
            "double_loss_rest_menit":       2,
            "throttle":                     True,
            "instant_reset":                False,
        },
        "wager": {
            "mines_count":                  1,
            "tile_indices":                 [0],
            "loss_multiplier":              "1.02",
            "cap_multiplier":               "3",
            "double_loss_rest_menit":       0,
            "throttle":                     False,
            "instant_reset":                True,
        },
        "aman": {
            "mines_count":                  1,
            "tile_indices":                 [0],
            "loss_multiplier":              "1.1",
            "cap_multiplier":               "2",
            "double_loss_rest_detik":       30,
            "throttle":                     True,
            "instant_reset":                False,
            "max_loss_override":            "15000",
            "dynamic_bet_pct":              "0.25",
            "dynamic_bet_min_idr":          "200",
            "dynamic_bet_max_idr":          "2000",
        },
    },
}


def load_config():
    """Muat config.json; fallback ke default kalau file tidak ada/rusak.
    Key yang hilang di config.json tetap diisi dari default (merge)."""
    if not os.path.exists(CONFIG_PATH):
        print(f"⚠️  config.json tidak ditemukan di {CONFIG_PATH} — pakai nilai default.")
        return dict(_DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("config.json harus berisi objek JSON (key-value)")
        merged = {**_DEFAULT_CONFIG, **data}
        # Merge nested mines_profiles per-profil — supaya kalau config.json cuma
        # menimpa/mendefinisikan sebagian profil, profil lain tetap ada (tidak
        # hilang seluruhnya seperti merge dangkal biasa) dan tidak crash saat
        # dilookup di main() / jalankan_strategy_mines_vip().
        default_profiles = _DEFAULT_CONFIG.get("mines_profiles", {})
        user_profiles     = data.get("mines_profiles", {})
        if isinstance(user_profiles, dict):
            merged_profiles = {k: dict(v) for k, v in default_profiles.items()}
            for nama, isi in user_profiles.items():
                if isinstance(isi, dict) and nama in merged_profiles:
                    merged_profiles[nama].update(isi)
                else:
                    merged_profiles[nama] = isi
            merged["mines_profiles"] = merged_profiles
        return merged
    except (json.JSONDecodeError, ValueError, OSError) as e:
        print(f"❌ config.json error ({e}) — pakai nilai default sebagai fallback.")
        return dict(_DEFAULT_CONFIG)


CONFIG = load_config()

MAX_CONSECUTIVE_ERRORS = int(CONFIG["max_consecutive_errors"])  # Berhenti jika gagal N kali berturut-turut

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

LIMBO_MUTATION = """
mutation LimboBet(
  $amount: Float!
  $multiplierTarget: Float!
  $currency: CurrencyEnum!
  $identifier: String!
) {
  limboBet(
    amount: $amount
    multiplierTarget: $multiplierTarget
    currency: $currency
    identifier: $identifier
  ) {
    id
    payoutMultiplier
    amount
    payout
    currency
    state {
      ... on CasinoGameLimbo {
        result
        multiplierTarget
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


MINES_BET_MUTATION = """
mutation MinesBet(
  $amount: Float!
  $currency: CurrencyEnum!
  $minesCount: Int!
  $identifier: String!
) {
  minesBet(
    amount: $amount
    currency: $currency
    minesCount: $minesCount
    identifier: $identifier
  ) {
    id
    amount
    payout
    payoutMultiplier
    currency
    state { ... on CasinoGameMines { mines minesCount } }
  }
}
"""

MINES_NEXT_MUTATION = """
mutation MinesNext($fields: [Int!]) {
  minesNext(fields: $fields) {
    id
    amount
    payout
    payoutMultiplier
    currency
    state { ... on CasinoGameMines { mines minesCount } }
    user { balances { available { amount currency } } }
  }
}
"""

MINES_CASHOUT_MUTATION = """
mutation {
  minesCashout {
    id
    amount
    payout
    payoutMultiplier
    currency
    state { ... on CasinoGameMines { mines minesCount } }
    user { balances { available { amount currency } } }
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


def determine_win_limbo(roll_result: dict) -> bool:
    """
    Tentukan menang/kalah untuk game Limbo.
    Menang jika multiplier hasil (result) >= multiplier target yang dipasang.
    Aman terhadap dict kosong — fallback ke False jika field tidak lengkap.
    """
    if not roll_result:
        return False
    try:
        result            = Decimal(str(roll_result["result"]))
        multiplier_target = Decimal(str(roll_result["multiplierTarget"]))
        return result >= multiplier_target
    except (KeyError, TypeError, InvalidOperation):
        pass
    return False


def mines_kena_ranjau(next_state: dict) -> bool:
    """
    Tentukan apakah reveal minesNext ini kena ranjau (ronde otomatis kalah).
    Terkonfirmasi lewat tes langsung ke API: selama ronde masih aman,
    state.mines tetap null. Begitu kena ranjau, ronde auto-selesai dan
    state.mines langsung terisi (posisi semua ranjau terbuka).
    """
    if not next_state:
        return False
    return bool(next_state.get("mines"))


def hitung_odds_mines(total_tiles: int, mines: int, reveals: int):
    """
    Hitung peluang menang (kombinatorik eksak, sesuai aturan game) dan
    multiplier fair (sebelum house edge ~1%) untuk kombinasi ranjau/reveal.
    Real multiplier dari API akan sedikit lebih rendah dari nilai fair ini.
    """
    aman = total_tiles - mines
    if reveals > aman or reveals <= 0:
        return Decimal("0"), Decimal("0")
    win_chance = Decimal(comb(aman, reveals)) / Decimal(comb(total_tiles, reveals))
    multiplier_fair = (Decimal("1") / win_chance) if win_chance > 0 else Decimal("0")
    return (
        (win_chance * 100).quantize(Decimal("0.1")),
        multiplier_fair.quantize(Decimal("0.001")),
    )


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


def clear_screen():
    """Bersihkan layar terminal agar tampilan selalu fresh setiap sesi/restart.
    Pakai ANSI escape (bukan os.system) — lebih cepat & tetap aman kalau
    output di-pipe/redirect ke file (tidak error, cuma escape code ikut tertulis)."""
    print("\033[H\033[2J\033[3J", end="")


def print_banner():
    clear_screen()
    now = datetime.now().strftime("%d %b %Y  %H:%M")
    print(g(CYAN, """
  ╔══════════════════════════════════════════════════════╗
  ║                                                      ║
  ║    ██████╗  ██████╗ ████████╗                        ║
  ║    ██╔══██╗██╔═══██╗╚══██╔══╝                        ║
  ║    ██████╔╝██║   ██║   ██║                           ║
  ║    ██╔══██╗██║   ██║   ██║                           ║
  ║    ██████╔╝╚██████╔╝   ██║                           ║
  ║    ╚═════╝  ╚═════╝    ╚═╝   VIP Auto-Bet Bot        ║
  ║                                                      ║
  ║     🎮  LIMBO  ·  MINES   │  Stake.com Official API  ║
  ║     🛡️  Mode Aman & Terkontrol  ·  24/7 VPS Ready    ║
  ║                                                      ║
  ╚══════════════════════════════════════════════════════╝"""))
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


def jalankan_strategy_vip(user: dict, vps_mode: bool = False, maks_ronde: Optional[int] = None):
    """
    Auto-bet Strategy VIP: LIMBO, 98% Win Chance (target multiplier 1.01x),
    money management "On-Loss Multiply" (naik 2% tiap kalah, reset saat menang).

    Tujuan  : Mengumpulkan volume wager secepat mungkin untuk naik VIP,
              dengan manajemen modal yang lebih efisien dibanding martingale
              penuh — kenaikan bet kecil & bertahap, bukan lipat 100%.

    Catatan Limbo   : Karena bot bertaruh langsung lewat API (bukan lewat UI
                      web), tidak ada animasi roll sama sekali — setiap bet
                      sudah otomatis "instant/fast" tanpa perlu setting lain.

    Logika istirahat:
      - Setiap Rp 5.000.000 wager kumulatif → istirahat 15 menit, lanjut otomatis
      - Stop-loss Rp 45.000 → istirahat 5–10 menit, lanjut sesi baru

    Log terminal setiap spin: nomor bet, wager, saldo, loss, W/L, dan durasi bot berjalan.

    Returns True jika ingin lanjut sesi baru, False jika user Ctrl+C.
    """

    # ── Konfigurasi strategi (dari config.json — TIDAK hardcode) ─────────────
    currency            = CONFIG["currency"]
    base_bet            = Decimal(str(CONFIG["base_bet"]))
    rest_setiap_volume  = Decimal(str(CONFIG["rest_setiap_volume"]))
    rest_menit_volume   = int(CONFIG["rest_menit_volume"])
    max_loss_limit      = Decimal(str(CONFIG["max_loss_limit"]))
    topup_alert_idr     = Decimal(str(CONFIG["topup_alert_idr"]))
    win_chance_pct      = Decimal(str(CONFIG["win_chance_pct"]))
    multiplier_target   = (Decimal("99") / win_chance_pct).quantize(
                              Decimal("0.0001"), rounding=ROUND_DOWN)   # ≈ 1.0102x

    # ── Konfigurasi On-Loss Multiply (money management ringan) ───────────────
    # Desain: kalah → bet naik 2% (BUKAN martingale 100%). Menang → langsung
    # kembali ke Base Bet. Pertumbuhan geometris lambat sehingga modal tetap
    # aman walau kena losing streak panjang. Ada cap keras agar tidak liar.
    on_loss_multiply_enabled = bool(CONFIG["on_loss_multiply_enabled"])
    on_loss_multiply_pct     = Decimal(str(CONFIG["on_loss_multiply_pct"]))
    on_loss_multiply_cap     = base_bet * Decimal(str(CONFIG["on_loss_multiply_cap_multiplier"]))

    # ── Tampilkan VIP status otomatis di atas CLI ─────────────────────────────
    flag_progress = user.get("flagProgress") or {"flag": "none", "progress": 0}
    print_vip_status(flag_progress)

    # ── Info konfigurasi sesi ─────────────────────────────────────────────────
    print_section("STRATEGY VIP — LIMBO 98% WIN CHANCE  (SPEED MODE)")
    print(f"  Game          : {g(BOLD, 'LIMBO')}  {g(DIM, '(via API — otomatis instant, tanpa animasi)')}")
    print(f"  Currency      : {g(BOLD, 'IDR (Rupiah)')}")
    print(f"  Base Bet      : {g(BOLD, fmt(base_bet, currency))}  {g(DIM, '← ubah di config.json')}")
    print(f"  Win Chance    : {g(BOLD, f'{win_chance_pct}%')}  |  Target Multiplier: {g(BOLD, f'{multiplier_target}x')}")
    print(f"  Rest Checkpoint : setiap {g(CYAN, fmt(rest_setiap_volume, currency))} wager → {g(CYAN, str(rest_menit_volume) + ' menit')}")
    print(f"  Stop-Loss     : {g(RED, fmt(max_loss_limit, currency))} loss → istirahat 5–10 mnt lalu lanjut")
    if on_loss_multiply_enabled:
        print(f"  On-Loss Multiply : {g(GREEN, 'AKTIF')}  "
              f"{g(DIM, f'+{on_loss_multiply_pct}% tiap kalah · cap {fmt(on_loss_multiply_cap, currency)} · reset saat menang')}")
    else:
        print(f"  On-Loss Multiply : {g(DIM, 'nonaktif (flat bet)')}")
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
    sudah_istirahat_internal = False  # True jika sesi ini sudah istirahat sendiri (stop-loss) — cegah istirahat dobel di caller vps_mode
    next_rest_checkpoint = rest_setiap_volume     # Checkpoint volume berikutnya
    next_million_notif   = Decimal("1000000")     # Milestone print di terminal tiap Rp1 juta wager
    _topup_notified      = False                  # Agar alert top-up hanya kirim sekali per sesi
    sesi_mulai           = datetime.now()         # Timer durasi bot berjalan
    take_profit_idr      = Decimal(str(CONFIG["take_profit_idr"]))  # Jeda 5 dtk setiap kelipatan profit ini
    next_take_profit     = take_profit_idr        # Threshold profit berikutnya
    session_take_profit  = Decimal(str(CONFIG.get("session_take_profit_idr", "0")))  # Hard-stop sesi saat profit ini

    # ── On-Loss Multiply state ────────────────────────────────────────────────
    current_bet         = base_bet    # Bet aktif saat ini
    loss_streak          = 0           # Kalah beruntun sejak reset terakhir
    max_loss_streak_bet  = 0           # Loss streak terpanjang dalam sesi ini
    max_bet_reached      = base_bet   # Bet tertinggi yang pernah dipasang
    cap_hit_count        = 0           # Berapa kali bet kena cap (mentok 5× base bet)

    # ── Profit Lock & Balance Tracking ───────────────────────────────────────
    saldo_awal           = None              # Saldo sesi (dicatat dari bal pertama)
    profit_lock_idr      = Decimal(str(CONFIG["profit_lock_idr"]))  # Stop-loss naik setiap saldo bertambah Rp X
    profit_lock_level    = 0                 # Sudah berapa kali profit lock naik

    try:
        while True:

            # ── Kirim taruhan ke Stake via API ────────────────────────────────
            identifier = str(uuid.uuid4())
            try:
                api_result = gql(LIMBO_MUTATION, {
                    "amount":           float(current_bet),
                    "multiplierTarget": float(multiplier_target),
                    "currency":         currency,
                    "identifier":       identifier,
                })
                roll            = api_result["limboBet"]
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

            won_state       = determine_win_limbo(state)
            won_payout      = payout > amount
            won             = won_payout if not state else won_state
            bet_sebelum_ini = current_bet   # Capture sebelum on-loss-multiply mengubahnya

            # ── Update statistik ──────────────────────────────────────────────
            total_volume += current_bet
            total_loss   -= profit   # negatif jika menang, positif jika kalah

            if won:
                wins += 1
            else:
                losses += 1

            # ── On-Loss Multiply: naik 2% tiap kalah, reset ke base saat menang ─
            if won:
                if loss_streak > 0:
                    print(g(GREEN,
                        f"  ✅ MENANG — reset ke Base Bet {fmt(base_bet, currency)} "
                        f"(setelah {loss_streak}x kalah beruntun)"
                    ))
                loss_streak = 0
                current_bet = base_bet
            elif on_loss_multiply_enabled:
                loss_streak += 1
                max_loss_streak_bet = max(max_loss_streak_bet, loss_streak)
                naik = current_bet * (Decimal("1") + on_loss_multiply_pct / Decimal("100"))
                if naik >= on_loss_multiply_cap:
                    current_bet = on_loss_multiply_cap
                    cap_hit_count += 1
                else:
                    current_bet = naik.quantize(_quanta(currency), rounding=ROUND_DOWN)
                max_bet_reached = max(max_bet_reached, current_bet)

            # ── Ambil saldo terkini ───────────────────────────────────────────
            user_bals  = roll.get("user", {}).get("balances", [])
            bal_amount = next(
                (b["available"]["amount"] for b in user_bals
                 if b["available"]["currency"] == currency), None)

            bal_dec = to_dec(bal_amount) if bal_amount is not None else None

            # ── Catat saldo awal sesi (sekali saja dari bet pertama) ──────────
            if saldo_awal is None and bal_dec is not None:
                saldo_awal = bal_dec

            # ── Profit Lock — naikkan stop-loss saat surplus +Rp20.000 ─────────
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
                speed_str = "-- b/m"

            bal_k  = idr_k(bal_amount) if bal_amount is not None else "N/A"
            loss_k = idr_k(total_loss)

            # Tandai apakah bet ini sudah naik dari base bet (on-loss multiply aktif)
            bet_label = (g(YELLOW, f"x{(bet_sebelum_ini / base_bet):.2f} {idr_k(amount)}")
                         if bet_sebelum_ini != base_bet
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

            # ── Session Take-Profit: stop sesi langsung saat profit target tercapai ─
            if session_take_profit > 0 and saldo_awal is not None and bal_dec is not None:
                net_saldo = bal_dec - saldo_awal
                if net_saldo >= session_take_profit:
                    print(g(GREEN,
                        f"\n  🎯 TAKE-PROFIT +{idr_k(net_saldo)} IDR tercapai! "
                        f"(target: +{idr_k(session_take_profit)} IDR)\n"
                        f"  Sesi ini selesai — mulai sesi baru fresh.\n"
                    ))
                    sudah_istirahat_internal = False
                    break

            # ── Cek stop-loss ─────────────────────────────────────────────────
            if total_loss >= max_loss_limit:
                jeda = random.randint(5, 10)
                print(g(RED,
                    f"\n  🛑 Stop-loss {fmt(max_loss_limit, currency)} tercapai di bet #{ronde}. "
                    f"Istirahat {jeda} menit untuk mengamankan modal..."
                ))
                rest_countdown(jeda)
                sudah_istirahat_internal = True
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

            # ── Batas ronde manual (untuk test live terbatas, misal 100 spin) ──
            if maks_ronde is not None and ronde >= maks_ronde:
                print(g(CYAN, f"\n  🏁 Batas {maks_ronde} ronde tercapai — sesi test dihentikan.\n"))
                break

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

    # ── Statistik On-Loss Multiply ─────────────────────────────────────────────
    if on_loss_multiply_enabled and max_loss_streak_bet > 0:
        print(f"\n  {g(CYAN, '◆')} {g(BOLD, 'STATISTIK ON-LOSS MULTIPLY')}")
        print(f"  {g(CYAN, '─' * 52)}")
        print(f"  {'Loss Streak Terpanjang':<24} {g(YELLOW, str(max_loss_streak_bet))}x")
        print(f"  {'Bet Tertinggi Dipasang':<24} {g(YELLOW, fmt(max_bet_reached, currency))}")
        print(f"  {'Bet Kena Cap (5x)':<24} {g(RED if cap_hit_count > 0 else DIM, f'{cap_hit_count} kali')}")
        print(f"  {g(CYAN, '─' * 52)}")
    elif on_loss_multiply_enabled:
        print(g(DIM, "\n  🛡  On-Loss Multiply: tidak ada loss dalam sesi ini — bet tetap flat"))

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
        # Tuple (lanjut, sudah_istirahat_internal) — caller pakai flag kedua
        # untuk skip istirahat tambahan kalau sesi ini sudah istirahat sendiri
        # (misal karena stop-loss), jadi tidak dobel istirahat.
        return (not stopped_by_user), sudah_istirahat_internal  # lanjut=False jika user Ctrl+C = berhenti total

    # ── Tanya apakah mau mulai sesi baru (mode normal) ───────────────────────
    print()
    try:
        jawab = input(g(YELLOW, "  🔁 Mulai sesi baru? (y/n): ")).strip().lower()
        return jawab in ("y", "ya", "yes", "1")
    except (EOFError, KeyboardInterrupt):
        return False


def jalankan_strategy_mines_vip(user: dict, vps_mode: bool = False, maks_ronde: Optional[int] = None, profile: str = "normal"):
    """
    Auto-bet Strategy VIP: MINES, 1 ranjau dari 25 kotak, buka 2 kotak fixed
    lalu auto cash-out (≈92% menang, ≈1,08x per menang).

    Catatan penting: posisi ranjau di-generate ulang secara acak & independen
    tiap ronde lewat Provably Fair — kotak mana yang dibuka TIDAK mempengaruhi
    peluang menang. Dua kotak fixed dipakai murni demi kesederhanaan kode.

    Money management "Recovery 1.5x":
      - Menang  → bet tetap flat (tidak naik), profit dicatat ke streak_net.
      - Kalah   → bet naik 1.5x dari bet SEBELUMNYA (bukan compounding dari base),
                  dengan cap keras agar tidak liar.
      - Reset ke Base Bet baru terjadi setelah streak_net (net sejak reset
        terakhir) balik ke ≥ 0 — bukan langsung di kemenangan pertama.
      - Kalau kena ranjau 2x berturut-turut → istirahat singkat (mines_double_loss_rest_menit).

    Returns True jika ingin lanjut sesi baru, False jika user Ctrl+C.
    """

    # ── Konfigurasi strategi (dari config.json) ──────────────────────────────
    currency            = CONFIG["currency"]
    base_bet            = Decimal(str(CONFIG["base_bet"]))
    rest_setiap_volume  = Decimal(str(CONFIG["rest_setiap_volume"]))
    rest_menit_volume   = int(CONFIG["rest_menit_volume"])
    max_loss_limit      = Decimal(str(CONFIG["max_loss_limit"]))
    topup_alert_idr     = Decimal(str(CONFIG["topup_alert_idr"]))

    mines_profile               = CONFIG["mines_profiles"].get(profile) or CONFIG["mines_profiles"]["normal"]
    mines_count                 = int(mines_profile["mines_count"])
    mines_fields                = [int(x) for x in mines_profile["tile_indices"]]
    mines_loss_multiplier       = Decimal(str(mines_profile["loss_multiplier"]))
    mines_cap                   = base_bet * Decimal(str(mines_profile["cap_multiplier"]))
    mines_double_loss_rest_menit = int(mines_profile.get("double_loss_rest_menit", 1))
    # double_loss_rest_detik override — jika ada, pakai detik (lebih presisi untuk VPS)
    _detik_override = mines_profile.get("double_loss_rest_detik")
    if _detik_override is not None:
        mines_double_loss_rest_detik = int(_detik_override)
        mines_double_loss_rest_menit = 0   # nonaktifkan hitungan menit
    else:
        mines_double_loss_rest_detik = mines_double_loss_rest_menit * 60
    mines_throttle              = bool(mines_profile.get("throttle", True))
    mines_instant_reset         = bool(mines_profile.get("instant_reset", False))
    # Profil boleh override stop-loss global — dipakai profil "aman" untuk batas lebih ketat
    if "max_loss_override" in mines_profile:
        max_loss_limit = Decimal(str(mines_profile["max_loss_override"]))
    win_chance_pct, multiplier_fair = hitung_odds_mines(25, mines_count, len(mines_fields))

    # ── Bet Dinamis: base bet = % dari saldo saat ini ─────────────────────────
    _dyn_pct_raw = mines_profile.get("dynamic_bet_pct")
    dynamic_bet_enabled = _dyn_pct_raw is not None
    if dynamic_bet_enabled:
        dynamic_bet_pct = Decimal(str(_dyn_pct_raw)) / Decimal("100")
        dynamic_bet_min = Decimal(str(mines_profile.get("dynamic_bet_min_idr", str(CONFIG["base_bet"]))))
        dynamic_bet_max = Decimal(str(mines_profile.get("dynamic_bet_max_idr", "99999")))
        # Hitung initial base_bet dari saldo awal (user dict dikirim dari caller)
        _init_bals = user.get("balances", [])
        _init_bal  = to_dec(next(
            (b["available"]["amount"] for b in _init_bals
             if b["available"]["currency"] == currency), "0"
        ))
        if _init_bal > 0:
            _computed  = (_init_bal * dynamic_bet_pct).quantize(_quanta(currency), rounding=ROUND_DOWN)
            base_bet   = max(dynamic_bet_min, min(_computed, dynamic_bet_max))
            mines_cap  = base_bet * Decimal(str(mines_profile["cap_multiplier"]))
    else:
        dynamic_bet_pct = Decimal("0")
        dynamic_bet_min = base_bet
        dynamic_bet_max = base_bet

    # ── Tampilkan VIP status otomatis di atas CLI ─────────────────────────────
    flag_progress = user.get("flagProgress") or {"flag": "none", "progress": 0}
    print_vip_status(flag_progress)

    # ── Info konfigurasi sesi ─────────────────────────────────────────────────
    # Label keamanan per profil
    _safety_labels = {
        "aman":    g(GREEN,  "🛡️  AMAN       — modal diutamakan, lambat tapi terkontrol"),
        "normal":  g(YELLOW, "⚖️  SEIMBANG  — keseimbangan antara keamanan & volume"),
        "agresif": g(RED,    "⚡  AGRESIF   — volume tinggi, risiko saldo lebih besar"),
        "wager":   g(CYAN,   "🚀  WAGER     — maksimum kecepatan, cocok modal besar"),
    }
    _safety_line = _safety_labels.get(profile, g(DIM, profile.upper()))

    print_section(f"STRATEGY VIP — MINES {mines_count} RANJAU  ({profile.upper()})")
    print(f"  {_safety_line}")
    print(f"  {g(CYAN, '─' * 52)}")
    print(f"  Game          : {g(BOLD, 'MINES')}  {g(DIM, f'({mines_count} ranjau dari 25 kotak · buka {len(mines_fields)} kotak fixed)')}")
    print(f"  Currency      : {g(BOLD, 'IDR (Rupiah)')}")
    if dynamic_bet_enabled:
        print(f"  Bet Dinamis   : {g(GREEN, 'AKTIF')} — {float(dynamic_bet_pct)*100:.2f}% saldo "
              f"· min {fmt(dynamic_bet_min, currency)} · max {fmt(dynamic_bet_max, currency)}")
        print(f"  Base Bet Awal : {g(BOLD, fmt(base_bet, currency))}  {g(DIM, '(dihitung otomatis dari saldo)')}")
    else:
        print(f"  Base Bet      : {g(BOLD, fmt(base_bet, currency))}  {g(DIM, '← ubah di config.json')}")
    print(f"  Peluang Menang: {g(BOLD, f'≈{win_chance_pct}%')}  |  Multiplier fair: {g(BOLD, f'≈{multiplier_fair}x')}")
    print(f"  Stop-Loss     : {g(RED, fmt(max_loss_limit, currency))} loss → istirahat lalu lanjut"
          + (g(GREEN, "  ← lebih ketat dari default") if "max_loss_override" in mines_profile else ""))
    _reset_label = g(GREEN, "INSTANT (tiap menang)") if mines_instant_reset else g(YELLOW, "MODAL BALIK (tunggu balik modal dulu)")
    naik_pct = (mines_loss_multiplier - Decimal("1")) * 100
    print(f"  Recovery Bet  : {g(DIM, f'+{naik_pct:.0f}% tiap kalah')} · cap {g(YELLOW, fmt(mines_cap, currency))} · Reset: {_reset_label}")
    if mines_double_loss_rest_detik > 0:
        _dl_label = (f"{mines_double_loss_rest_detik} detik"
                     if mines_double_loss_rest_detik < 60
                     else f"{mines_double_loss_rest_detik // 60} menit")
        print(f"  Double-Loss   : istirahat {g(YELLOW, _dl_label)} jika kena ranjau 2x berturut-turut")
    else:
        print(f"  Double-Loss   : {g(DIM, 'tanpa jeda (profil wager)')}")
    print(g(DIM, "\n  Tekan Ctrl+C untuk berhenti kapan saja.\n"))

    # ── State tracker ────────────────────────────────────────────────────────
    total_volume         = Decimal("0")
    total_loss           = Decimal("0")
    wins                 = 0
    losses               = 0
    consecutive_err      = 0
    ronde                = 0
    stopped_by_user      = False
    sudah_istirahat_internal = False
    next_rest_checkpoint = rest_setiap_volume
    next_million_notif   = Decimal("1000000")
    _topup_notified      = False
    sesi_mulai           = datetime.now()
    take_profit_idr      = Decimal(str(CONFIG["take_profit_idr"]))
    next_take_profit     = take_profit_idr
    session_take_profit  = Decimal(str(CONFIG.get("session_take_profit_idr", "0")))  # Hard-stop sesi

    # ── Recovery 1.5x state ────────────────────────────────────────────────────
    current_bet          = base_bet
    streak_net           = Decimal("0")   # net profit/loss sejak reset terakhir
    loss_streak          = 0
    max_loss_streak_bet   = 0
    max_bet_reached       = base_bet
    cap_hit_count         = 0
    hasil_2_terakhir      = []   # True=menang, False=kalah — deteksi kena ranjau 2x berturut

    # ── Profit Lock & Balance Tracking ───────────────────────────────────────
    saldo_awal           = None
    bal_dec              = None   # inisialisasi — cegah crash saat menang di ronde pertama
    bal_amount           = None
    profit_lock_idr      = Decimal(str(CONFIG["profit_lock_idr"]))
    profit_lock_level    = 0

    try:
        while True:

            # ── 1. Mulai ronde: minesBet ──────────────────────────────────────
            identifier = str(uuid.uuid4())
            bet_sebelum_ini = current_bet
            try:
                gql(MINES_BET_MUTATION, {
                    "amount":     float(current_bet),
                    "currency":   currency,
                    "minesCount": mines_count,
                    "identifier": identifier,
                })
                consecutive_err = 0
            except PermissionError as e:
                print(g(RED, f"\n  ❌ Auth error, sesi dihentikan: {e}"))
                break
            except Exception as e:
                consecutive_err += 1
                print(g(RED, f"  ❌ Error API minesBet ({consecutive_err}/{MAX_CONSECUTIVE_ERRORS}): {e}"))
                if consecutive_err >= MAX_CONSECUTIVE_ERRORS:
                    print(g(RED, "  🛑 Terlalu banyak error berturut-turut. Sesi dihentikan."))
                    break
                time.sleep(2)
                continue

            # ── 2. Buka kotak: minesNext ──────────────────────────────────────
            try:
                next_result = gql(MINES_NEXT_MUTATION, {"fields": mines_fields})["minesNext"]
                consecutive_err = 0
            except PermissionError as e:
                print(g(RED, f"\n  ❌ Auth error, sesi dihentikan: {e}"))
                break
            except Exception as e:
                consecutive_err += 1
                print(g(RED, f"  ❌ Error API minesNext ({consecutive_err}/{MAX_CONSECUTIVE_ERRORS}): {e}"))
                if consecutive_err >= MAX_CONSECUTIVE_ERRORS:
                    print(g(RED, "  🛑 Terlalu banyak error berturut-turut. Sesi dihentikan."))
                    break
                time.sleep(2)
                continue

            ronde += 1
            state = next_result.get("state") or {}
            kena_ranjau = mines_kena_ranjau(state)

            if kena_ranjau:
                # ── Kalah: ronde otomatis selesai, tidak perlu cashout ─────────
                amount     = current_bet
                payout     = Decimal("0")
                user_bals  = next_result.get("user", {}).get("balances", [])
            else:
                # ── 3. Aman: kunci profit dengan minesCashout ──────────────────
                try:
                    cashout_result = gql(MINES_CASHOUT_MUTATION)["minesCashout"]
                    consecutive_err = 0
                except PermissionError as e:
                    print(g(RED, f"\n  ❌ Auth error, sesi dihentikan: {e}"))
                    break
                except Exception as e:
                    consecutive_err += 1
                    print(g(RED, f"  ❌ Error API minesCashout ({consecutive_err}/{MAX_CONSECUTIVE_ERRORS}): {e}"))
                    if consecutive_err >= MAX_CONSECUTIVE_ERRORS:
                        print(g(RED, "  🛑 Terlalu banyak error berturut-turut. Sesi dihentikan."))
                        break
                    time.sleep(2)
                    continue
                amount    = to_dec(cashout_result.get("amount", current_bet))
                payout    = to_dec(cashout_result.get("payout", 0))
                user_bals = cashout_result.get("user", {}).get("balances", [])

            profit = (payout - amount).quantize(_quanta(currency), rounding=ROUND_DOWN)
            won    = payout > amount

            # ── Update statistik ──────────────────────────────────────────────
            total_volume += current_bet
            total_loss   -= profit

            if won:
                wins += 1
            else:
                losses += 1

            # ── Recovery 1.5x: naik saat kalah, reset saat modal balik ────────
            hasil_2_terakhir.append(won)
            hasil_2_terakhir = hasil_2_terakhir[-2:]

            if won:
                streak_net += profit
                should_reset = mines_instant_reset or (streak_net >= 0)
                if should_reset:
                    # ── Bet Dinamis: recalculate base_bet dari saldo terbaru ──
                    if dynamic_bet_enabled and bal_dec is not None and bal_dec > 0:
                        _computed  = (bal_dec * dynamic_bet_pct).quantize(_quanta(currency), rounding=ROUND_DOWN)
                        _new_base  = max(dynamic_bet_min, min(_computed, dynamic_bet_max))
                        if _new_base != base_bet:
                            print(g(DIM,
                                f"  📊 Bet dinamis: saldo {idr_k(bal_dec)} IDR "
                                f"→ base bet {fmt(_new_base, currency)}"
                            ))
                        base_bet  = _new_base
                        mines_cap = base_bet * Decimal(str(mines_profile["cap_multiplier"]))
                    if current_bet != base_bet:
                        _reset_tag = "INSTANT RESET" if mines_instant_reset else "MODAL BALIK"
                        print(g(GREEN,
                            f"  ✅ {_reset_tag} — kembali ke Base Bet {fmt(base_bet, currency)} "
                            f"(setelah {loss_streak}x kalah beruntun)"
                        ))
                    loss_streak = 0
                    current_bet = base_bet
                    streak_net  = Decimal("0")
            else:
                streak_net -= amount
                loss_streak += 1
                max_loss_streak_bet = max(max_loss_streak_bet, loss_streak)
                naik = current_bet * mines_loss_multiplier
                if naik >= mines_cap:
                    current_bet = mines_cap
                    cap_hit_count += 1
                else:
                    current_bet = naik.quantize(_quanta(currency), rounding=ROUND_DOWN)
                max_bet_reached = max(max_bet_reached, current_bet)

            # ── Ambil saldo terkini ───────────────────────────────────────────
            bal_amount = next(
                (b["available"]["amount"] for b in user_bals
                 if b["available"]["currency"] == currency), None)
            bal_dec = to_dec(bal_amount) if bal_amount is not None else None

            if saldo_awal is None and bal_dec is not None:
                saldo_awal = bal_dec

            # ── Profit Lock ────────────────────────────────────────────────────
            if saldo_awal is not None and bal_dec is not None:
                surplus = bal_dec - saldo_awal
                target_lock = profit_lock_idr * (profit_lock_level + 1)
                if surplus >= target_lock:
                    profit_lock_level += 1
                    max_loss_limit = total_loss + profit_lock_idr
                    print(g(GREEN,
                        f"\n  🔒 PROFIT LOCK #{profit_lock_level}: "
                        f"Surplus +{idr_k(surplus)} IDR — "
                        f"Stop-loss dinaikkan ke {fmt(max_loss_limit, currency)}\n"
                    ))

            # ── Top-Up Alert ───────────────────────────────────────────────────
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

            # ── Log setiap spin ────────────────────────────────────────────────
            elapsed      = datetime.now() - sesi_mulai
            elapsed_sek  = elapsed.total_seconds()
            total_sec    = int(elapsed_sek)
            jam, sisa    = divmod(total_sec, 3600)
            mnt, dtk     = divmod(sisa, 60)
            durasi_str   = f"{jam:02d}:{mnt:02d}:{dtk:02d}"
            win_rate     = Decimal(wins) / Decimal(ronde) * 100
            ikon         = g(GREEN, "✅") if won else g(RED, "❌")
            loss_color   = RED if total_loss > 0 else DIM

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
                speed_str = "-- b/m"

            bal_k  = idr_k(bal_amount) if bal_amount is not None else "N/A"
            loss_k = idr_k(total_loss)

            bet_label = (g(YELLOW, f"x{(bet_sebelum_ini / base_bet):.2f} {idr_k(amount)}")
                         if bet_sebelum_ini != base_bet
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

            # ── Kena ranjau 2x berturut-turut → istirahat singkat ─────────────
            if hasil_2_terakhir == [False, False] and mines_double_loss_rest_detik > 0:
                _dl_str = (f"{mines_double_loss_rest_detik} detik"
                           if mines_double_loss_rest_detik < 60
                           else f"{mines_double_loss_rest_detik // 60} menit")
                print(g(RED, f"\n  💣 Kena ranjau 2x berturut-turut — jeda {_dl_str}..."))
                if mines_double_loss_rest_detik < 60:
                    # Countdown pendek — tampilkan hitungan mundur per detik tanpa bar panjang
                    try:
                        for sisa in range(mines_double_loss_rest_detik, 0, -1):
                            print(f"\r  ⏳ {g(YELLOW, str(sisa))} detik tersisa...   ", end="", flush=True)
                            time.sleep(1)
                        print(f"\r  {g(GREEN, '✅')} Jeda selesai.{' ' * 25}")
                    except KeyboardInterrupt:
                        print(f"\n  {g(YELLOW, '⏩')} Skip jeda.")
                else:
                    rest_countdown(mines_double_loss_rest_detik // 60)
                hasil_2_terakhir = []
                print(g(GREEN, "  ▶  Lanjut betting...\n"))

            # ── Milestone setiap Rp1 juta wager ──────────────────────────────
            if total_volume >= next_million_notif:
                next_million_notif += Decimal("1000000")
                print(g(CYAN, f"\n  🎯 Milestone {idr_k(total_volume)} IDR wager tercapai!\n"))

            # ── Take-profit: jeda 5 dtk setiap kelipatan Rp 5.000 profit ──────
            net_sesi = -total_loss
            if net_sesi >= next_take_profit:
                next_take_profit += take_profit_idr
                print(g(GREEN,
                    f"\n  💰 Profit +{idr_k(net_sesi)} IDR — jeda 5 detik...\n"
                ))
                time.sleep(5)

            # ── Session Take-Profit: stop sesi langsung saat profit target tercapai ─
            if session_take_profit > 0 and saldo_awal is not None and bal_dec is not None:
                net_saldo = bal_dec - saldo_awal
                if net_saldo >= session_take_profit:
                    print(g(GREEN,
                        f"\n  🎯 TAKE-PROFIT +{idr_k(net_saldo)} IDR tercapai! "
                        f"(target: +{idr_k(session_take_profit)} IDR)\n"
                        f"  Sesi ini selesai — mulai sesi baru fresh.\n"
                    ))
                    sudah_istirahat_internal = False
                    break

            # ── Cek stop-loss ─────────────────────────────────────────────────
            if total_loss >= max_loss_limit:
                jeda = random.randint(5, 10)
                print(g(RED,
                    f"\n  🛑 Stop-loss {fmt(max_loss_limit, currency)} tercapai di bet #{ronde}. "
                    f"Istirahat {jeda} menit untuk mengamankan modal..."
                ))
                rest_countdown(jeda)
                sudah_istirahat_internal = True
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
                continue

            # ── Auto-throttle (dinonaktifkan untuk profil wager) ─────────────
            if mines_throttle:
                if bet_per_mnt > 50:
                    time.sleep(2)
                elif bet_per_mnt > 30:
                    time.sleep(1)

            # ── Batas ronde manual ────────────────────────────────────────────
            if maks_ronde is not None and ronde >= maks_ronde:
                print(g(CYAN, f"\n  🏁 Batas {maks_ronde} ronde tercapai — sesi test dihentikan.\n"))
                break

    except KeyboardInterrupt:
        print(g(YELLOW, "\n\n  ⏹  Dihentikan oleh pengguna."))
        stopped_by_user = True

    # ── Ringkasan akhir sesi Mines ─────────────────────────────────────────────
    total    = wins + losses
    win_rate = (Decimal(wins) / Decimal(total) * 100) if total > 0 else Decimal("0")
    net      = -total_loss

    print_section("RINGKASAN STRATEGY MINES")
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

    if max_loss_streak_bet > 0:
        print(f"\n  {g(CYAN, '◆')} {g(BOLD, 'STATISTIK RECOVERY 1.5x')}")
        print(f"  {g(CYAN, '─' * 52)}")
        print(f"  {'Loss Streak Terpanjang':<24} {g(YELLOW, str(max_loss_streak_bet))}x")
        print(f"  {'Bet Tertinggi Dipasang':<24} {g(YELLOW, fmt(max_bet_reached, currency))}")
        print(f"  {'Bet Kena Cap':<24} {g(RED if cap_hit_count > 0 else DIM, f'{cap_hit_count} kali')}")
        print(f"  {g(CYAN, '─' * 52)}")
    else:
        print(g(DIM, "\n  🛡  Recovery 1.5x: tidak ada loss dalam sesi ini — bet tetap flat"))

    # ── Refresh VIP progress dari API setelah sesi selesai ───────────────────
    flag_before = flag_progress.get("flag") or "none"
    prog_before = float(flag_progress.get("progress") or 0)
    try:
        fresh_user   = gql(USER_QUERY)["user"]
        flag_after   = fresh_user.get("flagProgress") or {"flag": "none", "progress": 0}
        flag_now     = flag_after.get("flag") or "none"
        prog_now     = float(flag_after.get("progress") or 0)

        print()
        print(g(BOLD, "  📊 VIP Progress setelah sesi:"))
        print_vip_status(flag_after)

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
        pass

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

    if vps_mode:
        return (not stopped_by_user), sudah_istirahat_internal

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

    # ── Menu pilihan game: dipilih SEKALI di awal, lalu loop terus di game itu ─
    print_section("PILIH GAME")
    print(f"  {g(BOLD, '1')}. Limbo  {g(DIM, '(on-loss multiply +2%)')}")
    print(f"  {g(BOLD, '2')}. Mines  {g(DIM, '(1/3 ranjau · recovery 1.5x/1.3x)')}")
    try:
        pilihan = input(g(YELLOW, "\n  Pilih game (1/2, default 1): ")).strip()
    except (EOFError, KeyboardInterrupt):
        pilihan = ""
    game_terpilih = "mines" if pilihan == "2" else "limbo"
    mines_profile_terpilih = "normal"

    if game_terpilih == "mines":
        _pr   = CONFIG["mines_profiles"]
        _pn   = _pr["normal"];   _pa = _pr["agresif"]
        _pw   = _pr.get("wager", {}); _pam = _pr.get("aman", {})
        _base = float(Decimal(str(CONFIG["base_bet"])))

        def _info(p, bpm):
            odds, mult = hitung_odds_mines(25, int(p.get("mines_count",1)), len(p.get("tile_indices",[0])))
            cap  = _base * float(p.get("cap_multiplier", 5))
            sloss = float(p.get("max_loss_override") or CONFIG["max_loss_limit"])
            return odds, mult, idr_k(cap), idr_k(sloss), idr_k(bpm * 60 * _base)

        odds_am, mult_am, cap_am, sl_am, wj_am = _info(_pam, 7)
        odds_n,  mult_n,  cap_n,  sl_n,  wj_n  = _info(_pn,  7)
        odds_a,  mult_a,  cap_a,  sl_a,  wj_a  = _info(_pa,  7)
        odds_w,  mult_w,  cap_w,  sl_w,  wj_w  = _info(_pw,  12)

        print()
        print(f"  {g(BOLD,'  #')}  {'Profil':<10} {'Win%':<8} {'Mult':<8} {'Cap bet':<12} {'Stop-loss':<12} {'Keamanan'}")
        print(f"  {g(CYAN, '─'*72)}")
        print(f"  {g(BOLD,'  1')}  {'Aman':<10} {g(GREEN,f'≈{odds_am}%'):<18} {g(GREEN,f'≈{mult_am}x'):<17} {g(GREEN,f'{cap_am} IDR'):<21} {g(GREEN,f'{sl_am} IDR'):<21} {g(GREEN,'🛡️  PALING AMAN ← rekomendasi')}")
        print(f"  {g(BOLD,'  2')}  {'Normal':<10} {g(YELLOW,f'≈{odds_n}%'):<18} {g(YELLOW,f'≈{mult_n}x'):<17} {g(YELLOW,f'{cap_n} IDR'):<21} {g(YELLOW,f'{sl_n} IDR'):<21} {g(YELLOW,'⚖️  Seimbang')}")
        print(f"  {g(BOLD,'  3')}  {'Agresif':<10} {g(RED,f'≈{odds_a}%'):<18} {g(RED,f'≈{mult_a}x'):<17} {g(RED,f'{cap_a} IDR'):<21} {g(RED,f'{sl_a} IDR'):<21} {g(RED,'⚡  Risiko tinggi')}")
        print(f"  {g(BOLD,'  4')}  {'Wager':<10} {g(DIM,f'≈{odds_w}%'):<16} {g(DIM,f'≈{mult_w}x'):<15} {g(DIM,f'{cap_w} IDR'):<19} {g(DIM,f'{sl_w} IDR'):<19} {g(DIM,'🚀  Kecepatan, bukan keamanan')}")
        try:
            sub_pilihan = input(g(YELLOW, "\n  Pilih profil Mines (1/2/3/4, default 1): ")).strip()
        except (EOFError, KeyboardInterrupt):
            sub_pilihan = ""
        if sub_pilihan == "2":
            mines_profile_terpilih = "normal"
        elif sub_pilihan == "3":
            mines_profile_terpilih = "agresif"
        elif sub_pilihan == "4":
            mines_profile_terpilih = "wager"
        else:
            mines_profile_terpilih = "aman"

    if game_terpilih == "mines":
        strategy_fn = lambda user, vps_mode, maks_ronde=None: jalankan_strategy_mines_vip(
            user=user, vps_mode=vps_mode, maks_ronde=maks_ronde, profile=mines_profile_terpilih)
        label_sesi = f"MINES-{mines_profile_terpilih.upper()}"
    else:
        strategy_fn = jalankan_strategy_vip
        label_sesi  = "LIMBO"
    print(g(GREEN, f"\n  ▶  Game terpilih: {g(BOLD, label_sesi)}\n"))

    # ── VPS Auto-Run: jalan 24/7, otomatis tanpa input ───────────────────────
    print(g(GREEN, "  ✅ VPS Auto-Run aktif — sesi baru otomatis setelah setiap sesi selesai"))
    print(g(DIM,   "  Ctrl+C saat betting = keluar. Ctrl+C saat istirahat = skip jeda.\n"))

    rest_menit = int(CONFIG["rest_menit_antar_sesi"])
    sesi_ke    = 1
    while True:
        clear_screen()  # Layar fresh setiap sesi baru — tidak numpuk log lama di terminal
        waktu_mulai = datetime.now().strftime("%d/%m %H:%M")
        print(g(CYAN, f"\n  ╔═══ SESI #{sesi_ke} ({game_terpilih.upper()})  ·  {waktu_mulai} ═══╗"))

        try:
            user = gql(USER_QUERY)["user"]
        except Exception as e:
            print(g(YELLOW, f"  ⚠️  Gagal refresh data user: {e} — lanjut dengan data sesi sebelumnya."))

        lanjut, sudah_istirahat_internal = strategy_fn(user=user, vps_mode=True)
        if not lanjut:
            print(g(YELLOW, "\n  VPS Auto-Run dihentikan. Sampai jumpa! 👋"))
            break

        sesi_ke += 1

        # ── Cegah istirahat dobel ────────────────────────────────────────────
        # Kalau sesi tadi sudah istirahat sendiri (misal kena stop-loss), tidak
        # perlu istirahat tambahan lagi di sini — langsung lanjut sesi baru.
        if sudah_istirahat_internal:
            print(g(DIM, "  ⏭  Sesi tadi sudah istirahat (stop-loss) — lanjut langsung tanpa jeda tambahan.\n"))
        else:
            rest_countdown(rest_menit)



if __name__ == "__main__":
    RESTART_DELAY = int(CONFIG["restart_delay_detik"])   # detik tunggu sebelum restart setelah crash tak terduga
    MAX_RESTART_ATTEMPTS = int(CONFIG["max_restart_attempts"])  # batas restart berturut-turut sebelum menyerah
    restart_attempts = 0
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
            restart_attempts += 1

            if restart_attempts > MAX_RESTART_ATTEMPTS:
                print(g(RED, f"\n  💥 Bot crash tak terduga: {e}"))
                print(g(RED,
                    f"  🚫 Sudah {restart_attempts - 1}x restart berturut-turut tanpa berhasil — "
                    f"kemungkinan ada bug permanen (saldo habis, error API non-auth, dll)."
                ))
                print(g(RED, "  Script dihentikan total. Cek log di atas lalu perbaiki sebelum menjalankan ulang."))
                break

            print(g(RED, f"\n  💥 Bot crash tak terduga: {e}"))
            print(g(YELLOW,
                f"  🔄 Auto-restart dalam {RESTART_DELAY} detik... "
                f"(percobaan {restart_attempts}/{MAX_RESTART_ATTEMPTS} · Ctrl+C untuk batalkan)"
            ))
            try:
                time.sleep(RESTART_DELAY)
            except KeyboardInterrupt:
                print(g(YELLOW, "\n  ⏹  Restart dibatalkan."))
                break
            print(g(CYAN, "\n  ▶  Memulai ulang bot...\n"))
            # lanjut iterasi while → main() dipanggil lagi
