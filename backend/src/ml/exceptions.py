"""ML pipeline exceptions — strict path: no silent fallback."""


class MlModelNotFound(Exception):
    """Required model artifacts or directory missing."""


class MlFeatureMismatch(Exception):
    """Scaler, meta, or Keras input shape disagree on feature dimensions."""


class MlInsufficientRows(Exception):
    """Window has fewer rows than model lookback or invalid shape."""


class MlRuntimeError(Exception):
    """Inference or runtime validation failure."""
