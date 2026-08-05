"""
Bayesian A/B testing engine — replaces Welch's t-test for policy attribution.

Uses Beta-Binomial conjugacy for pass/fail task outcomes:
  P(θ|data) = Beta(α_prior + successes, β_prior + failures)

Advantages over t-test:
- Works on small samples (n<10)
- No normality assumption
- Direct probability statements: "85% chance policy B is better"
- Natural sequential updating
- No Type I/II error inflation on sparse data
"""

import math
from typing import Optional


def beta_probability_of_superiority(
    alpha_a: float, beta_a: float,
    alpha_b: float, beta_b: float,
    samples: int = 10000,
) -> float:
    """Probability that treatment B is superior to control A.
    
    Uses Monte Carlo sampling from Beta posteriors.
    P(θ_B > θ_A) = ∫∫ I(θ_B > θ_A) Beta(θ_A) Beta(θ_B) dθ_A dθ_B
    
    Args:
        alpha_a, beta_a: Posterior parameters for control (successes, failures)
        alpha_b, beta_b: Posterior parameters for treatment
        samples: Monte Carlo samples (default 10K, good to ~0.01 precision)
    
    Returns:
        Probability (0-1) that B outperforms A.
    """
    import random
    random.seed(42)  # Deterministic for reproducibility
    
    superior_count = 0
    for _ in range(samples):
        theta_a = random.betavariate(alpha_a, beta_a)
        theta_b = random.betavariate(alpha_b, beta_b)
        if theta_b > theta_a:
            superior_count += 1
    
    return superior_count / samples


def expected_loss(
    alpha_a: float, beta_a: float,
    alpha_b: float, beta_b: float,
    samples: int = 10000,
) -> float:
    """Expected loss if we choose B over A when A is actually better.
    
    E[loss] = ∫∫ max(0, θ_A - θ_B) Beta(θ_A) Beta(θ_B) dθ_A dθ_B
    
    Lower is better. <0.01 is negligible risk.
    """
    import random
    random.seed(42)
    
    total_loss = 0.0
    for _ in range(samples):
        theta_a = random.betavariate(alpha_a, beta_a)
        theta_b = random.betavariate(alpha_b, beta_b)
        total_loss += max(0, theta_a - theta_b)
    
    return total_loss / samples


class BayesianAB:
    """Bayesian A/B test for policy effectiveness.
    
    Uses Beta-Binomial model with uninformative prior Beta(1, 1).
    
    Usage:
        ab = BayesianAB()
        ab.add_control(success=True)   # Record control outcome
        ab.add_treatment(success=False) # Record treatment outcome
        result = ab.evaluate()
        # result['probability_b_better'] = 0.85
        # result['recommendation'] = 'promote' | 'revert' | 'extend'
    """
    
    def __init__(self, prior_alpha: float = 1.0, prior_beta: float = 1.0,
                 threshold: float = 0.90, loss_threshold: float = 0.01):
        """
        Args:
            prior_alpha, prior_beta: Beta prior parameters (1,1 = uniform)
            threshold: Probability needed to declare winner (0.90 = 90% confident)
            loss_threshold: Maximum acceptable expected loss for promotion
        """
        self.prior_alpha = prior_alpha
        self.prior_beta = prior_beta
        self.threshold = threshold
        self.loss_threshold = loss_threshold
        
        self.control_successes = 0
        self.control_failures = 0
        self.treatment_successes = 0
        self.treatment_failures = 0
    
    def add_control(self, success: bool):
        if success: self.control_successes += 1
        else: self.control_failures += 1
    
    def add_treatment(self, success: bool):
        if success: self.treatment_successes += 1
        else: self.treatment_failures += 1
    
    @property
    def control_alpha(self): return self.prior_alpha + self.control_successes
    
    @property
    def control_beta(self): return self.prior_beta + self.control_failures
    
    @property
    def treatment_alpha(self): return self.prior_alpha + self.treatment_successes
    
    @property
    def treatment_beta(self): return self.prior_beta + self.treatment_failures
    
    @property
    def control_rate(self):
        total = self.control_successes + self.control_failures
        return self.control_successes / max(total, 1)
    
    @property
    def treatment_rate(self):
        total = self.treatment_successes + self.treatment_failures
        return self.treatment_successes / max(total, 1)
    
    def evaluate(self) -> dict:
        """Evaluate the A/B test and make a recommendation.
        
        Returns:
            dict with probability, expected_loss, effect_size, recommendation
        """
        n_control = self.control_successes + self.control_failures
        n_treatment = self.treatment_successes + self.treatment_failures
        
        if n_control < 3 or n_treatment < 3:
            return {
                "recommendation": "extend",
                "reason": f"Insufficient data ({n_control} control, {n_treatment} treatment)",
                "probability_b_better": 0.5,
                "expected_loss": 1.0,
                "control_rate": self.control_rate,
                "treatment_rate": self.treatment_rate,
            }
        
        prob = beta_probability_of_superiority(
            self.control_alpha, self.control_beta,
            self.treatment_alpha, self.treatment_beta,
        )
        
        loss = expected_loss(
            self.control_alpha, self.control_beta,
            self.treatment_alpha, self.treatment_beta,
        )
        
        effect = self.treatment_rate - self.control_rate
        
        if prob >= self.threshold:
            recommendation = "promote"
            reason = f"Treatment superior with {prob:.1%} probability"
        elif prob <= (1 - self.threshold):
            recommendation = "revert"
            reason = f"Treatment inferior with {(1-prob):.1%} probability"
        elif loss < self.loss_threshold:
            recommendation = "promote"
            reason = f"Negligible expected loss ({loss:.4f}) — safe to promote"
        else:
            recommendation = "extend"
            reason = f"Inconclusive ({prob:.1%} prob, {loss:.4f} loss) — extend observation"
        
        return {
            "recommendation": recommendation,
            "reason": reason,
            "probability_b_better": round(prob, 4),
            "expected_loss": round(loss, 4),
            "effect_size": round(effect, 4),
            "control_rate": round(self.control_rate, 4),
            "treatment_rate": round(self.treatment_rate, 4),
            "control_samples": n_control,
            "treatment_samples": n_treatment,
            "control_posterior": f"Beta({self.control_alpha:.0f}, {self.control_beta:.0f})",
            "treatment_posterior": f"Beta({self.treatment_alpha:.0f}, {self.treatment_beta:.0f})",
        }


