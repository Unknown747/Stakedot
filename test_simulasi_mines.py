#!/usr/bin/env python3
"""
Simulasi Dry-Run — MINES (tanpa uang asli)
Menguji logika recovery, stop-loss, dan estimasi wager dari jalankan_strategy_mines_vip()
menggunakan RNG lokal — tidak memanggil API Stake.com sama sekali.

Cara pakai:
  python3 test_simulasi_mines.py                         # profil default (wager, saldo 200k)
  python3 test_simulasi_mines.py 500000 wager            # saldo 500k, profil wager
  python3 test_simulasi_mines.py 200000 normal 15        # saldo 200k, profil normal, 15 kalah dipaksa
  python3 test_simulasi_mines.py 200000 agresif 10
"""

import sys
import random
from decimal import Decimal, ROUND_DOWN
from math import comb

from main import (
    hitung_odds_mines, to_dec, fmt, idr_k, _quanta,
    g, BOLD, GREEN, RED, CYAN, YELLOW, DIM, WHITE,
    CONFIG,
)

random.seed()

SEP = g(CYAN, "─" * 58)


def header(title):
    print(f"\n{SEP}")
    print(f"  {g(BOLD, title)}")
    print(SEP)


# ── Muat profil dari config ────────────────────────────────────────────────────
PROFILE_NAME  = sys.argv[2] if len(sys.argv) > 2 else "wager"
SALDO_AWAL    = Decimal(sys.argv[1]) if len(sys.argv) > 1 else Decimal("200000")
FORCE_LOSSES  = int(sys.argv[3]) if len(sys.argv) > 3 else 0
N_SPIN_MAX    = 2000

_profiles = CONFIG["mines_profiles"]
if PROFILE_NAME not in _profiles:
    print(g(RED, f"❌ Profil '{PROFILE_NAME}' tidak ada. Pilihan: {list(_profiles.keys())}"))
    sys.exit(1)

mines_profile       = _profiles[PROFILE_NAME]
mines_count         = int(mines_profile["mines_count"])
mines_fields        = [int(x) for x in mines_profile["tile_indices"]]
loss_multiplier     = Decimal(str(mines_profile["loss_multiplier"]))
currency            = CONFIG["currency"]
base_bet            = Decimal(str(CONFIG["base_bet"]))
mines_cap           = base_bet * Decimal(str(mines_profile["cap_multiplier"]))
double_loss_menit   = int(mines_profile.get("double_loss_rest_menit", 1))
throttle            = bool(mines_profile.get("throttle", True))
instant_reset       = bool(mines_profile.get("instant_reset", False))
max_loss_limit      = Decimal(str(CONFIG["max_loss_limit"]))
profit_lock_idr     = Decimal(str(CONFIG["profit_lock_idr"]))
rest_setiap_volume  = Decimal(str(CONFIG["rest_setiap_volume"]))

win_chance_pct, multiplier_fair = hitung_odds_mines(25, mines_count, len(mines_fields))
WIN_PROB = float(win_chance_pct) / 100.0

QUANTA = _quanta(currency)


def simulasi_mines_ronde(bet: Decimal, force_lose: bool = False):
    """
    Simulasikan satu ronde Mines (minesBet + minesNext + minesCashout)
    secara lokal. Return (won: bool, profit: Decimal, payout: Decimal).

    Kalau menang → payout = bet × multiplier_fair (sedikit kurang dari fair karena house edge).
    Kalau kalah  → payout = 0, profit = -bet.
    """
    house_edge   = Decimal("0.99")   # house edge ~1%
    real_multi   = multiplier_fair * house_edge
    menang       = (not force_lose) and (random.random() < WIN_PROB)
    if menang:
        payout = (bet * real_multi).quantize(QUANTA, rounding=ROUND_DOWN)
    else:
        payout = Decimal("0")
    profit = (payout - bet).quantize(QUANTA, rounding=ROUND_DOWN)
    return menang, profit, payout


