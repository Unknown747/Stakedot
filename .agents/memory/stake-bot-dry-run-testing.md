---
name: Stake bot testing without API key
description: How to test the Stake.com bot's betting logic at volume (e.g. hundreds/thousands of spins) when no STAKE_API_KEY secret is configured.
---

## No API key means no live bets — use a local RNG dry-run instead of skipping the test
When asked to test the bot with many spins (e.g. 1000) and `STAKE_API_KEY` is not set in Secrets, do not silently skip testing or fabricate results. Ask the user whether they want to provide a real API key (real money risk) or get a local dry-run simulation instead.
**Why:** the bot places real-money bets via Stake's GraphQL API; running hundreds/thousands of live bets without explicit consent is a significant, irreversible financial action.
**How to apply:** build a standalone simulator script that imports the bot's pure logic (win-determination function, money-management/on-loss-multiply logic, formatting helpers) from the main script and replaces only the network call with a local RNG roll matching the game's real win probability. This validates stop-loss, profit-lock, bet-cap, and win-rate-consistency logic without touching the API or real funds. Keep this simulator as a separate file from the live/API-based audit script so the two testing modes stay clearly distinct.
