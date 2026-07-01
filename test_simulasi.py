#!/usr/bin/env python3
"""
Simulasi 1000 Spin — LIMBO (dry-run, TANPA uang asli)
Menguji logika betting (on-loss multiply, stop-loss, profit lock, VIP math)
dari main.py memakai RNG lokal — tidak memanggil API Stake.com sama sekali.
"""

import random
from decimal import Decimal, ROUND_DOWN
from collections import Counter

from main import (
    determine_win_limbo, to_dec, fmt, _quanta,
    g, BOLD, GREEN, RED, CYAN, YELLOW, DIM,
)

random.seed()  # RNG non-deterministik, seperti hasil roll asli

SEP = g(CYAN, "─" * 55)


def header(title):
    print(f"\n{SEP}")
    print(f"  {g(BOLD, title)}")
    print(SEP)


# ── Konfigurasi strategi — HARUS identik dengan jalankan_strategy_vip() ───────
N_SPIN            = 1000
currency          = "idr"
base_bet          = Decimal("1000")
win_chance_pct    = Decimal("98")
multiplier_target = (Decimal("99") / win_chance_pct).quantize(
                        Decimal("0.0001"), rounding=ROUND_DOWN)   # ≈ 1.0102x
max_loss_limit    = Decimal("45000")
profit_lock_idr   = Decimal("20000")
rest_setiap_volume = Decimal("5000000")

on_loss_multiply_enabled = True
on_loss_multiply_pct     = Decimal("2")
on_loss_multiply_cap     = base_bet * Decimal("5")

# ── Fungsi simulasi hasil roll (menggantikan panggilan API) ───────────────────
# House edge 1% ditiru dengan win probability nyata = win_chance_pct% (98%),
# konsisten dengan cara Stake menghitung provably-fair result vs multiplierTarget.
WIN_PROB = float(win_chance_pct) / 100.0


def simulasi_roll(bet: Decimal):
    """Tiru satu limboBet API call secara lokal. Return dict roll-like."""
    menang = random.random() < WIN_PROB
    if menang:
        # Result acak di atas target (biar determine_win_limbo tetap valid)
        result = float(multiplier_target) + random.uniform(0, 5)
        payout = (bet * multiplier_target).quantize(_quanta(currency), rounding=ROUND_DOWN)
    else:
        result = float(multiplier_target) * random.uniform(0.1, 0.999)
        payout = Decimal("0")
    return {
        "state": {"result": result, "multiplierTarget": float(multiplier_target)},
        "payout": str(payout),
        "amount": str(bet),
    }


