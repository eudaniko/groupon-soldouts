# Sold-outs: which restock tasks are worth a rep's call

Built for Dan Okafor's sold-outs ask (Groupon UK Local, case exercise). People, merchants and numbers are invented.

**In one line:** about 1 in 6 restock tasks is for a deal that tops itself up (auto-replenish), and a call there adds almost nothing. Stop creating those tasks (behind a switch, with a 20% holdout), and give reps a phone page that says, for the rest, call / don't bother / something else, with the £ and the quote behind it.

## Run it

Needs Python 3.10+. No packages for the tool or the tests.

```bash
python3 -m soldouts.app                    # rep tool on http://localhost:8080 (demo data without a key)
python3 -m unittest discover -s tests      # tool tests
(cd routing && python3 -m unittest discover -s tests)   # routing service tests (incl. the change)
```

With the sandbox: put `SANDBOX_KEY=...` in `.env` (git-ignored). The tool then reads `GET /soldouts/today` and writes marks with `PUT /merchants/{id}/mark`. Without it, it uses `routing/input/todays_soldouts.csv` and says "demo data" at the top.

Other commands:

```bash
python3 -m soldouts.detect --backend rules --pack data/pack --merchants M10001   # text flags, offline
python3 -m soldouts.detect --backend llm --merchants M10001 --out data/flags_llm.json --merge   # needs key
python3 -m soldouts.measure estimate                      # the range, from history
python3 -m soldouts.measure readout --start 2026-11-14    # the real number, after launch
python3 scripts/build_suppressions.py --on 2026-11-13 --out proposal/suppressions.csv
python3 scripts/estimate_uplift.py                        # re-check of the £11 memo (needs pandas)
```

The data pack (`data-pack.zip` from the Desk) goes in `data/pack/` for the scripts that read history. It isn't committed. The tool itself runs from `data/context.json` and `data/uplift.json`, which are built from it and committed.

## What's here

| Part | Where | Status |
|---|---|---|
| Rep tool (phone) | `soldouts/app.py`, `soldouts/static/index.html` | Works. Rep filter, call / something else / later / skip, £ value, quotes, merchant marks |
| Money logic | `soldouts/money.py`, `soldouts/decide.py` | Works, tested. Code does the sums |
| Text flags (AI) | `soldouts/detect.py`, `soldouts/texts.py` | Rules backend offline; LLM backend with word-for-word quote check; results cached |
| Routing change | `routing/` (2.15.0 imported as-is, then changed in one commit) | Done, tested, off by default |
| Suppression list | `scripts/build_suppressions.py` -> `proposal/suppressions.csv` | Generated, not installed |
| Measurement | `soldouts/measure.py`, `soldouts/holdout.py` | Estimate + readout scripts |
| Analysis | `scripts/estimate_uplift.py` -> `data/uplift.json` | Re-check of Priya's memo |
| Notes | `notes/dan.md`, `notes/greg-change-request.md` | |

## What I decided, and why

