# Sold-outs: which restock tasks are worth a rep's call

Built for Dan Okafor's sold-outs ask (Groupon UK Local, case exercise). People, merchants and numbers are invented.

**In one line:** about 1 in 5 restock tasks is for a deal that tops itself up (auto-replenish), and a call there adds almost nothing. Stop creating most of those tasks (config-only, off by default, with a 20% holdout), and give reps a phone page that says, for every sold-out, call / skip / later / something else, with the £ and the merchant's own words behind it.

**For Dan:** ~18 rep hours a week back, counted from day one, with under £1k a year of GP at risk. What reps do with that time is worth £0 to ~£50k of GP a year, not £340k. First restock check at Christmas, first GP check early January, firm by March (if it goes in this week, before the freeze).

## Run it

Needs Python 3.10+. No packages for the tool or the tests.

```bash
python3 -m soldouts.app                    # rep tool on http://localhost:8080 (demo data without a key)
python3 -m unittest discover -s tests      # tool tests
(cd routing && python3 -m unittest discover -s tests)   # routing service tests (incl. the change)
```

On a shared server, set `APP_PASSWORD=...` (one team password): the tool then shows a sign-in page and keeps each phone signed in for 30 days with a signed cookie (HttpOnly; changing the password signs everyone out; 8 wrong tries from one address pause sign-in for 10 minutes). Scripts can still use basic auth (`curl -u x:$APP_PASSWORD`). Without it, there's no sign-in, for running it locally.

With `OPEN_SIGN_IN=1` the same sign-in page has no password box: one tap on Sign in and you're in (same 30-day cookie). The hand-in copy runs this way, so anyone with the link can open it, and can also mark merchants. Remove the line from `.env` and restart to need the password again.

With the sandbox: put `SANDBOX_KEY=...` in `.env` (git-ignored). The tool then reads `GET /soldouts/today` and writes marks with `PUT /merchants/{id}/mark`. Without it, it uses `routing/input/todays_soldouts.csv` and says "demo data" at the top.

The AI detector, offline from a file (no network, no key):

```bash
python3 -m soldouts.detect --items tests/fixtures/sample_items.json                   # rules backend
python3 -m soldouts.detect --items tests/fixtures/sample_items.json --backend replay  # recorded LLM answers, quotes re-checked
```

`sample_items.json` is the cleaned text for 5 merchants from the data pack. `replay` takes the LLM's recorded answers (`data/flags_llm.json`, 73 merchants) and runs the same quote check on them, so you can see what the model said and that every quote is really in the text.

Other commands:

```bash
python3 -m soldouts.detect --backend rules --pack data/pack --merchants M10001   # text flags from the pack, offline
python3 -m soldouts.detect --backend llm --merchants M10001 --out data/flags_llm.json --merge   # live, needs key
python3 -m soldouts.measure volume                        # what the actual list removes (last 12 weeks)
python3 -m soldouts.measure estimate                      # the range, from history
python3 -m soldouts.measure readout --start 2026-11-12    # the real number and the stop lines, after launch
python3 -m soldouts.measure callbacks                      # promised callbacks the list would drop (routing input)
python3 scripts/aa_stop_lines.py                          # how often the stop lines fire by chance (A/A on history)
python3 -m soldouts.evaluate data/rep_labels.csv          # tool vs a rep's ring/leave
python3 scripts/build_suppressions.py --on 2026-11-13 --out proposal/suppressions.csv
python3 scripts/build_overrides.py                        # proposal/env_overrides.json + the diff Hana reviews
python3 scripts/estimate_uplift.py                        # re-check of the £11 memo (needs pandas)
```

The data pack (`data-pack.zip` from the Desk) goes in `data/pack/` for the scripts that read history. It isn't committed. The tool itself runs from `data/context.json` and `data/uplift.json`, which are built from it and committed.

## What's here

