Change request: stop restock tasks on deals auto-replenish already tops up (config-only)

What changes. One block added to config/env_overrides.json: "routing": {"suppressed_deal_ids": [...]}. No code change. Routing already drops any deal in suppressed_deal_ids. The list = the 3 deals Ops already suppress in routing.json (kept, because the override replaces that list) + 1,097 deals with an auto-replenish schedule that has no end date or ends after 7 Jan, merchant band B–D, not do-not-contact. Priors override untouched. Touches: the morning task lists, from the first run after the deploy. No data changes, nothing merchant-facing.

Why. Those deals restock by themselves (96% do, median 7 days). A connected call there adds £0–3 GP. On the last 12 weeks this list would have removed ~88 tasks a week (14% of all restock tasks), ~18 rep hours a week. GP at risk: ~£500 a year (worst case ~£1k).

Off by default, one switch, Ops holds it. Nothing changes until Merchant Ops deploys the file. Off = Merchant Ops deploys env_overrides.json without the "routing" block. That is a config deploy by your team, not a flip: it takes effect from the first morning run after the deploy, and the output is then exactly today's (tested). Nothing to clean up: tasks that weren't created don't need closing.

Holdout. 20% of eligible merchants (274 deals), picked by a fixed hash, stay off the list and keep getting tasks.

Stop rule. Off if any of these (lines 2 and 3 compare listed deals with the holdout, minus the same gap in the 12 weeks before launch):
1. A rep or merchant reports a listed deal sold out for 14+ days.
2. Restock: listed deals' 14-day restock rate is more than 16 points behind the holdout (average is ~75%). Checked every Monday from week 6, when four weeks of sold-outs have had their 14 days.
3. GP: listed deals' 30-day GP per sold-out is more than £8 below the holdout (average is ~£16). Checked every Monday from week 8, when four weeks of sold-outs have had their 30 days.
Why these numbers: the two groups drift apart by themselves. Last winter, with no change at all, the comparison would have read up to 15 points and £7.50 behind, so tighter lines would fire by chance in exactly the freeze. Tested on a year of history with no change (a fake launch every day, put through the Monday checks): these lines would have stopped 1 launch in 100 by chance, and none of those made at this time of year. (I had 10 points before; tested this way, that would have stopped half the launches made at this time of year.) The flip side: the lines only catch a big drop. A small loss, like the ~£500 a year expected, is too small for a 20% holdout to see.
Owner: Daniel runs the check every Monday (python3 -m soldouts.measure readout, which prints stop_now) and posts it in #uk-soldouts. Removal: Merchant Ops, as a production config deploy through you. Hana's switch is the sandbox one; this change doesn't use it.

In the freeze. From Monday to 7 Jan nothing touches merchant config, so a removal in that window is a deploy you'd have to let through as an exception. If you'd rather not: on the numbers the list puts about £90 of GP at risk over the whole freeze (worst case ~£160), and reps can still ring any listed deal; it just isn't on their list.

Only automation. Every deal is on the list because of an auto-replenish schedule. Nobody is skipped for any other reason, so no rep-confirmed list is needed for this change. Rep marks in the tool don't touch routing.

Callbacks. In today's code suppressed_deal_ids also drops a promised callback on a listed deal. Count: today's routing input has 36 tasks and 3 promised callbacks (T-0004, T-0007, T-0010). The list removes 3 tasks (T-0027, T-0028, T-0036), none with a callback, so it drops 0 today; I checked by running the routing code with the new config. History doesn't record promised callbacks (not in the CRM export or the sandbox), so I can't give a weekly number from data. If Ops shares the Monday input, I'll run the same count on it (python3 -m soldouts.measure callbacks). The proper fix (callbacks never suppressed) is 2.16.0, for January.

Review. Hana looked at the list and the config on Tuesday; I've asked her to confirm the diff to you directly. For Wednesday's 15:00 change review. If it isn't agreed there: Friday's 11:00 gate at the latest (agreed by Thursday morning), otherwise January.

Two questions for you: (1) OK to take it at Wednesday's review? (2) If a stop line is crossed during the freeze, will you let the removal through as an exception?
