from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import tensorflow as tf


def build_model(lookback: int, n_features: int) -> tf.keras.Model:
    """
    Improved LSTM model:
    - Deeper (3-layer) with BatchNormalization for better generalization
    - L2 regularization to reduce overfitting
    """
    reg = tf.keras.regularizers.l2(1e-4)
    model = tf.keras.Sequential(
        [
            tf.keras.layers.Input(shape=(lookback, n_features)),
            tf.keras.layers.LSTM(128, return_sequences=True, kernel_regularizer=reg),
            tf.keras.layers.BatchNormalization(),
            tf.keras.layers.Dropout(0.3),
            tf.keras.layers.LSTM(64, return_sequences=True, kernel_regularizer=reg),
            tf.keras.layers.BatchNormalization(),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.LSTM(32, return_sequences=False),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.Dense(32, activation="relu"),
            tf.keras.layers.Dense(3, activation="softmax"),
        ]
    )
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model


def compute_class_weights(y: np.ndarray) -> dict:
    """
    Compute balanced class weights to handle SELL/BUY imbalance.
    Financial data is typically 70-80% HOLD, so weighting rare classes is critical.
    """
    from collections import Counter

    counts = Counter(y.tolist())
    total = len(y)
    n_classes = 3
    weights = {}
    for cls in range(n_classes):
        count = counts.get(cls, 1)
        weights[cls] = total / (n_classes * count)
    return weights


def train(model_dir: str = "models/lstm_v1", epochs: int = 50, batch_size: int = 32):
    model_dir = Path(model_dir)
    ds = np.load(model_dir / "dataset.npz")

    Xtr, ytr = ds["Xtr"], ds["ytr"]
    Xva, yva = ds["Xva"], ds["yva"]

    meta = json.loads((model_dir / "meta.json").read_text())
    lookback = int(meta["lookback"])
    n_features = int(meta["n_features"])

    model = build_model(lookback, n_features)

    # Compute class weights to handle imbalanced HOLD/BUY/SELL distribution
    class_weights = compute_class_weights(ytr)
    print(f"Class weights: {class_weights}")

    cb = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=7, restore_best_weights=True
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=4, min_lr=1e-6
        ),
    ]

    hist = model.fit(
        Xtr,
        ytr,
        validation_data=(Xva, yva),
        epochs=epochs,
        batch_size=batch_size,
        callbacks=cb,
        class_weight=class_weights,  # key improvement for imbalanced classes
        verbose=1,
    )

    model.save(model_dir / "model.keras")

    metrics = {
        "train_acc": float(hist.history["accuracy"][-1]),
        "val_acc": float(hist.history["val_accuracy"][-1]),
        "train_loss": float(hist.history["loss"][-1]),
        "val_loss": float(hist.history["val_loss"][-1]),
        "epochs_trained": len(hist.history["loss"]),
        "class_weights": class_weights,
    }
    (model_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    print(train())
