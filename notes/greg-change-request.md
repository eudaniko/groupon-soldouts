Change request: stop restock tasks on deals auto-replenish already tops up (config-only)

What changes. One block added to config/env_overrides.json: "routing": {"suppressed_deal_ids": [...]}. No code change. Routing already drops any deal in suppressed_deal_ids. The list = the 3 deals Ops already suppress in routing.json (kept, because the override replaces that list) + 1,097 deals with an auto-replenish schedule that has no end date or ends after 7 Jan, merchant band B–D, not do-not-contact. Priors override untouched. Touches: the morning task lists, from the first run after the deploy. No data changes, nothing merchant-facing.

Why. Those deals restock by themselves (96% do, median 7 days). A connected call there adds £0–3 GP. On the last 12 weeks this list would have removed ~88 tasks a week (14% of all restock tasks), ~18 rep hours a week. GP at risk: ~£500 a year (worst case ~£1k).

Off by default, one switch, Ops holds it. Nothing changes until Merchant Ops deploys the file. Off = Merchant Ops deploys env_overrides.json without the "routing" block. That is a config deploy by your team, not a flip: it takes effect from the first morning run after the deploy, and the output is then exactly today's (tested). Nothing to clean up: tasks that weren't created don't need closing.

Holdout. 20% of eligible merchants (274 deals), picked by a fixed hash, stay off the list and keep getting tasks.

Stop rule. Off if any of these:
1. A rep or merchant reports a listed deal sold out for 14+ days.
2. From week 4, checked weekly: listed deals' 14-day restock rate falls more than 10 points behind the holdout, measured against the same gap before launch. (Why 10: on history with no change at all, this number moves by about ±9 points at 4 weeks.)
3. From day 30: GP per sold-out is credibly lower than the holdout (the 90% interval is entirely below zero).
Owner: Daniel runs the check every Monday (python3 -m soldouts.measure readout) and posts it in #uk-soldouts. Who in Merchant Ops removes it, and whether that counts as an emergency change you sign off during the freeze, is your call: please name the person.

Only automation. Every deal is on the list because of an auto-replenish schedule. Nobody is skipped for any other reason, so no rep-confirmed list is needed for this change. Rep marks in the tool don't touch routing.

Known limit. In today's code suppressed_deal_ids also drops a promised callback on that deal. Should be rare on auto-topped-up deals; reps can still ring. The proper fix (callbacks never suppressed, behind suppress_soldout_tasks) is ready as 2.16.0 for January.

Review. Hana has looked at the list and the config. Agreed by Thursday morning for Friday's gate; otherwise January.

Two questions for you: (1) OK to go in before the freeze, given rollback is a config deploy? (2) Who removes it if a stop rule triggers?
