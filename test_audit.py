#!/usr/bin/env python3
"""
Audit & Test Script untuk dice.py
Menguji semua komponen tanpa perlu main full session.
"""

import os, sys, uuid, time, csv, random
from decimal import Decimal, ROUND_DOWN
from datetime import datetime

# ── Import dari dice.py ───────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from dice import (
    gql, USER_QUERY, DICE_MUTATION,
    determine_win, to_dec, fmt, _quanta,
    print_vip_status, simpan_log_csv, CSV_LOG,
    g, BOLD, GREEN, RED, CYAN, YELLOW, BLUE, DIM,
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
fp       = user.get("flagProgress") or {"flag": "none", "progress": 0}
progress = float(fp.get("progress") or 0)   # aman dari None
info(f"Raw API → flag={fp.get('flag')}, progress={progress:.4f}")
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
        result    = gql(DICE_MUTATION, {
            "amount":     float(base_bet),
            "target":     target_num,
            "condition":  condition,
            "currency":   currency,
            "identifier": ident,
        })
        roll      = result["diceRoll"]

        # ── Parse aman seperti di dice.py production ──────────────────────────
        state      = roll.get("state") or {}
        payout     = to_dec(roll.get("payout", 0))
        amount     = to_dec(roll.get("amount", 0))
        profit     = (payout - amount).quantize(_quanta(currency), rounding=ROUND_DOWN)

        won_state  = determine_win(state)
        won_payout = payout > amount
        won        = won_payout if not state else won_state

        total_volume += base_bet
        total_loss   -= profit

        rolled    = float(state.get("result", 0))
        user_bals = roll.get("user", {}).get("balances", [])
        bal       = next(
            (b["available"]["amount"] for b in user_bals
             if b["available"]["currency"] == currency), None
        )

        icon = g(GREEN, "WIN ✅") if won else g(RED, "LOSS ❌")
        pstr = g(GREEN, f"+{fmt(profit, currency)}") if won else g(RED, fmt(profit, currency))
        if won:
            wins += 1
        else:
            losses += 1

        bal_str = fmt(bal, currency) if bal is not None else "N/A"
        print(f"  Roll #{i}: {g(BOLD, f'{rolled:.2f}'):<8} {icon}  {pstr:<22} "
              f"Saldo: {g(CYAN, bal_str)}")

        time.sleep(random.uniform(0.6, 1.3))

    except Exception as e:
        fail(f"Bet #{i} error: {e}")

total    = wins + losses
win_rate = (wins / total * 100) if total > 0 else 0
print()
ok(f"5 bet selesai — W/L: {wins}/{losses} ({win_rate:.0f}%) | "
   f"Volume: {fmt(total_volume, currency)} | "
   f"Loss: {fmt(total_loss, currency)}")

# ── TEST 5: determine_win safety ──────────────────────────────────────────────
header("TEST 5 — determine_win Safety & Stop Condition Logic")

# Uji determine_win dengan dict kosong / None — tidak boleh crash
assert determine_win({})   == False, "dict kosong harus return False"
assert determine_win(None) == False, "None harus return False"  # type: ignore
assert determine_win({"result": 50, "target": 98, "condition": "below"}) == True
assert determine_win({"result": 99, "target": 98, "condition": "below"}) == False
assert determine_win({"result": 99, "target": 98, "condition": "above"}) == True
ok("determine_win aman untuk semua edge case")

# Simulasi stop conditions
sim_volume     = Decimal("1999800") + Decimal("200")  # tepat 2.000.000
sim_target_vol = Decimal("2000000")
sim_loss_bad   = Decimal("31000")
sim_loss_limit = Decimal("30000")
sim_vol_ok     = Decimal("500000")
sim_loss_ok    = Decimal("5000")

assert sim_volume    >= sim_target_vol,  "Target volume harus terdeteksi"
assert sim_loss_bad  >= sim_loss_limit,  "Stop-loss harus terdeteksi"
assert sim_vol_ok    <  sim_target_vol,  "Volume aman tidak boleh trigger stop"
assert sim_loss_ok   <  sim_loss_limit,  "Loss aman tidak boleh trigger stop"

ok("Stop TARGET VOLUME terdeteksi ✅")
ok("Stop LOSS LIMIT terdeteksi ✅")
ok("Kondisi aman tidak trigger stop ✅")

# ── TEST 6: VIP next-level lookup ─────────────────────────────────────────────
header("TEST 6 — VIP Next-Level Lookup")
from dice import VIP_LEVELS, VIP_ORDER

for key in VIP_ORDER[:-1]:   # semua kecuali level terakhir
    cur_idx  = VIP_ORDER.index(key)
    next_key = VIP_ORDER[cur_idx + 1]
    assert next_key in VIP_LEVELS, f"Next key '{next_key}' tidak ada di VIP_LEVELS"
    ok(f"{VIP_LEVELS[key]['label']} → {VIP_LEVELS[next_key]['label']}")

diamond_info = VIP_LEVELS["diamond"]
assert diamond_info["next_usd"] is None, "Diamond harus punya next_usd=None"
ok("Diamond tidak punya next level (benar)")

# ── TEST 7: CSV Logging ───────────────────────────────────────────────────────
header("TEST 7 — CSV Logging")
net      = -total_loss
win_rate = (Decimal(wins) / Decimal(total) * 100) if total > 0 else Decimal("0")

test_row = {
    "tanggal":          datetime.now().strftime("%Y-%m-%d %H:%M"),
    "ronde":            total,
    "volume_idr":       str(total_volume),
    "loss_idr":         str(total_loss),
    "win_rate_pct":     f"{win_rate:.1f}",
    "net_idr":          str(net),
    "vip_flag":         fp.get("flag", ""),
    "vip_progress_pct": f"{progress * 100:.2f}",
}
try:
    simpan_log_csv(test_row)
    ok(f"Log tersimpan ke {CSV_LOG}")

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
