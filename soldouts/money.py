"""What a sold-out is worth chasing. Plain arithmetic, no AI.

value = P(connect) x GP uplift of a connected call x (1 - refund risk) - rep time

- GP uplift: per size band, from scripts/estimate_uplift.py (same merchant, called vs left alone,
  30 days after the sell-out, already net of refunds inside those 30 days).
- P(connect): the merchant's own history of restock calls that connected, shrunk to the band rate.
- Refund risk: refunds that land after the 30-day window. Proxy: the merchant's refund share of
  (GP + refunds) over its last 6 months. Doubled if the notes flag a capacity problem, because
  selling more than a merchant can serve is where refunds come from.
- Rep time: minutes per task x loaded hourly cost.
"""
from dataclasses import dataclass

from soldouts import config


@dataclass
class Worth:
    gp_if_connected: float
    p_connect: float
    refund_risk: float
    rep_cost: float

    @property
    def expected_gp(self):
        return self.p_connect * self.gp_if_connected * (1 - self.refund_risk)

    @property
    def value(self):
        return round(self.expected_gp - self.rep_cost, 2)

    def explain(self):
        return (f"{self.p_connect:.0%} chance to connect x £{self.gp_if_connected:.2f} GP"
                f" x (1 - {self.refund_risk:.0%} refund risk) - £{self.rep_cost:.2f} rep time"
                f" = £{self.value:.2f}")


def rep_cost(minutes=config.MINUTES_PER_TASK, hourly=None):
    hourly = config.REP_HOURLY_COST_GBP if hourly is None else hourly
    return round(minutes / 60 * hourly, 2)


def shrunk_rate(successes, trials, prior_rate, prior_weight=5):
    """Merchant's own rate pulled towards the band rate when it has few attempts."""
    return (successes + prior_rate * prior_weight) / (trials + prior_weight)


def refund_risk(refunds_gbp, gp_gbp, capacity_flag=False):
    total = refunds_gbp + gp_gbp
    share = refunds_gbp / total if total > 0 else 0.0
    if capacity_flag:
        share *= 2
    return min(max(share, 0.0), 0.9)


def worth(band, uplift, p_connect, refund_share, hourly=None):
    gp = uplift["bands"][band]["uplift_per_connected_call_gbp"]
    return Worth(gp_if_connected=gp, p_connect=p_connect, refund_risk=refund_share, rep_cost=rep_cost(hourly=hourly))
