# Change request: routing 2.16.0, sold-out task suppression for auto-replenished deals

**For:** Greg Lindqvist (Merchant Ops). **Code review:** Hana Kowalczyk. **From:** Daniel Nikonenko. **For:** Wednesday change review.

## What changes

1. `routing/plan.py` uses the existing `suppress_soldout_tasks` switch and `input/suppressions.csv` (both shipped unused in 2.15.0). When the switch is on, a sold-out on a listed deal (or merchant) gets no restock task. Promised callbacks are never suppressed. Everything else in the morning run is unchanged.
2. A one-time `input/suppressions.csv` with **1,097 deals**: deals with an auto-replenish schedule that has no end date or ends after 7 January, merchants in bands B to D, not do-not-contact. 20% of eligible merchants (274 deals) are held out by a fixed hash and keep their tasks, so we can measure.
3. Switch stays **off** in the deploy. Turning it on is a separate one-line config change.

Why: these deals restock by themselves (96% within a median of 7 days). A connected call on them adds about £0 to £3 of GP. That's ~77 tasks and ~15 rep hours a week.

## Risk

- **A deal stays sold out that a rep would have restocked.** Bounded: those calls added ~£450 a year in total (worst case ~£850). The holdout shows it if it's worse.
- **A schedule ends during the freeze and the deal is still on the list.** Avoided: only schedules running past 7 January are listed.
- **The switch flips by accident or config is mistyped.** Only JSON `true` turns it on; `"true"` as a string, `1` or a missing key mean off. `env_overrides.json` wins over `routing.json`, so the switch must be set in one place; we set it in `routing.json` only.
- **Output with the switch off differs from today.** Tested: identical to 2.15.0. 22 routing tests pass (11 existing + 11 new).
- Freed slots are filled from carry-over, like any dropped task. Reps see fewer overdue tasks.

## Rollback

Set `suppress_soldout_tasks` to `false` in `config/routing.json`. Applies from the next morning run. Nothing else to undo: no data is changed, tasks that weren't created don't need closing. Emptying `suppressions.csv` also works.

## When to stop

Switch it off if any of these happens:
- a rep or merchant reports a deal sold out for 14+ days that's on the list;
- weekly check: restock rate within 14 days for treated deals is more than 5 points below the holdout;
- from 30 days in: GP per sold-out for treated deals is more than £2 below the holdout (90% interval);
- Greg or Hana asks.

## How we'll check

`python3 -m soldouts.measure readout --start <switch-on date>` on a fresh export. Rep hours saved is counted from week 1. GP: first read 9 January, firm by end of February.

## Timing

Hana reviews the diff before Wednesday's change review. If Greg agrees, switch on before the freeze starts Monday, since the change and the file are fixed for the freeze. If not before Monday, it waits until after 7 January.