# ── CLI ──
def main():
    import argparse
    p = argparse.ArgumentParser(description="Bayesian A/B test for policy evaluation")
    p.add_argument("--control-successes", type=int, default=0)
    p.add_argument("--control-failures", type=int, default=0)
    p.add_argument("--treatment-successes", type=int, default=0)
    p.add_argument("--treatment-failures", type=int, default=0)
    p.add_argument("--threshold", type=float, default=0.90)
    p.add_argument("--demo", action="store_true", help="Run demo scenarios")
    args = p.parse_args()
    
    if args.demo:
        demos = [
            ("Clear winner (large sample)", 50, 50, 75, 25),
            ("Clear winner (small sample)", 5, 5, 8, 2),
            ("Too close to call", 10, 10, 12, 8),
            ("Treatment is worse", 20, 5, 10, 15),
            ("Tiny sample (inconclusive)", 2, 1, 2, 0),
        ]
        
        for label, cs, cf, ts, tf in demos:
            ab = BayesianAB()
            for _ in range(cs): ab.add_control(True)
            for _ in range(cf): ab.add_control(False)
            for _ in range(ts): ab.add_treatment(True)
            for _ in range(tf): ab.add_treatment(False)
            result = ab.evaluate()
            icon = {"promote": "📈", "revert": "📉", "extend": "⏸"}[result["recommendation"]]
            print(f"\n{icon} {label}")
            print(f"   Control: {ab.control_rate:.0%} ({cs+cf} samples)")
            print(f"   Treatment: {ab.treatment_rate:.0%} ({ts+tf} samples)")
            print(f"   P(B>A): {result['probability_b_better']:.1%}")
            print(f"   E[loss]: {result['expected_loss']:.4f}")
            print(f"   → {result['recommendation']}: {result['reason']}")
        return
    
    ab = BayesianAB(threshold=args.threshold)
    for _ in range(args.control_successes): ab.add_control(True)
    for _ in range(args.control_failures): ab.add_control(False)
    for _ in range(args.treatment_successes): ab.add_treatment(True)
    for _ in range(args.treatment_failures): ab.add_treatment(False)
    
    result = ab.evaluate()
    print(f"Recommendation: {result['recommendation']}")
    print(f"P(B>A): {result['probability_b_better']:.1%}")
    print(f"E[loss]: {result['expected_loss']:.4f}")
    print(f"Effect: {result['effect_size']:+.1%}")


if __name__ == "__main__":
    main()
