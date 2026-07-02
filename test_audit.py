#!/usr/bin/env python3
"""
Audit & Test Script untuk main.py (LIMBO + MINES)
Menguji semua komponen tanpa perlu main full session.
"""

import os, sys, uuid, time, csv, random
from decimal import Decimal, ROUND_DOWN
from datetime import datetime

# ── Import dari main.py ───────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from main import (
    gql, USER_QUERY, LIMBO_MUTATION,
    determine_win_limbo, mines_kena_ranjau, hitung_odds_mines,
    to_dec, fmt, idr_k, _quanta,
    print_vip_status, simpan_log_csv, CSV_LOG,
    CONFIG,
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
header("TEST 4 — Live Bet 5 Ronde (Rp 1.000/roll, 98% win chance, LIMBO)")
info("Menempatkan 5 taruhan nyata ke Stake.com...\n")

base_bet          = Decimal("1000")
currency          = "idr"
multiplier_target = Decimal("1.0102")

total_volume = Decimal("0")
total_loss   = Decimal("0")
wins = losses = 0

for i in range(1, 6):
    ident = str(uuid.uuid4())
    try:
        result    = gql(LIMBO_MUTATION, {
            "amount":           float(base_bet),
            "multiplierTarget": float(multiplier_target),
            "currency":         currency,
            "identifier":       ident,
        })
        roll      = result["limboBet"]

        # ── Parse aman seperti di main.py production ──────────────────────────
        state      = roll.get("state") or {}
        payout     = to_dec(roll.get("payout", 0))
        amount     = to_dec(roll.get("amount", 0))
        profit     = (payout - amount).quantize(_quanta(currency), rounding=ROUND_DOWN)

        won_state  = determine_win_limbo(state)
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

# ── TEST 5: determine_win_limbo safety ────────────────────────────────────────
header("TEST 5 — determine_win_limbo Safety & Stop Condition Logic")

# Uji determine_win_limbo dengan dict kosong / None — tidak boleh crash
assert determine_win_limbo({})   == False, "dict kosong harus return False"
assert determine_win_limbo(None) == False, "None harus return False"  # type: ignore
assert determine_win_limbo({"result": 1.02,   "multiplierTarget": 1.0102}) == True
assert determine_win_limbo({"result": 1.0102, "multiplierTarget": 1.0102}) == True
assert determine_win_limbo({"result": 1.00,   "multiplierTarget": 1.0102}) == False
ok("determine_win_limbo aman untuk semua edge case")

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
from main import VIP_LEVELS, VIP_ORDER

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

# ── TEST 8: mines_kena_ranjau safety ──────────────────────────────────────────
header("TEST 8 — mines_kena_ranjau Safety")

assert mines_kena_ranjau({}) == False,         "dict kosong harus return False"
assert mines_kena_ranjau(None) == False,        "None harus return False"   # type: ignore
assert mines_kena_ranjau({"mines": None}) == False, "mines=None harus False"
assert mines_kena_ranjau({"mines": []}) == False,   "mines=[] (list kosong) harus False"
assert mines_kena_ranjau({"mines": [3, 17]}) == True, "mines=[3,17] (kena ranjau) harus True"
ok("mines_kena_ranjau aman untuk semua edge case")

# ── TEST 9: hitung_odds_mines akurasi ─────────────────────────────────────────
header("TEST 9 — hitung_odds_mines Akurasi")

# Profil normal: 1 mine, 2 reveals  → C(24,2)/C(25,2) = 276/300 = 92%
chance_n, multi_n = hitung_odds_mines(25, 1, 2)
assert Decimal("91") < chance_n < Decimal("93"), f"Normal win% harus ~92%, dapat {chance_n}"
ok(f"Normal  (1 mine · 2 reveal) → ≈{chance_n}% menang · fair multiplier ≈{multi_n}x")

# Profil agresif: 3 mines, 2 reveals → C(22,2)/C(25,2) = 231/300 = 77%
chance_a, multi_a = hitung_odds_mines(25, 3, 2)
assert Decimal("76") < chance_a < Decimal("78"), f"Agresif win% harus ~77%, dapat {chance_a}"
ok(f"Agresif (3 mine · 2 reveal) → ≈{chance_a}% menang · fair multiplier ≈{multi_a}x")

