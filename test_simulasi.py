#!/usr/bin/env python3
"""
Simulasi Spin — LIMBO (dry-run, TANPA uang asli)
Menguji logika betting (on-loss multiply, stop-loss, profit lock, VIP math)
dari main.py memakai RNG lokal — tidak memanggil API Stake.com sama sekali.

Simulasi dijalankan dengan saldo awal tertentu (default Rp 200.000) dan
berhenti otomatis kalau saldo sudah tidak cukup untuk bet berikutnya,
persis seperti yang akan terjadi di akun asli.
"""

import sys
import random
from decimal import Decimal, ROUND_DOWN

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
N_SPIN_MAX        = 1000                      # batas maksimum spin per run
SALDO_AWAL        = Decimal(sys.argv[1]) if len(sys.argv) > 1 else Decimal("200000")
# Argumen ke-2 (opsional): jumlah kekalahan beruntun yang DIPAKSA di awal run,
# untuk menguji skenario terburuk (worst-case) — bukan RNG normal.
FORCE_LOSSES      = int(sys.argv[2]) if len(sys.argv) > 2 else 0
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

WIN_PROB = float(win_chance_pct) / 100.0   # probabilitas menang nyata = win_chance_pct%


def simulasi_roll(bet: Decimal, force_lose: bool = False):
    """Tiru satu limboBet API call secara lokal. Return dict roll-like.

    force_lose=True memaksa hasil kalah (dipakai utk skenario worst-case),
    bukan RNG normal — untuk menguji ketahanan saldo/bet di kondisi apes.
    """
    menang = (not force_lose) and (random.random() < WIN_PROB)
    if menang:
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
    header(f"SIMULASI DRY-RUN — LIMBO (SALDO AWAL {fmt(SALDO_AWAL, currency)})")
    print(f"  Base Bet      : {g(BOLD, fmt(base_bet, currency))}")
    print(f"  Win Chance    : {g(BOLD, f'{win_chance_pct}%')}  |  Target: {g(BOLD, f'{multiplier_target}x')}")
    print(f"  Stop-Loss     : {g(RED, fmt(max_loss_limit, currency))}  {g(DIM, '(sesi berhenti sementara lalu reset, bukan berhenti total)')}")
    print(f"  On-Loss Mult. : +{on_loss_multiply_pct}% tiap kalah, cap {fmt(on_loss_multiply_cap, currency)}")
    print(f"  Batas spin    : {g(BOLD, str(N_SPIN_MAX))}  {g(DIM, '(atau berhenti lebih awal kalau saldo habis)')}")
    print(g(DIM, "  (Semua angka di bawah adalah hasil RNG lokal, bukan hasil API Stake.com)\n"))

    saldo               = SALDO_AWAL
    total_volume        = Decimal("0")
    total_loss          = Decimal("0")           # loss berjalan dalam 1 sesi (di-reset saat stop-loss kena)
    wins = losses        = 0
    current_bet          = base_bet
    loss_streak          = 0
    max_loss_streak      = 0
    max_bet_reached      = base_bet
    cap_hit_count        = 0
    stoploss_hits        = 0
    profit_lock_level    = 0
    saldo_acuan_lock     = saldo                  # acuan profit-lock, direset tiap sesi baru
    next_rest_checkpoint = rest_setiap_volume
    checkpoint_hits      = 0
    ronde                = 0
    saldo_habis          = False
    sesi_log             = []                     # ringkasan tiap sesi (antar stop-loss)
    sesi_wins = sesi_losses = 0
    sesi_ke               = 1
    worst_case_log        = []                    # progres bet per kalah, khusus mode worst-case

    if FORCE_LOSSES > 0:
        header(f"MODE WORST-CASE — {FORCE_LOSSES}x KEKALAHAN BERUNTUN DIPAKSA DI AWAL")
        print(g(YELLOW, f"  ⚠️  {FORCE_LOSSES} spin pertama DIPAKSA kalah (bukan RNG) untuk stress-test.\n"))

    while ronde < N_SPIN_MAX:
        # ── Cek saldo cukup untuk bet berikutnya ────────────────────────────
        if saldo < current_bet:
            saldo_habis = True
            break

        ronde += 1
        force_lose = ronde <= FORCE_LOSSES
        roll   = simulasi_roll(current_bet, force_lose=force_lose)

        state  = roll["state"]
        payout = to_dec(roll["payout"])
        amount = to_dec(roll["amount"])
        profit = (payout - amount).quantize(_quanta(currency), rounding=ROUND_DOWN)
        won    = determine_win_limbo(state)

        total_volume += current_bet
        total_loss   -= profit
        saldo        += profit

        if won:
            wins += 1
            sesi_wins += 1
        else:
            losses += 1
            sesi_losses += 1

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

        if force_lose:
            worst_case_log.append({
                "kalah_ke": ronde, "bet_baru": current_bet, "saldo": saldo,
            })

        # ── Cek stop-loss → tutup sesi ini, catat ringkasan, mulai sesi baru ─
        if total_loss >= max_loss_limit:
            stoploss_hits += 1
            sesi_log.append({
                "sesi": sesi_ke, "wins": sesi_wins, "losses": sesi_losses,
                "loss_idr": total_loss, "saldo_akhir": saldo,
            })
            sesi_ke += 1
            sesi_wins = sesi_losses = 0
            total_loss  = Decimal("0")
            current_bet = base_bet
            loss_streak = 0

        # ── Cek profit lock ───────────────────────────────────────────────
        surplus     = saldo - saldo_acuan_lock
        target_lock = profit_lock_idr * (profit_lock_level + 1)
        if surplus >= target_lock:
            profit_lock_level += 1

        # ── Cek checkpoint volume (rest) ─────────────────────────────────
        if total_volume >= next_rest_checkpoint:
            next_rest_checkpoint += rest_setiap_volume
            checkpoint_hits += 1

    # Tutup sesi terakhir yang belum kena stop-loss (kalau ada aktivitas)
    if sesi_wins + sesi_losses > 0:
        sesi_log.append({
            "sesi": sesi_ke, "wins": sesi_wins, "losses": sesi_losses,
            "loss_idr": total_loss, "saldo_akhir": saldo,
        })

    # ── Ringkasan hasil ────────────────────────────────────────────────────
    total    = wins + losses
    win_rate = (Decimal(wins) / Decimal(total) * 100) if total else Decimal("0")
    net      = saldo - SALDO_AWAL

    if worst_case_log:
        header(f"DETAIL WORST-CASE — PROGRES {FORCE_LOSSES}x KEKALAHAN BERUNTUN")
        print(f"  {'Kalah ke-':<12}{'Bet Baru':<16}{'Saldo Setelahnya':<18}")
        for w in worst_case_log:
            print(f"  {w['kalah_ke']:<12}{fmt(w['bet_baru'], currency):<16}{fmt(w['saldo'], currency):<18}")
        habis_terpakai = SALDO_AWAL - worst_case_log[-1]["saldo"]
        print(g(YELLOW, f"\n  💸 Total habis terpakai selama {FORCE_LOSSES}x kalah beruntun: {fmt(habis_terpakai, currency)}"))
        if worst_case_log[-1]["bet_baru"] >= on_loss_multiply_cap:
            print(g(RED, f"  🛑 Bet sudah mentok di cap {fmt(on_loss_multiply_cap, currency)} sebelum {FORCE_LOSSES}x kalah selesai."))

    header("RINCIAN PER SESI (antar stop-loss)")
    print(f"  {'Sesi':<6}{'Menang':<10}{'Kalah':<10}{'Loss Sesi':<16}{'Saldo Akhir':<16}")
    for s in sesi_log:
        loss_str = fmt(s["loss_idr"], currency)
        saldo_str = fmt(s["saldo_akhir"], currency)
        print(f"  {s['sesi']:<6}{s['wins']:<10}{s['losses']:<10}{loss_str:<16}{saldo_str:<16}")

    header("RINGKASAN TOTAL")
    print(f"  Saldo awal        : {g(BOLD, fmt(SALDO_AWAL, currency))}")
    print(f"  Saldo akhir       : {g(BOLD, fmt(saldo, currency))}")
    print(f"  Ronde dimainkan   : {g(BOLD, str(total))} {g(DIM, f'dari maks {N_SPIN_MAX}')}")
    print(f"  Menang            : {g(GREEN, str(wins))} kali")
    print(f"  Kalah             : {g(RED, str(losses))} kali")
    print(f"  Win Rate          : {g(BOLD, f'{win_rate:.2f}%')}  {g(DIM, '(target teoritis: 98.00%)')}")
    print(f"  Total Volume      : {g(CYAN, fmt(total_volume, currency))}")
    net_color = GREEN if net >= 0 else RED
    print(f"  Net P/L           : {g(net_color, ('+' if net >= 0 else '') + fmt(net, currency))}")
    print(f"  Jumlah sesi       : {len(sesi_log)}  {g(DIM, f'(stop-loss terpicu {stoploss_hits}x)')}")
    print(f"  Profit-lock level : {profit_lock_level}x")
    print(f"  Loss streak terpanjang : {max_loss_streak}x")
    print(f"  Bet tertinggi dipasang : {fmt(max_bet_reached, currency)}")
    print(f"  Bet kena cap (5x)      : {cap_hit_count}x")

    header("HASIL AKHIR")
    if saldo_habis:
        print(g(RED, f"  ⚠️  Saldo HABIS setelah {total} spin — sisa {fmt(saldo, currency)} tidak cukup untuk bet {fmt(current_bet, currency)}."))
    elif total == N_SPIN_MAX:
        print(g(GREEN, f"  ✅ Saldo {fmt(SALDO_AWAL, currency)} berhasil bertahan sampai {N_SPIN_MAX} spin."))

    if not (90 <= float(win_rate) <= 100) and total > 0:
        print(g(RED, f"  ❌ Win rate {win_rate:.2f}% jauh dari target 98% — cek logika simulasi"))
    elif total > 0:
        print(g(GREEN, f"  ✅ Win rate {win_rate:.2f}% masuk rentang wajar (target statistik: 98%)"))

    if max_bet_reached <= on_loss_multiply_cap:
        print(g(GREEN, "  ✅ On-Loss Multiply tidak pernah melebihi cap 5x base bet"))
    else:
        print(g(RED, "  ❌ Bet melebihi cap — bug pada logika on-loss-multiply!"))

    print(g(DIM, "\n  Catatan: ini simulasi RNG lokal, TIDAK memanggil API Stake.com / tidak ada uang asli terpakai.\n"))


if __name__ == "__main__":
    main()