**1. Priya's £11 per call is real for some sold-outs, not for all, and £340k a year is far too high.** I reproduced the memo (£11.33 with its method) and then:
- removed the CRM sync-replay duplicates, and the February 2026 migration rows that log Deal Alert emails as 1 to 4 second "calls" by reps;
- split out sold-outs where an auto-replenish schedule was running that day. That's **18.6%** of them. The memo assumed automation was negligible. These deals restock by themselves 96% of the time in a median of 7 days;
- compared called and left-alone sold-outs **of the same merchant**, so "reps call the merchants who'd have done well anyway" mostly drops out;
- weighted by sold-outs, not by calls (the memo's weighting tilts to band A).

Value of a connected restock call, GP over 30 days, same merchant (90% interval):

| Band | Manual deals | With auto-replenish running |
|---|---|---|
| A | £14.64 (11.9 to 16.9) | £14.56 (2.7 to 27.8, only 48 calls) |
| B | £8.18 (6.7 to 9.7) | £3.23 (1.5 to 4.9) |
| C | £4.09 (2.9 to 5.2) | -£0.14 (-1.1 to 0.8) |
| D | £2.04 (1.0 to 3.1) | £0.94 (0.4 to 1.6) |

The £340k multiplies £11 by every task, but 28% are already called, the ones left are mostly small merchants, and the figure has no rep time in it.

**2. The routing change is narrow on purpose.** Only deals with an open-ended auto-replenish schedule, bands B to D. Not band A: too few calls to be sure (the interval runs from £2.7 to £27.8). Not "every low-value task": that's a bigger change to how reps work and Dan, Renee and Greg should decide it, not me in three hours. It is the part I'm most sure is safe: about 77 tasks a week, ~15 rep hours, and at most ~£800 a year of GP at risk.

**3. Off by default, one switch, rollback = switch off.** The switch and the empty suppression file already existed in routing 2.15.0 ("agreed in October"). I wired them in `plan.py`: with the switch off the output is identical (tested); promised callbacks are never suppressed; only JSON `true` turns it on (a string `"false"` in `env_overrides.json` would otherwise be truthy).

**4. The list only uses schedules that run past the freeze** (no end date, or ending after 7 January). Routing reads the file once per run and nobody can regenerate it during the freeze, so a schedule ending in December would leave a deal suppressed with nothing topping it up.

**5. Holdout: 20% of merchants, by a stable hash**, keep getting tasks. The readout compares the same kind of sold-out in both groups, so peak season hits both.

**6. Money: value = P(connect) x GP uplift x (1 - refund risk) - rep time.** Per band uplift from the table; P(connect) is the merchant's own history pulled towards the band rate; refund risk is the merchant's refunds over the last 6 months as a share of GP + refunds, doubled if the text says they can't take more customers (the 30-day GP misses refunds that come later). Rep time is 12 minutes at **£20/hour, an assumption** (asked Priya for the real figure). At £20/h most band C and D tasks are worth less than the rep's time.

**7. Decision order** (`soldouts/decide.py`): do-not-contact, promised callback, the rep's own mark, auto-replenish, merchant said no, merchant away (only if said in the last 3 weeks), capacity or quality problem (then: talk capacity, not a bigger cap), Deal Alert link trouble (then: send login help, not a sales call), then the £ value.

**8. One customer complaint is not a flag.** A review or refund reason only counts with a second one, or if the rep or merchant said it too. A newer "wants more" from the merchant beats older negatives.

## Where AI is used, and how it's checked

- **In the product:** `soldouts/detect.py` sends one merchant's last 12 months of text (rep notes, Deal Alert replies, reviews, refund reasons; newest 60 items) to `claude-haiku-5-5` through the sandbox gateway, with a fixed JSON schema and thinking off. It must cite an item id and quote it word for word. **Code checks every quote against the cited item and drops it if it isn't there.** Cut-off answers (`stop_reason` not `end_turn`) are rejected, not parsed. Results are cached in `data/flags_llm.json`; the tool reads the cache and falls back to the rules backend.
- **The AI never does the sums or makes the decision.** It produces flags + quotes; `decide.py` applies fixed rules.
- **Offline:** the rules backend (regular expressions, same output shape) runs with no network and no key, which is what the tests and an offline run use.
- **Checked against people:** see "Checked against a rep" below.
- **To build it:** I used Claude (chat + code) for analysis, code and drafts. Session export is in the submission.

## Checked against a rep

PENDING: Renee's labels for merchants in her book vs the tool's decision and flags.

## What it can't do yet

- Doesn't know a rep's real day: it ranks and explains, routing still builds the list.
- £ values are 30-day GP and use a guessed hourly cost. Long-term effects (a merchant who stops working with us) aren't in it.
- Refund risk is a proxy (past refund share), not a forecast.
- Rules backend is crude: it flags "auto top-up" in "auto top-up wasn't something she wanted". The LLM reads that correctly, but only for merchants we paid to run it on.
- Merchant marks live in the sandbox (and a local file); routing doesn't read them.
- The readout needs ~3 months of sold-outs + 30 days to say anything about GP with confidence. Rep hours saved are counted from day one.

## What I cut, and why

- **Suppressing every task worth less than the rep's time** (most C/D tasks at £20/h). Biggest prize, but changes reps' jobs and needs Dan/Renee to agree; also needs the real hourly cost. Next step.
- **Band A auto-replenish tasks.** Not enough data to be sure.
- **Automated cap raises** (Priya's second recommendation). Greg said not before January, and it's his team's call.
- **Routing reading marks or flags directly.** Would be a bigger change in a freeze week.
- **Running the LLM on all 3,000 merchants.** Budget (~1 cent each through Sonnet) and not needed: today's sold-outs only.
- **Login, rep accounts, offline mode in the app.** A shared password on the hosted copy.
