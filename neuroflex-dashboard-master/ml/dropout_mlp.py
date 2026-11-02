"""Small NumPy MLP classifier with inverted dropout and weighted Adam."""

from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin


class DropoutMLPClassifier(ClassifierMixin, BaseEstimator):
    """One-hidden-layer classifier used by the frozen object-count model."""

    def __init__(
        self,
        hidden_units=64,
        dropout_rate=0.25,
        learning_rate=0.001,
        epochs=70,
        batch_size=128,
        l2=1e-4,
        random_state=42,
    ):
        self.hidden_units = hidden_units
        self.dropout_rate = dropout_rate
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.batch_size = batch_size
        self.l2 = l2
        self.random_state = random_state

    @staticmethod
    def _softmax(scores):
        scores = scores - scores.max(axis=1, keepdims=True)
        exp_scores = np.exp(scores)
        return exp_scores / exp_scores.sum(axis=1, keepdims=True)

    @staticmethod
    def _dense(X):
        return np.asarray(X.toarray() if hasattr(X, "toarray") else X, dtype=np.float64)

    def fit(self, X, y):
        if not 0 <= self.dropout_rate < 1:
            raise ValueError("dropout_rate debe estar entre 0 y 1")
        X, y = self._dense(X), np.asarray(y)
        self.classes_, encoded = np.unique(y, return_inverse=True)
        n_samples, n_features = X.shape
        n_classes = len(self.classes_)
        if n_classes < 2:
            raise ValueError("Se necesitan al menos dos clases")

        self.n_features_in_ = n_features
        self.rng_ = np.random.default_rng(self.random_state)
        self.W_ = self.rng_.normal(
            0, np.sqrt(2 / n_features), (n_features, self.hidden_units)
        )
        self.b_ = np.zeros(self.hidden_units)
        self.V_ = self.rng_.normal(
            0, np.sqrt(1 / self.hidden_units), (self.hidden_units, n_classes)
        )
        self.c_ = np.zeros(n_classes)
        params = [self.W_, self.b_, self.V_, self.c_]
        first_moment = [np.zeros_like(param) for param in params]
        second_moment = [np.zeros_like(param) for param in params]
        counts = np.bincount(encoded, minlength=n_classes)
        class_weights = n_samples / (n_classes * counts)
        onehot = np.eye(n_classes)[encoded]
        step = 0

        for _ in range(self.epochs):
            order = self.rng_.permutation(n_samples)
            for start in range(0, n_samples, self.batch_size):
                ids = order[start : start + self.batch_size]
                xb, yb = X[ids], onehot[ids]
                weights = class_weights[encoded[ids]]
                z = xb @ self.W_ + self.b_
                hidden = np.maximum(z, 0)
                mask = (self.rng_.random(hidden.shape) >= self.dropout_rate) / (
                    1 - self.dropout_rate
                )
                hidden *= mask
                delta = (
                    (self._softmax(hidden @ self.V_ + self.c_) - yb)
                    * weights[:, None]
                    / weights.sum()
                )
                dz = (delta @ self.V_.T) * mask * (z > 0)
                grads = [
                    xb.T @ dz + self.l2 * self.W_,
                    dz.sum(axis=0),
                    hidden.T @ delta + self.l2 * self.V_,
                    delta.sum(axis=0),
                ]
                step += 1
                for param, grad, m, v in zip(
                    params, grads, first_moment, second_moment
                ):
                    m[:] = 0.9 * m + 0.1 * grad
                    v[:] = 0.999 * v + 0.001 * grad**2
                    mhat = m / (1 - 0.9**step)
                    vhat = v / (1 - 0.999**step)
                    param -= self.learning_rate * mhat / (np.sqrt(vhat) + 1e-8)
        del self.rng_
        return self

    def predict_proba(self, X):
        hidden = np.maximum(self._dense(X) @ self.W_ + self.b_, 0)
        return self._softmax(hidden @ self.V_ + self.c_)

    def predict(self, X):
        return self.classes_[self.predict_proba(X).argmax(axis=1)]
