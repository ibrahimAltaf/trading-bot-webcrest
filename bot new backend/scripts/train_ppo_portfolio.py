#!/usr/bin/env python3
"""
Train PPO on MultiCoinTradingEnv (synthetic). Saves zip for RL_HYBRID / hybrid layer.

  pip install -r requirements-rl.txt
  set PYTHONPATH=.
  python scripts/train_ppo_portfolio.py --timesteps 100000 --out models/ppo_portfolio.zip
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timesteps", type=int, default=100_000)
    ap.add_argument("--out", default="models/ppo_portfolio.zip")
    args = ap.parse_args()

    try:
        from stable_baselines3 import PPO
        from stable_baselines3.common.vec_env import DummyVecEnv
    except ImportError as e:
        raise SystemExit(
            "Install RL deps: pip install -r requirements-rl.txt\n" + str(e)
        ) from e

    from src.rl.trading_env import MultiCoinTradingEnv  # noqa: E402

    def _make():
        return MultiCoinTradingEnv(max_steps=256)

    venv = DummyVecEnv([_make])
    model = PPO("MlpPolicy", venv, verbose=1)
    model.learn(total_timesteps=int(args.timesteps))

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(out.with_suffix("")))
    print(f"Saved PPO to {out.with_suffix('')}.zip")


if __name__ == "__main__":
    main()
