Change request: stop restock tasks on deals auto-replenish already tops up (config-only)

What changes. One block added to config/env_overrides.json: "routing": {"suppressed_deal_ids": [...]}. No code change. Routing already drops any deal in suppressed_deal_ids. The list = the 3 deals Ops already suppress in routing.json (kept, because the override replaces that list) + 1,097 deals that have an auto-replenish schedule with no end date or ending after 7 Jan, merchant band B–D, not do-not-contact. Priors override untouched. Touches: tomorrow's task lists only. No data, no merchant-facing change.

Why. Those deals restock by themselves (96% within a median of 7 days). A connected call there adds £0–3 GP. ~77 tasks/week, ~15 rep hours/week back.

Off by default, one switch, Ops holds it. It ships as a ready file; nothing changes until Ops deploys it. Off = delete the "routing" block from env_overrides.json; the next morning run is exactly today's output (tested). Nothing to clean up: tasks that weren't created don't need closing.

Holdout. 20% of eligible merchants (274 deals), picked by a fixed hash, stay off the list and keep getting tasks.

Stop rule. Switch off if any of these:
1. Treated deals' restock rate within 14 days falls more than 5 points below the holdout's (weekly check).
2. A rep or merchant reports a listed deal sold out 14+ days.
3. From 30 days in: GP per sold-out for treated deals is more than £2 below holdout (90% interval).
Owner: Daniel runs the check every Monday and posts it in #uk-soldouts; Hana switches it off. (Hana, OK to be named?)

Only automation. Every deal on the list is there because of an auto-replenish schedule. Nobody is skipped for any other reason, so no rep-confirmed list is needed for this change. Rep marks in the tool don't touch routing.

Known limit. In the current code suppressed_deal_ids also drops a promised callback on that deal. On auto-topped-up deals that should be rare; reps can still ring. Proper fix (callbacks never suppressed, behind suppress_soldout_tasks) is ready as 2.16.0 for January.

Review. Hana is getting the list and the config diff today. Agreed by Thursday morning for Friday's gate; otherwise January.