| Part | Where | Status |
|---|---|---|
| Rep tool (phone) | `soldouts/app.py`, `soldouts/static/index.html` | Works, hosted (link in the submission). Rep picker with search, call / other / later / skip, rank + £ + the sum behind it, "decided by" rule, quotes, merchant marks, editable hourly assumption |
| Money logic | `soldouts/money.py`, `soldouts/decide.py` | Works, tested. Code does the sums |
| Text flags (AI) | `soldouts/detect.py`, `soldouts/texts.py` | Rules backend offline; LLM backend with word-for-word quote check; results cached |
| Routing change | `proposal/env_overrides.json` (config-only, for the freeze); `routing/` 2.16.0 code version for January | Done, tested, off by default |
| Suppression list | `scripts/build_suppressions.py` -> `proposal/suppressions.csv` | Generated, not installed |
| Measurement | `soldouts/measure.py`, `soldouts/holdout.py` | Volume, estimate and readout (holdout, corrected for the pre-launch gap) |
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

Deal Alerts (Priya's tip): 79% of manual sold-outs in the period got a sold-out alert within 3 days. With an alert, left-alone deals restock a bit more often (58% vs 52%) and a connected call is worth a bit less (£9.69 vs £11.17, same-merchant). So alerts do part of the job, but much less than auto-replenish. Not used in the decision yet; worth a look at why 21% get no alert.

The £340k multiplies £11 by every task, but 28% are already called, the ones left are mostly small merchants, and the figure has no rep time in it.

**2. The routing change is narrow on purpose.** Only deals with an open-ended auto-replenish schedule, bands B to D. Not band A: too few calls to be sure (the interval runs from £2.7 to £27.8). Not "every low-value task": that's a bigger change to how reps work and Dan, Renee and Greg should decide it, not me in three hours. It is the part I'm most sure is safe. Applied to the last 12 weeks, the list removes ~88 tasks a week (14% of all restock tasks), ~18 rep hours, with ~£500 a year of GP at risk (worst case ~£1k).

**3a. For the freeze: config-only.** Greg's condition was "config-only, or it's January". So what goes to Greg's change review (Wednesday 15:00, the last before the freeze; Friday 11:00 is only a final gate for things already discussed) is `proposal/env_overrides.json`: the existing priors override unchanged, plus `routing.suppressed_deal_ids` with Ops' 3 existing ids (the override replaces the list in `routing.json`, so they must be carried over) and the 1,097 auto-replenish deals. No code change; routing already honours that list. Off = Merchant Ops deploys the file without the `routing` block (Hana pointed out that is a config deploy by Greg's team, not a flip); the next run's output is then identical to today's (tested in `tests/test_config_only.py`). Known limit: in 2.15.0 a suppressed deal also loses a promised callback. On today's routing input that's 0 (3 callbacks in 36 tasks, none on a listed deal; `measure callbacks` and a test check it); history doesn't record callbacks, so there's no weekly number. The code change below fixes it and waits for January. Change request: `notes/greg-change-request.md`.

**3. The code version (2.16.0, for January): off by default, one switch, rollback = switch off.** The switch and the empty suppression file already existed in routing 2.15.0 ("agreed in October"). I wired them in `plan.py`: with the switch off the output is identical (tested); promised callbacks are never suppressed; only JSON `true` turns it on (a string `"false"` in `env_overrides.json` would otherwise be truthy).

**4. The list only uses schedules that run past the freeze** (no end date, or ending after 7 January). Routing reads the file once per run and nobody can regenerate it during the freeze, so a schedule ending in December would leave a deal suppressed with nothing topping it up.

**5. Holdout: 20% of merchants, by a stable hash**, keep getting tasks. The readout compares the same kind of sold-out in both groups, so peak season hits both. See "How we'll know".

**6. Money: value = P(connect) x GP uplift x (1 - refund risk) - rep time.** Per band uplift from the table; P(connect) is the merchant's own history pulled towards the band rate; refund risk is the merchant's refunds over the last 6 months as a share of GP + refunds, doubled if the text says they can't take more customers (the 30-day GP misses refunds that come later). Rep time is 12 minutes at **£20/hour, an assumption**: Priya has no loaded cost; Dan said use it, but label it an assumption and make it easy to change. The page shows it as an assumption and lets you change it (`?rate=`), and `REP_HOURLY_COST_GBP` sets the default. At £20/h most band C and D tasks are worth less than the rep's time.

**7. Decision order** (`soldouts/decide.py`, first match wins; the page shows which rule decided): do-not-contact, promised callback, the rep's own mark, auto-replenish running (bands B–D), merchant said no, merchant says it tops up by itself, merchant away (only if said in the last 3 weeks), capacity or quality problem (then: talk capacity, not a bigger cap), Deal Alert link trouble (then: send login help, not a sales call), then the £ value, highest first.

**8. One customer complaint is not a flag.** A review or refund reason only counts with a second one, or if the rep or merchant said it too. A newer "wants more" from the merchant beats older negatives.

## How we'll know (the number for Dan)

- **Counted from day one:** tasks not created x 12 minutes. On the last 12 weeks the list would have removed ~88 tasks a week: **~18 rep hours a week** (`python3 -m soldouts.measure volume`).
- **What it costs:** GP lost by not calling those deals: ~£500 a year, worst case ~£1k (calls on auto-replenished deals add £0–3 each, and few of them were made).
- **What it could earn:** if the freed slots go to the next task on the list, between £0 (time goes elsewhere) and ~£50k a year (every slot becomes a band-A manual call). That's the honest range, and it's why I don't quote one number.
- **The real number:** `python3 -m soldouts.measure readout --start <first run>`. It compares listed deals (treated) with the 20% holdout on 14-day restock rate and 30-day GP, **minus the same gap in the 12 weeks before launch**, using only sold-outs whose 14 or 30 days are over. The hash split isn't perfectly balanced and the gap moves around: about 0 over the whole history, but in the same weeks last year (mid-November to early January) "treated" merchants restocked ~6 points less often and made ~£4 less GP per sold-out, with no change at all, after ~0 in the 12 weeks before. Subtracting the gap before launch takes out a steady difference, not a drift like that one, so the stop lines below are set wide enough for it.
- **Stop lines (numbers, as Greg asked):** restock more than **16 points** behind the holdout (average 14-day restock is ~75%), checked every Monday from week 6 (four weeks of sold-outs with their 14 days); 30-day GP per sold-out more than **£8** below the holdout (average ~£16), checked every Monday from week 8. `readout` prints `stop_now` and the reason.
- **How sure:** an A/A test on history (`scripts/aa_stop_lines.py`: a fake launch every day from July 2025 to August 2026, no change at all, with the Monday checks run as they would be live, up to week 16). These lines stopped 1% of the 400 launches by chance, and none of the 43 made between late October and the end of November last year. The worst no-change read at this time last year was 15 points and £7.54 behind, so tighter lines fire: at 12 points and £6, 40% of the launches made at this time of year would have been stopped with nothing wrong (at 10 points, my first draft, 51%). Averaged over the whole year those tighter lines looked fine (2–4% of single reads), which is why I first missed it. So: first restock check at Christmas (week 6 if it starts ~12 November), first GP check early January, firm by March. The holdout can only see a large drop; a small loss (the expected one is under £1 per sold-out) is far below what 20% of ~97 sold-outs a week can show. The 90% intervals `readout` prints only cover sampling noise, so they are too narrow; the A/A is the honest measure.

## Where AI is used, and how it's checked

- **In the product:** `soldouts/detect.py` sends one merchant's last 12 months of text (rep notes, Deal Alert replies, reviews, refund reasons; newest 60 items, cleaned: duplicates from the CRM replay removed, Windows-1252 mojibake fixed) to `claude-haiku-5-5` through the sandbox gateway, with a fixed JSON schema and thinking off. It must cite an item id and quote it word for word. **Code checks every quote against the cited item and drops it if it isn't there.** Cut-off answers (`stop_reason` not `end_turn`) are rejected, not parsed. Results are cached in `data/flags_llm.json`; the hosted tool reads new merchants in the background as they sell out, and shows the rules flags until then. Spend so far: about $0.02 of the $20 (about $0.0003 per merchant).
- **The AI never does the sums or makes the decision.** It produces flags + quotes; `decide.py` applies fixed rules.
- **Offline:** the rules backend (regular expressions, same output shape) runs with no network and no key. The LLM's answers are recorded in `data/flags_llm.json`; `--backend replay` re-checks them against the text with no network. The tests use both, plus a fake LLM for the failure cases (made-up quote, cut-off answer).
- **Checked against people:** see "Checked against a rep" below.
- **To build it:** I used Claude (chat + code) for analysis, code and drafts. Session export is in the submission.

## Checked against a rep

**Not done by hand-in.** On Tuesday I picked 10 merchants from Renee's book (R10, North H&B) and asked her "ring or leave, and why": a mix of ones the tool says to call, ones where the merchant has said no, two that top themselves up and one that isn't worth a call. Her answers hadn't arrived when I submitted. When they do, they go in `data/rep_labels.csv` and `python3 -m soldouts.evaluate data/rep_labels.csv` prints, for each merchant, Renee vs the tool with the LLM flags, the tool with the rules flags and the LLM's own one-line verdict, plus how many agree.

What is checked meanwhile: every quote the LLM gives is checked word for word against the item it cites, in code, and `--backend replay` re-runs that check on all 73 recorded answers offline. The tests feed it a made-up quote and a cut-off answer, and both are rejected. The AI never decides: it finds the words, and `decide.py` applies fixed rules. That shows the quotes are real, not that the judgement matches a rep's. That part still needs Renee.

## What it can't do yet

- Doesn't know a rep's real day: it ranks and explains, routing still builds the list.
- £ values are 30-day GP and use a guessed hourly cost. Long-term effects (a merchant who stops working with us) aren't in it.
- Refund risk is a proxy (past refund share), not a forecast.
- Rules backend is crude: it flags "auto top-up" in "auto top-up wasn't something she wanted". The LLM reads that correctly, but only for merchants we paid to run it on.
- Merchant marks live in the sandbox (and a local file); routing doesn't read them.
- The readout is noisy with a 20% holdout (see "How we'll know"); GP needs ~12 weeks + 30 days to be firm. Rep hours saved are counted from day one.
- The stop lines are tuned on one winter. If this winter's drift between the groups is bigger than last year's, a line could fire with nothing wrong; with a second winter of data I'd also compare against the same weeks last year.
- In the freeze (Monday to 7 January) nothing touches merchant config, so taking the list off is itself a change Greg would have to sign off. On the numbers the list puts about £90 of GP at risk over the whole freeze (worst case ~£160: the yearly figure x 8 weeks x 1.1, because last year's sold-outs ran ~10% above average in that window), and reps can still ring any listed deal.
- The holdout measures what we lose by not calling. It does **not** measure the upside: what reps do with the 18 freed hours lands on everyone's list, holdout merchants included.

## What I cut, and why

- **Suppressing every task worth less than the rep's time** (most C/D tasks at £20/h). Biggest prize, but changes reps' jobs and needs Dan/Renee to agree; also needs the real hourly cost. Next step.
- **Band A auto-replenish tasks.** Not enough data to be sure.
- **Automated cap raises** (Priya's second recommendation). Greg said not before January, and it's his team's call.
- **Routing reading marks or flags directly.** Would be a bigger change in a freeze week.
- **Running the LLM on all 3,000 merchants up front.** Cheap with Haiku (about $1), but not needed: the tool reads a merchant when it sells out. Worth doing before routing ever uses the flags.
- **A rep-level holdout** to measure the upside of the freed time. 24 reps are too few to see it in weeks.
- **Using Deal Alerts in the decision.** They help a bit (see above); not enough to change a call, and I ran out of time.
- **Rep accounts, offline mode in the app.** One sign-in page with one shared team password (or none, with `OPEN_SIGN_IN=1`, as on the hand-in copy), no per-rep logins.
