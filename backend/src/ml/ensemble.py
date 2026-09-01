def combine(rule_signal: str, lstm: dict, agree_thr: float = 0.70, override_thr: float = 0.85) -> str:
    # rule_signal: BUY/SELL/HOLD
    # lstm["signal"]: BUY/SELL/HOLD with probs
    if rule_signal == "BUY" and lstm["up"] >= agree_thr:
        return "BUY"
    if rule_signal == "SELL" and lstm["down"] >= agree_thr:
        return "SELL"

    # optional override (strict)
    if lstm["signal"] == "BUY" and lstm["up"] >= override_thr and rule_signal != "SELL":
        return "BUY"
    if lstm["signal"] == "SELL" and lstm["down"] >= override_thr and rule_signal != "BUY":
        return "SELL"

    return rule_signal
