"""Production LSTM architecture (configurable for tuning)."""
from __future__ import annotations

from typing import Any, Dict, Optional

import tensorflow as tf


def build_production_lstm(
    lookback: int,
    n_features: int,
    *,
    lstm_units_1: int = 128,
    lstm_units_2: int = 64,
    dense_units: int = 64,
    dropout: float = 0.2,
    learning_rate: float = 1e-3,
) -> tf.keras.Model:
    """
    Spec: LSTM(128, return_sequences=True) -> Dropout -> LSTM(64) -> Dense(64,relu) -> Dense(3, softmax)
    """
    model = tf.keras.Sequential(
        [
            tf.keras.layers.Input(shape=(lookback, n_features)),
            tf.keras.layers.LSTM(
                lstm_units_1, return_sequences=True, name="lstm_1"
            ),
            tf.keras.layers.Dropout(dropout),
            tf.keras.layers.LSTM(lstm_units_2, name="lstm_2"),
            tf.keras.layers.Dense(dense_units, activation="relu", name="dense_1"),
            tf.keras.layers.Dense(3, activation="softmax", name="out"),
        ]
    )
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model


def build_model_from_hyperparams(
    lookback: int,
    n_features: int,
    hp: Dict[str, Any],
) -> tf.keras.Model:
    return build_production_lstm(
        lookback,
        n_features,
        lstm_units_1=int(hp.get("lstm_units_1", 128)),
        lstm_units_2=int(hp.get("lstm_units_2", 64)),
        dense_units=int(hp.get("dense_units", 64)),
        dropout=float(hp.get("dropout", 0.2)),
        learning_rate=float(hp.get("learning_rate", 1e-3)),
    )
