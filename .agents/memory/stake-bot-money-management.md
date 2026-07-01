---
name: Stake bot money management
description: Decisions about the Stake.com auto-bet bot's game choice, bet sizing strategy, and CLI behavior — read before changing main.py's core betting logic (bot entry point was renamed from dice.py to main.py).
---

## Full martingale was rejected in favor of gentle escalation
The user tried full martingale-style recovery (large single "recovery bet" after a loss) and it caused large losses in practice, so it was disabled.
It was later replaced with a lighter "on-loss multiply" scheme: bet increases by a small fixed percentage (e.g. 2%) after each loss, resets to base bet on any win, with a hard cap (e.g. 5x base bet).
**Why:** full martingale grows bet size too fast for a small bankroll under Stake's ~98%-win/2%-house-edge dice/limbo games; slow geometric growth keeps drawdown manageable while still recovering some loss.
**How to apply:** when asked to add "recovery" or "loss recovery" to this bot, default to gentle percentage-based escalation with a hard cap, not doubling/martingale, unless the user explicitly insists otherwise — and if they do, flag the risk first.

## CLI must auto-run with zero prompts (VPS-focused)
The user runs this bot unattended on a VPS. All interactive menus (mode selection, y/n prompts) were removed; `python3 main.py` goes straight into the auto-bet loop with automatic session restarts and rest countdowns between sessions.
**Why:** stated explicitly — "script fokus di vps," no one is at the keyboard to answer prompts.
**How to apply:** any new feature must not introduce a blocking `input()` call in the main run path; use config constants instead.

## Game/API mutation choice is a real product decision, not just internal logic
The bot has been switched between Stake's Dice game and Limbo game (different GraphQL mutations/fields: `diceRoll` with target+condition vs `limboBet` with `multiplierTarget`). Win-chance/multiplier math (`multiplier ≈ 99 / win_chance_pct`) is shared, but the mutation, win-determination function, and bet display all need to change together when switching games.
**Why:** these are different casino games with different API shapes; mixing them causes API errors or silent wrong-win detection.
**How to apply:** when switching games again, grep for the old mutation name and win-determination function to make sure no orphaned references remain (this codebase had recurring dead-code buildup from prior menu/game switches, cleaned up via orphan-function/import audits).