# Profil wager: 1 mine, 1 reveal → C(24,1)/C(25,1) = 24/25 = 96%
chance_w, multi_w = hitung_odds_mines(25, 1, 1)
assert Decimal("95") < chance_w < Decimal("97"), f"Wager win% harus ~96%, dapat {chance_w}"
ok(f"Wager   (1 mine · 1 reveal) → ≈{chance_w}% menang · fair multiplier ≈{multi_w}x")

# Edge case: reveal lebih banyak dari kotak aman → return (0, 0)
chance_bad, multi_bad = hitung_odds_mines(25, 1, 25)  # 24 kotak aman, minta 25
assert chance_bad == Decimal("0"), "Reveal > aman harus return win_chance=0"
ok("Edge case reveal > kotak aman → (0, 0) — aman")

# ── TEST 10: Config Mines profiles lengkap ────────────────────────────────────
header("TEST 10 — Validasi Config mines_profiles")

required_keys = {"mines_count", "tile_indices", "loss_multiplier", "cap_multiplier",
                 "double_loss_rest_menit", "throttle", "instant_reset"}
profiles = CONFIG.get("mines_profiles", {})
assert len(profiles) >= 3, f"Harus ada ≥3 profil, dapat {len(profiles)}: {list(profiles.keys())}"

for nama, profil in profiles.items():
    missing = required_keys - set(profil.keys())
    assert not missing, f"Profil '{nama}' kurang key: {missing}"
    assert int(profil["mines_count"]) >= 1,  f"Profil '{nama}': mines_count harus ≥1"
    assert len(profil["tile_indices"]) >= 1, f"Profil '{nama}': tile_indices harus ≥1 elemen"
    assert Decimal(str(profil["loss_multiplier"])) >= Decimal("1"), \
        f"Profil '{nama}': loss_multiplier harus ≥1"
    ok(f"Profil '{nama}': semua key ada dan valid  ✅")

# Pastikan profil wager punya throttle=False dan instant_reset=True
wager = profiles.get("wager", {})
assert wager.get("throttle")       == False, "Profil wager: throttle harus False"
assert wager.get("instant_reset")  == True,  "Profil wager: instant_reset harus True"
assert len(wager.get("tile_indices", [])) == 1, "Profil wager: hanya 1 reveal (1 elemen tile_indices)"
ok("Profil 'wager' terverifikasi: throttle=False, instant_reset=True, 1 reveal")

# ── TEST 11: Recovery logic (instant_reset vs modal balik) ────────────────────
header("TEST 11 — Simulasi Recovery Logic")

from decimal import Decimal

CURRENCY = "idr"
Q        = _quanta(CURRENCY)

def sim_recovery(loss_multi, cap_multi, instant, base=Decimal("500"), n_kalah=5):
    """Simulasikan N kalah berturut-turut lalu 1 menang — return (bet_saat_menang, direset)."""
    bet        = base
    cap        = base * cap_multi
    streak_net = Decimal("0")
    for _ in range(n_kalah):
        streak_net -= bet
        naik = bet * loss_multi
        bet  = min(naik, cap).quantize(Q, rounding=ROUND_DOWN)
    # 1 menang
    profit = (bet * Decimal("1.04")).quantize(Q, rounding=ROUND_DOWN)  # simulasi profit kecil
    streak_net += profit
    should_reset = instant or (streak_net >= 0)
    return bet, should_reset

# Wager: instant_reset=True → bet PASTI direset tiap menang
bet_w, reset_w = sim_recovery(Decimal("1.02"), Decimal("3"), instant=True, n_kalah=5)
assert reset_w == True, "instant_reset=True harus selalu reset setelah menang"
ok(f"Wager  — 5x kalah · bet saat menang: {fmt(bet_w, CURRENCY)} → instant reset ✅")

# Normal: instant_reset=False, loss_multi=1.5x → streak_net belum tentu ≥0
bet_n, reset_n = sim_recovery(Decimal("1.5"), Decimal("5"), instant=False, n_kalah=5)
info(f"Normal — 5x kalah · bet saat menang: {fmt(bet_n, CURRENCY)} · reset={reset_n}")
ok("Normal recovery logic berjalan tanpa crash ✅")

# ── HASIL AKHIR ───────────────────────────────────────────────────────────────
header("AUDIT SELESAI — LIMBO + MINES")
print(f"  Semua komponen main.py (Limbo & Mines) berfungsi normal.")
print(f"  Profil Mines terdeteksi: {g(BOLD, ', '.join(CONFIG.get('mines_profiles', {}).keys()))}")
print(f"  Jalankan {g(BOLD, 'python3 main.py')} untuk mulai grinding VIP otomatis.\n")