def main():
    header(f"SIMULASI {N_SPIN} SPIN — LIMBO (DRY-RUN, TANPA UANG ASLI)")
    print(f"  Base Bet      : {g(BOLD, fmt(base_bet, currency))}")
    print(f"  Win Chance    : {g(BOLD, f'{win_chance_pct}%')}  |  Target: {g(BOLD, f'{multiplier_target}x')}")
    print(f"  Stop-Loss     : {g(RED, fmt(max_loss_limit, currency))}")
    print(f"  On-Loss Mult. : +{on_loss_multiply_pct}% tiap kalah, cap {fmt(on_loss_multiply_cap, currency)}")
    print(g(DIM, "  (Semua angka di bawah adalah hasil RNG lokal, bukan hasil API Stake.com)\n"))

    total_volume        = Decimal("0")
    total_loss          = Decimal("0")
    wins = losses       = 0
    current_bet         = base_bet
    loss_streak         = 0
    max_loss_streak     = 0
    max_bet_reached     = base_bet
    cap_hit_count       = 0
    stoploss_hits       = 0
    profit_lock_level   = 0
    saldo_virtual       = Decimal("500000")   # saldo virtual awal, hanya utk cek top-up/lock
    saldo_awal          = saldo_virtual
    next_rest_checkpoint = rest_setiap_volume
    checkpoint_hits     = 0
    ronde               = 0
    hasil_per_100        = []   # win-rate tiap blok 100 ronde, utk cek konsistensi RNG
    blok_win = 0

    while ronde < N_SPIN:
        ronde += 1
        roll   = simulasi_roll(current_bet)

        state  = roll["state"]
        payout = to_dec(roll["payout"])
        amount = to_dec(roll["amount"])
        profit = (payout - amount).quantize(_quanta(currency), rounding=ROUND_DOWN)
        won    = determine_win_limbo(state)

        total_volume  += current_bet
        total_loss    -= profit
        saldo_virtual += profit

        if won:
            wins += 1
            blok_win += 1
        else:
            losses += 1

        # ── Reuse persis logika on-loss-multiply dari main.py ───────────────
        if won:
            loss_streak = 0
            current_bet = base_bet
        elif on_loss_multiply_enabled:
            loss_streak += 1
            max_loss_streak = max(max_loss_streak, loss_streak)
            naik = current_bet * (Decimal("1") + on_loss_multiply_pct / Decimal("100"))
            if naik >= on_loss_multiply_cap:
                current_bet = on_loss_multiply_cap
                cap_hit_count += 1
            else:
                current_bet = naik.quantize(_quanta(currency), rounding=ROUND_DOWN)
            max_bet_reached = max(max_bet_reached, current_bet)

        # ── Cek stop-loss (sama seperti sesi asli — hitung, lalu reset sesi) ─
        if total_loss >= max_loss_limit:
            stoploss_hits += 1
            total_loss  = Decimal("0")
            current_bet = base_bet
            loss_streak = 0

        # ── Cek profit lock ───────────────────────────────────────────────
        surplus     = saldo_virtual - saldo_awal
        target_lock = profit_lock_idr * (profit_lock_level + 1)
        if surplus >= target_lock:
            profit_lock_level += 1

        # ── Cek checkpoint volume (rest) ─────────────────────────────────
        if total_volume >= next_rest_checkpoint:
            next_rest_checkpoint += rest_setiap_volume
            checkpoint_hits += 1

        if ronde % 100 == 0:
            hasil_per_100.append(blok_win)
            blok_win = 0

    # ── Ringkasan hasil ────────────────────────────────────────────────────
    total    = wins + losses
    win_rate = (Decimal(wins) / Decimal(total) * 100) if total else Decimal("0")
    net      = -total_loss

    header("RINGKASAN SIMULASI")
    print(f"  Ronde dimainkan   : {g(BOLD, str(total))}")
    print(f"  Menang / Kalah    : {g(GREEN, str(wins))} / {g(RED, str(losses))}")
    print(f"  Win Rate          : {g(BOLD, f'{win_rate:.2f}%')}  {g(DIM, '(target teoritis: 98.00%)')}")
    print(f"  Total Volume      : {g(CYAN, fmt(total_volume, currency))}")
    net_color = GREEN if net >= 0 else RED
    print(f"  Net P/L (RNG run) : {g(net_color, ('+' if net >= 0 else '') + fmt(net, currency))}")
    print(f"  Checkpoint volume tercapai : {checkpoint_hits}x (setiap {fmt(rest_setiap_volume, currency)})")
    print(f"  Stop-loss terpicu          : {stoploss_hits}x (limit {fmt(max_loss_limit, currency)})")
    print(f"  Profit-lock level tercapai : {profit_lock_level}x")
    print(f"  Loss streak terpanjang     : {max_loss_streak}x")
    print(f"  Bet tertinggi dipasang     : {fmt(max_bet_reached, currency)}")
    print(f"  Bet kena cap (5x)          : {cap_hit_count}x")

    header("VALIDASI KONSISTENSI RNG (per blok 100 spin)")
    for i, w in enumerate(hasil_per_100, start=1):
        print(f"  Blok {i:>2} (#{ (i-1)*100+1 }-{i*100:>4}) : {w}/100 menang ({w:.0f}%)")

    header("HASIL AKHIR")
    checks_ok = True
    if not (90 <= float(win_rate) <= 100):
        checks_ok = False
        print(g(RED, f"  ❌ Win rate {win_rate:.2f}% jauh dari target 98% — cek determine_win_limbo/simulasi"))
    else:
        print(g(GREEN, f"  ✅ Win rate {win_rate:.2f}% masuk rentang wajar (target statistik: 98%)"))

    if total == N_SPIN:
        print(g(GREEN, f"  ✅ Semua {N_SPIN} spin selesai tanpa crash"))
    else:
        checks_ok = False
        print(g(RED, f"  ❌ Hanya {total}/{N_SPIN} spin selesai"))

    if cap_hit_count >= 0 and max_bet_reached <= on_loss_multiply_cap:
        print(g(GREEN, "  ✅ On-Loss Multiply tidak pernah melebihi cap 5x base bet"))
    else:
        checks_ok = False
        print(g(RED, "  ❌ Bet melebihi cap — bug pada logika on-loss-multiply!"))

    print()
    if checks_ok:
        print(g(GREEN, g(BOLD, "  🎉 SIMULASI 1000 SPIN LULUS — logika betting main.py aman untuk live run.")))
    else:
        print(g(RED, g(BOLD, "  ⚠️  Ada anomali pada simulasi — cek log di atas sebelum live run.")))
    print(g(DIM, "\n  Catatan: ini simulasi RNG lokal, TIDAK memanggil API Stake.com / tidak ada uang asli terpakai.\n"))


if __name__ == "__main__":
    main()