def main():
    header(f"SIMULASI DRY-RUN — MINES  [{PROFILE_NAME.upper()}]  (saldo awal {fmt(SALDO_AWAL, currency)})")

    # ── Konfigurasi profil ─────────────────────────────────────────────────────
    print(f"  Profil          : {g(BOLD, PROFILE_NAME.upper())}")
    print(f"  Mines / Kotak   : {g(BOLD, str(mines_count))} ranjau · buka {g(BOLD, str(len(mines_fields)))} kotak")
    print(f"  Win Chance      : {g(BOLD, f'≈{win_chance_pct}%')}  |  Multiplier fair: {g(BOLD, f'≈{multiplier_fair}x')} (real ≈ ×0.99)")
    print(f"  Base Bet        : {g(BOLD, fmt(base_bet, currency))}")
    print(f"  Loss Multiplier : {g(YELLOW, f'×{loss_multiplier}')}  |  Cap: {g(RED, fmt(mines_cap, currency))}")
    print(f"  Reset Bet       : {g(GREEN, 'Instant (tiap menang)') if instant_reset else g(YELLOW, 'Modal Balik (streak_net ≥ 0)')}")
    print(f"  Double-Loss Rest: {g(DIM, 'dinonaktifkan') if double_loss_menit == 0 else g(YELLOW, f'{double_loss_menit} menit')}")
    print(f"  Throttle        : {g(DIM, 'aktif') if throttle else g(GREEN, 'NONAKTIF — full speed')}")
    print(f"  Stop-Loss Sesi  : {g(RED, fmt(max_loss_limit, currency))}")
    print(f"  Batas spin      : {g(BOLD, str(N_SPIN_MAX))}")
    if FORCE_LOSSES > 0:
        print(g(YELLOW, f"\n  ⚠️  {FORCE_LOSSES} spin pertama DIPAKSA kalah (stress-test worst-case)\n"))
    else:
        print(g(DIM, "  (hasil RNG lokal, bukan API Stake.com — tidak ada uang asli terpakai)\n"))

    # ── State ──────────────────────────────────────────────────────────────────
    saldo               = SALDO_AWAL
    total_volume        = Decimal("0")
    total_loss_sesi     = Decimal("0")    # di-reset tiap stop-loss
    total_loss_kumulatif = Decimal("0")
    wins = losses       = 0
    current_bet         = base_bet
    loss_streak         = 0
    streak_net          = Decimal("0")
    max_loss_streak     = 0
    max_bet_reached     = base_bet
    cap_hit_count       = 0
    stoploss_hits       = 0
    profit_lock_level   = 0
    saldo_awal_sesi     = saldo           # acuan profit-lock per sesi
    ronde               = 0
    saldo_habis         = False
    hasil_2_terakhir    = []

    sesi_log            = []
    sesi_ke             = 1
    sesi_wins = sesi_losses = 0
    worst_case_log      = []

    checkpoint_hits     = 0
    next_rest_checkpoint = rest_setiap_volume

    while ronde < N_SPIN_MAX:
        if saldo < current_bet:
            saldo_habis = True
            break

        ronde += 1
        force_lose = ronde <= FORCE_LOSSES
        menang, profit, payout = simulasi_mines_ronde(current_bet, force_lose=force_lose)

        total_volume         += current_bet
        total_loss_sesi      -= profit
        total_loss_kumulatif -= profit
        saldo                += profit

        if menang:
            wins += 1
            sesi_wins += 1
        else:
            losses += 1
            sesi_losses += 1

        # ── Recovery ────────────────────────────────────────────────────────
        hasil_2_terakhir.append(menang)
        hasil_2_terakhir = hasil_2_terakhir[-2:]

        if menang:
            streak_net += profit
            should_reset = instant_reset or (streak_net >= 0)
            if should_reset:
                loss_streak = 0
                current_bet = base_bet
                streak_net  = Decimal("0")
        else:
            streak_net -= current_bet
            loss_streak += 1
            max_loss_streak = max(max_loss_streak, loss_streak)
            naik = current_bet * loss_multiplier
            if naik >= mines_cap:
                current_bet = mines_cap
                cap_hit_count += 1
            else:
                current_bet = naik.quantize(QUANTA, rounding=ROUND_DOWN)
            max_bet_reached = max(max_bet_reached, current_bet)

        if force_lose:
            worst_case_log.append({
                "kalah_ke": ronde, "bet_baru": current_bet, "saldo": saldo,
            })

        # ── Profit lock ───────────────────────────────────────────────────
        surplus     = saldo - saldo_awal_sesi
        target_lock = profit_lock_idr * (profit_lock_level + 1)
        if surplus >= target_lock:
            profit_lock_level += 1

        # ── Stop-loss sesi ────────────────────────────────────────────────
        if total_loss_sesi >= max_loss_limit:
            stoploss_hits += 1
            sesi_log.append({
                "sesi": sesi_ke, "wins": sesi_wins, "losses": sesi_losses,
                "loss_idr": total_loss_sesi, "saldo_akhir": saldo,
            })
            sesi_ke += 1
            sesi_wins = sesi_losses = 0
            total_loss_sesi = Decimal("0")
            current_bet     = base_bet
            loss_streak     = 0
            streak_net      = Decimal("0")
            saldo_awal_sesi = saldo

        # ── Checkpoint volume ─────────────────────────────────────────────
        if total_volume >= next_rest_checkpoint:
            next_rest_checkpoint += rest_setiap_volume
            checkpoint_hits += 1

    # Tutup sesi terakhir
    if sesi_wins + sesi_losses > 0:
        sesi_log.append({
            "sesi": sesi_ke, "wins": sesi_wins, "losses": sesi_losses,
            "loss_idr": total_loss_sesi, "saldo_akhir": saldo,
        })

    total    = wins + losses
    win_rate = (Decimal(wins) / Decimal(total) * 100) if total else Decimal("0")
    net      = saldo - SALDO_AWAL

    # ── Worst-case detail ──────────────────────────────────────────────────────
    if worst_case_log:
        header(f"DETAIL WORST-CASE — {FORCE_LOSSES}x KEKALAHAN BERUNTUN DIPAKSA")
        print(f"  {'Kalah ke-':<12}{'Bet Baru':<18}{'Saldo Setelahnya':<20}")
        for w in worst_case_log:
            _bet_str  = fmt(w["bet_baru"], currency)
            _sld_str  = fmt(w["saldo"], currency)
            _ratio    = (w["bet_baru"] / base_bet)
            _color    = RED if w["bet_baru"] >= mines_cap else YELLOW if w["bet_baru"] > base_bet else DIM
            print(f"  {w['kalah_ke']:<12}{g(_color, f'{_bet_str} (×{_ratio:.2f})'):<35}{g(CYAN, _sld_str)}")
        habis = SALDO_AWAL - worst_case_log[-1]["saldo"]
        print(g(YELLOW, f"\n  💸 Total saldo terpakai: {fmt(habis, currency)}"))
        if worst_case_log[-1]["bet_baru"] >= mines_cap:
            print(g(RED, f"  🛑 Bet sudah di cap {fmt(mines_cap, currency)} sebelum {FORCE_LOSSES}x kalah selesai."))

    # ── Rincian per sesi ───────────────────────────────────────────────────────
    header("RINCIAN PER SESI (antar stop-loss)")
    print(f"  {'Sesi':<6}{'Menang':<10}{'Kalah':<10}{'Loss Sesi':<18}{'Saldo Akhir':<18}")
    for s in sesi_log:
        print(f"  {s['sesi']:<6}{g(GREEN, str(s['wins'])):<17}{g(RED, str(s['losses'])):<17}"
              f"{fmt(s['loss_idr'], currency):<18}{g(CYAN, fmt(s['saldo_akhir'], currency))}")

    # ── Ringkasan total ────────────────────────────────────────────────────────
    header("RINGKASAN TOTAL")
    print(f"  Saldo awal          : {g(BOLD, fmt(SALDO_AWAL, currency))}")
    print(f"  Saldo akhir         : {g(BOLD, fmt(saldo, currency))}")
    print(f"  Ronde dimainkan     : {g(BOLD, str(total))} {g(DIM, f'dari maks {N_SPIN_MAX}')}")
    print(f"  Menang              : {g(GREEN, str(wins))} kali")
    print(f"  Kalah               : {g(RED, str(losses))} kali")
    print(f"  Win Rate            : {g(BOLD, f'{win_rate:.2f}%')}  {g(DIM, f'(target teoritis: {win_chance_pct}%)')}")
    print(f"  Total Volume Wager  : {g(CYAN, fmt(total_volume, currency))}")
    net_color = GREEN if net >= 0 else RED
    print(f"  Net P/L             : {g(net_color, ('+' if net >= 0 else '') + fmt(net, currency))}")
    print(f"  Sesi total          : {len(sesi_log)}  {g(DIM, f'(stop-loss terpicu {stoploss_hits}x)')}")
    print(f"  Volume checkpoint   : {g(DIM, f'{checkpoint_hits}x  (setiap {fmt(rest_setiap_volume, currency)} wager)')}")
    print(f"  Profit-lock level   : {profit_lock_level}x")
    print(f"  Loss streak terpanjang  : {g(YELLOW, str(max_loss_streak))}x")
    print(f"  Bet tertinggi dipasang  : {g(YELLOW, fmt(max_bet_reached, currency))}")
    kali_cap = g(RED, str(cap_hit_count)) if cap_hit_count else g(DIM, "0")
    print(f"  Bet kena cap ({idr_k(mines_cap)})  : {kali_cap}x")

    # ── Perbandingan vs Limbo 98% (wager/ronde basis) ─────────────────────────
    header(f"PERBANDINGAN PROFIL: {PROFILE_NAME.upper()} vs Limbo 98%")
    limbo_win_pct = Decimal("98")
    limbo_multi   = (Decimal("99") / limbo_win_pct).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    wager_per_ronde_mines = float(total_volume) / total if total else 0
    wager_per_ronde_limbo = float(base_bet)
    # Estimasi loss per 1000 ronde
    loss_rate_mines = (100 - float(win_chance_pct)) / 100.0
    loss_rate_limbo = (100 - float(limbo_win_pct)) / 100.0
    exp_loss_mines_1k = loss_rate_mines * 1000 * wager_per_ronde_mines
    exp_loss_limbo_1k = loss_rate_limbo * 1000 * float(base_bet)
    print(f"  {'':38} {g(BOLD, PROFILE_NAME.upper()[:8]):<14} {g(BOLD, 'LIMBO 98%')}")
    print(f"  {'Win rate teoritis':<38} {g(GREEN, f'≈{win_chance_pct}%'):<21} {g(GREEN, f'≈{limbo_win_pct}%')}")
    print(f"  {'Multiplier fair':<38} {g(CYAN, f'≈{multiplier_fair}x'):<21} {g(CYAN, f'≈{limbo_multi}x')}")
    print(f"  {'API calls per ronde':<38} {g(YELLOW, '3 calls'):<21} {g(GREEN, '1 call')}")
    print(f"  {'Est. loss per 1.000 ronde (flat)':<38} {g(RED, idr_k(exp_loss_mines_1k)):<21} {g(DIM, idr_k(exp_loss_limbo_1k))}")
    print(g(DIM, "\n  ⚡ Limbo 98% tetap lebih cepat (1 API call), tapi Mines Wager mendekatinya"))
    print(g(DIM,  "     dengan win rate 96% dan throttle nonaktif.\n"))

    # ── Hasil akhir ────────────────────────────────────────────────────────────
    header("HASIL AKHIR")
    if saldo_habis:
        print(g(RED,
            f"  ⚠️  Saldo HABIS setelah {total} spin — "
            f"sisa {fmt(saldo, currency)} tidak cukup untuk bet {fmt(current_bet, currency)}."))
    elif total == N_SPIN_MAX:
        print(g(GREEN,
            f"  ✅ Saldo {fmt(SALDO_AWAL, currency)} bertahan sampai {N_SPIN_MAX} spin."))

    expected_lo = float(win_chance_pct) * 0.90
    if not (expected_lo <= float(win_rate) <= 100) and total > 0:
        print(g(RED,
            f"  ❌ Win rate {win_rate:.2f}% jauh dari target {win_chance_pct}% — cek logika simulasi"))
    elif total > 0:
        print(g(GREEN,
            f"  ✅ Win rate {win_rate:.2f}% masuk rentang wajar (target: {win_chance_pct}%)"))

    if max_bet_reached <= mines_cap:
        print(g(GREEN, f"  ✅ Bet tidak pernah melebihi cap {fmt(mines_cap, currency)}"))
    else:
        print(g(RED,   f"  ❌ Bet melebihi cap — bug pada logika recovery!"))

    print(g(DIM, "\n  Simulasi RNG lokal — tidak ada API call / uang asli terpakai.\n"))


if __name__ == "__main__":
    main()
