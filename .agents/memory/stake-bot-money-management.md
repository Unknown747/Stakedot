---
name: Stake bot money management
description: Decisions about the Stake.com auto-bet bot's game choice, bet sizing strategy, and CLI behavior — read before changing main.py's core betting logic (bot entry point was renamed from dice.py to main.py).
---

## Full martingale was rejected in favor of gentle escalation
The user tried full martingale-style recovery (large single "recovery bet" after a loss) and it caused large losses in practice, so it was disabled.
It was later replaced with a lighter "on-loss multiply" scheme: bet increases by a small fixed percentage (e.g. 2%) after each loss, resets to base bet on any win, with a hard cap (e.g. 5x base bet).
**Why:** full martingale grows bet size too fast for a small bankroll under Stake's ~98%-win/2%-house-edge dice/limbo games; slow geometric growth keeps drawdown manageable while still recovering some loss.
**How to apply:** when asked to add "recovery" or "loss recovery" to this bot, default to gentle percentage-based escalation with a hard cap, not doubling/martingale, unless the user explicitly insists otherwise — and if they do, flag the risk first.

## CLI must auto-run with zero prompts (VPS-focused) — except a one-time startup choice
The user runs this bot unattended on a VPS. Interactive menus were removed from the per-session loop; `python3 main.py` runs the auto-bet loop with automatic session restarts and rest countdowns between sessions, with no `input()` calls inside that loop.
An explicit exception was later added: a single `input()` at the very start of `main()` (before the VPS loop begins) to choose which game strategy to run (e.g. "1. Limbo, 2. Mines"). This is a one-time choice, not a per-session prompt, so it doesn't break unattended 24/7 operation.
**Why:** stated explicitly — "script fokus di vps," no one is at the keyboard to answer prompts *during* a running session; but choosing which strategy to run once at boot is acceptable and was explicitly requested.
**How to apply:** any new feature must not introduce a blocking `input()` call inside the session loop; a single one-time selection prompt before the loop starts is fine. New strategies should be added as their own `jalankan_strategy_*_vip()` function selected via this startup menu, not as branches deep inside one shared function.

## Mines was added as a second game alongside Limbo — different bet/round shape
Mines uses a 3-call-per-round flow (`minesBet` → `minesNext(fields)` → `minesCashout`), not a single mutation like Limbo/Dice. Win/loss is determined by whether `state.mines` becomes non-null right after `minesNext` (non-null = hit a mine = loss, payout 0 stays; null = still safe → call `minesCashout` to lock the win).
Tile-reveal pattern (which indices you pick) has **no effect on odds** — mine positions are freshly randomized per round via Provably Fair; picking 2 fixed indices is purely for code simplicity, not "safer tiles."
Money management deliberately differs from Limbo's on-loss-multiply: on loss, bet multiplies ×1.5 from the *previous* bet (not compounding from base, not martingale ×2); bet only resets to base once the cumulative net loss streak (`streak_net`) recovers to ≥0, not on the first win after a loss. Two mine-hits in a row triggers a short (~1 min) in-session rest, separate from the stop-loss rest.
**Why:** user explicitly designed and confirmed this recovery scheme distinct from Limbo's; also corrected a misconception that tile choice affects win probability — it's purely combinatorial (`C(24,2)/C(25,2)` for 1 mine, 2 reveals ≈ 92%).
**How to apply:** keep Mines' `jalankan_strategy_mines_vip()` as its own function mirroring `jalankan_strategy_vip()`'s logging/CSV/stop-loss/checkpoint structure, but never merge its 3-call bet flow or ×1.5-recovery math into Limbo's single-call/percent-escalation logic.

Mines odds/multiplier displayed in the CLI are computed live via exact combinatorics (`hitung_odds_mines`: `C(safe,reveals)/C(total,reveals)`), not hardcoded per mode — this made it trivial to add a second "agresif" profile (more mines, lower win chance, gentler ×1.3 recovery multiplier since losses are more frequent) without touching the odds-display code. Config stores multiple named profiles under `mines_profiles` (dict of dicts) rather than flat `mines_*` keys, selected via a one-time submenu after choosing Mines.
**Why:** a second risk profile was requested right after Mines shipped; computing odds live instead of hardcoding avoided stale/wrong percentages when profile parameters change.
**How to apply:** when adding another Mines profile or game variant, add a new named entry under `mines_profiles` (don't reintroduce flat `mines_*` config keys) and reuse `hitung_odds_mines()` for any displayed win-chance/multiplier text.

## Game/API mutation choice is a real product decision, not just internal logic
The bot has been switched between Stake's Dice game and Limbo game (different GraphQL mutations/fields: `diceRoll` with target+condition vs `limboBet` with `multiplierTarget`). Win-chance/multiplier math (`multiplier ≈ 99 / win_chance_pct`) is shared, but the mutation, win-determination function, and bet display all need to change together when switching games.
**Why:** these are different casino games with different API shapes; mixing them causes API errors or silent wrong-win detection.
**How to apply:** when switching games again, grep for the old mutation name and win-determination function to make sure no orphaned references remain (this codebase had recurring dead-code buildup from prior menu/game switches, cleaned up via orphan-function/import audits).
