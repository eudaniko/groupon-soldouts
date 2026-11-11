# routing

Builds each rep's morning task list from yesterday's sold-outs. Owned by Merchant Ops (Hana day to day). Runs overnight; lists are ready by about 07:00.

```
python3 -m routing.plan input/todays_soldouts.csv
python3 -m unittest discover -s tests     # or: python3 -m pytest
```

## What it does

1. Takes the sold-outs for one rep (`input/todays_soldouts.csv` is yesterday's file for one rep).
2. Creates one restock task per sold-out. It works from that file only. It has no view of anything else that may be happening to the deal.
3. Drops do-not-contact merchants and anything in `suppressed_deal_ids`. Pauses merchants after too many failed attempts.
4. Promised callbacks go first, whatever they are worth. Someone told the merchant we would ring.
5. The rest are ranked by expected GP: `(called - left_alone) x value_30d_gbp`, using the restock priors.
6. Fills the rep's day. Whatever doesn't fit carries over to tomorrow and shows as overdue.

## Config

| File | What's in it |
|---|---|
| `config/routing.json` | Minutes per day, minutes per task, pause threshold, `suppressed_deal_ids`, `suppress_soldout_tasks`, `suppression_file` |
| `priors.json` | Restock priors used for ranking; also the priors for other task types |
| `config/env_overrides.json` | Environment values. Loaded last, on top of the above, and takes precedence (`priors` over `priors.json`, `routing` over `config/routing.json`) |
| `input/suppressions.csv` | Sold-out suppression list: `deal_id`, `merchant_id`, `reason`, `source`, `added_on`. Ships empty |

Notes for anyone changing things:

- All values are read at start of run. There is no hot reload.
- `suppressed_deal_ids` is a plain list of deal ids. A suppressed deal gets no task. Ops use it for deals in dispute or under a manual arrangement.
- Value per task comes from the input file; routing does not compute it.
- The input file's column order matters to the importer, so add columns at the end.

## Sold-out suppression (not wired yet)

Agreed in October so reps stop getting tasks that don't need them. Only the plumbing exists:

- `suppress_soldout_tasks` in `config/routing.json`. Default `false`. This is the one switch.
- `input/suppressions.csv`, read by `routing/suppressions.py` (`load_suppressions()`). A row needs a `deal_id`, or a `merchant_id` for the whole merchant.
- `plan.py` doesn't use either yet. With the switch off, output must stay exactly as it is today.

Whoever picks it up: decide what goes in the file and why, wire it into `plan.py` behind the switch, add tests, and remember `env_overrides.json` wins over `routing.json`. Rolling back means switching it off, nothing else.

## Ops

- Changes go to Wednesday change review, then Merchant Ops deploys. Config changes count as changes.
- Peak change freeze: nothing touches routing or its config until 7 January.
- Version: 2.15.0 (2.15.0 added the suppression switch and file, unused)
