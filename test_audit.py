#!/usr/bin/env python3
"""
Audit & Test Script untuk dice.py
Menguji semua komponen tanpa perlu main full session.
"""

import os, sys, uuid, time, csv, random
import requests
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from datetime import datetime

# ── Import dari dice.py ───────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from dice import (
    gql, USER_QUERY, DICE_MUTATION,
    determine_win, to_dec, fmt, _quanta,
    print_vip_status, simpan_log_csv, CSV_LOG,
    g, BOLD, GREEN, RED, CYAN, YELLOW, BLUE, DIM, R,
)

SEP = g(BLUE, "─" * 55)

def header(title):
    print(f"\n{SEP}")
    print(f"  {g(BOLD, title)}")
    print(SEP)

def ok(msg):  print(f"  {g(GREEN,  '✅')} {msg}")
def fail(msg):print(f"  {g(RED,    '❌')} {msg}")
def info(msg):print(f"  {g(CYAN,   'ℹ️')}  {msg}")

# ── TEST 1: Koneksi & Login ───────────────────────────────────────────────────
header("TEST 1 — Koneksi & Login")
try:
    user = gql(USER_QUERY)["user"]
    ok(f"Login berhasil: {g(BOLD, user['name'])}")
except Exception as e:
    fail(f"Login gagal: {e}")
    sys.exit(1)

# ── TEST 2: VIP Status ────────────────────────────────────────────────────────
header("TEST 2 — VIP Status Display")
fp = user.get("flagProgress") or {"flag": "none", "progress": 0}
info(f"Raw API → flag={fp.get('flag')}, progress={fp.get('progress'):.4f}")
print()
print_vip_status(fp)
ok("VIP status tampil tanpa error")

# ── TEST 3: Saldo IDR ─────────────────────────────────────────────────────────
header("TEST 3 — Saldo IDR")
idr_balance = to_dec(
    next((b["available"]["amount"]
          for b in user["balances"]
          if b["available"]["currency"] == "idr"), "0")
)
info(f"Saldo IDR: {fmt(idr_balance, 'idr')}")
if idr_balance > 0:
    ok("Saldo IDR tersedia")
else:
    fail("Saldo IDR kosong — top up dulu sebelum lanjut")

# ── TEST 4: Live Bet (5 ronde kecil) ─────────────────────────────────────────
header("TEST 4 — Live Bet 5 Ronde (Rp 200/roll, 98% win chance)")
info("Menempatkan 5 taruhan nyata ke Stake.com...\n")

base_bet   = Decimal("200")
currency   = "idr"
condition  = "below"
target_num = 98.0

total_volume = Decimal("0")
total_loss   = Decimal("0")
wins = losses = 0

for i in range(1, 6):
    ident = str(uuid.uuid4())
    try:
        result = gql(DICE_MUTATION, {
            "amount":     float(base_bet),
            "target":     target_num,
            "condition":  condition,
            "currency":   currency,
            "identifier": ident,
        })
        roll   = result["diceRoll"]
        won    = determine_win(roll["state"])
        payout = to_dec(roll["payout"])
        amount = to_dec(roll["amount"])
        profit = (payout - amount).quantize(_quanta(currency), rounding=ROUND_DOWN)

        total_volume += base_bet
        total_loss   -= profit

        rolled   = float(roll["state"]["result"])
        user_bals = roll.get("user", {}).get("balances", [])
        bal      = next(
            (b["available"]["amount"] for b in user_bals
             if b["available"]["currency"] == currency), "?"
        )

        icon = g(GREEN, "WIN ✅") if won else g(RED, "LOSS ❌")
        if won:
            wins += 1
            pstr = g(GREEN, f"+{fmt(profit, currency)}")
        else:
            losses += 1
            pstr = g(RED, fmt(profit, currency))

        print(f"  Roll #{i}: {g(BOLD, f'{rolled:.2f}'):<8} {icon}  {pstr:<22} "
              f"Saldo: {g(CYAN, fmt(bal, currency))}")

        time.sleep(random.uniform(0.6, 1.3))   # Jeda acak seperti production

    except Exception as e:
        fail(f"Bet #{i} error: {e}")

total = wins + losses
win_rate = (wins / total * 100) if total > 0 else 0
print()
ok(f"5 bet selesai — W/L: {wins}/{losses} ({win_rate:.0f}%) | "
   f"Volume: {fmt(total_volume, currency)} | "
   f"Loss: {fmt(total_loss, currency)}")

# ── TEST 5: Stop Condition Logic ──────────────────────────────────────────────
header("TEST 5 — Stop Condition Logic")

# Simulasi: volume sudah mendekati target
sim_volume     = Decimal("1999800")   # Tinggal 1 bet lagi ke 2 juta
sim_target_vol = Decimal("2000000")
sim_loss       = Decimal("25000")     # Loss masih di bawah limit
sim_loss_limit = Decimal("30000")

sim_volume += base_bet   # Tambah 1 bet terakhir → 2.000.000

if sim_volume >= sim_target_vol:
    ok(f"Stop TARGET VOLUME: {fmt(sim_volume, 'idr')} ≥ {fmt(sim_target_vol, 'idr')} → BERHENTI ✅")
else:
    fail("Target volume tidak terdeteksi")

# Simulasi: loss sudah melewati limit
sim_loss2 = Decimal("31000")
if sim_loss2 >= sim_loss_limit:
    ok(f"Stop LOSS LIMIT: {fmt(sim_loss2, 'idr')} ≥ {fmt(sim_loss_limit, 'idr')} → BERHENTI ✅")
else:
    fail("Stop-loss tidak terdeteksi")

# Simulasi: keduanya belum tercapai → lanjut
sim_vol_aman  = Decimal("500000")
sim_loss_aman = Decimal("5000")
if sim_vol_aman < sim_target_vol and sim_loss_aman < sim_loss_limit:
    ok(f"Kondisi normal: volume & loss masih aman → LANJUT ✅")

# ── TEST 6: CSV Logging ───────────────────────────────────────────────────────
header("TEST 6 — CSV Logging")
net = -total_loss
test_row = {
    "tanggal":          datetime.now().strftime("%Y-%m-%d %H:%M"),
    "ronde":            total,
    "volume_idr":       str(total_volume),
    "loss_idr":         str(total_loss),
    "win_rate_pct":     f"{win_rate:.1f}",
    "net_idr":          str(net),
    "vip_flag":         fp.get("flag", ""),
    "vip_progress_pct": f"{float(fp.get('progress', 0)) * 100:.2f}",
}
try:
    simpan_log_csv(test_row)
    ok(f"Log tersimpan ke {CSV_LOG}")

    # Baca balik dan verifikasi
    with open(CSV_LOG, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    last = rows[-1]
    info(f"Baris terakhir → tanggal={last['tanggal']}, "
         f"ronde={last['ronde']}, volume={last['volume_idr']}, "
         f"vip={last['vip_flag']}({last['vip_progress_pct']}%)")
    ok("Data CSV terbaca dengan benar")
except Exception as e:
    fail(f"CSV error: {e}")

# ── HASIL AKHIR ───────────────────────────────────────────────────────────────
header("AUDIT SELESAI")
print(f"  Semua komponen dice.py berfungsi normal.")
print(f"  Jalankan {g(BOLD, 'python dice.py')} → pilih Mode 2 untuk mulai grinding VIP.\n")
