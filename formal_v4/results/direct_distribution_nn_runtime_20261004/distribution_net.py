"""Single physical-factor/band PMF, with exactly matching NumPy inference.

This module knows neither future truth nor candidate selection. Its callers own
public data construction, split locks, calibration and the finite decision gate.
"""
from __future__ import annotations

import json
import numpy as np

K = 64
QUERY_DIM = 51
TOKEN_DIM = 24
NOTICE_DIM = 129
META_DIM = 16
OUTPUT_DIM = 3 * (K + 1)
STATE_KEYS = ("past_tokens", "past_mask", "past_notice", "past_meta",
              "current_notice", "current_meta")


def make_torch_net(with_history=True):
    import torch
    from torch import nn

    class DistributionNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.with_history = bool(with_history)
            if self.with_history:
                self.token1 = nn.Linear(24, 32)
                self.token2 = nn.Linear(32, 32)
            self.context1 = nn.Linear(1817 if self.with_history else 145, 64)
            self.context2 = nn.Linear(64, 32)
            self.query1 = nn.Linear(83, 32)
            self.joint = nn.Linear(32, OUTPUT_DIM)

        def encode_state(self, batch):
            current = torch.cat((batch["current_notice"], batch["current_meta"]), -1)
            if self.with_history:
                token = torch.relu(self.token2(torch.relu(self.token1(batch["past_tokens"]))))
                mask = batch["past_mask"].to(dtype=token.dtype).unsqueeze(-1)
                masked = token * mask
                mean = masked.sum(-2) / mask.sum(-2).clamp_min(1.)
                # Tokens follow ReLU, so zero is also the empty-pool value.
                maximum = masked.max(-2).values
                past = torch.cat((mean, maximum, batch["past_notice"], batch["past_meta"]), -1)
                state = torch.cat((past.flatten(1), current), -1)
            else:
                state = current
            return torch.relu(self.context2(torch.relu(self.context1(state))))

        def from_context(self, context, query, query_state):
            encoded = torch.cat((context[query_state], query), -1)
            return self.joint(torch.relu(self.query1(encoded)))

        def forward(self, batch, query, query_state):
            return self.from_context(self.encode_state(batch), query, query_state)

    return DistributionNet()


def torch_soft_ce(logits, physical_factor, band, temperature=1.):
    """Return one loss per query; caller supplies world/state balancing."""
    import torch
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    if bool(torch.any(~torch.isfinite(physical_factor))) or bool(torch.any(
            (physical_factor < 0) | (physical_factor > 1))):
        raise ValueError("physical F must be finite in [0,1]")
    if bool(torch.any((band < 0) | (band >= 3))):
        raise ValueError("band must have DARK/BRIGHT/BACKUP index 0..2")
    coordinate = physical_factor * K
    left = coordinate.floor().to(torch.long).clamp_max(K - 1)
    fraction = coordinate - left
    index = band.to(torch.long) * (K + 1) + left
    logp = torch.log_softmax(logits / temperature, -1)
    rows = torch.arange(len(index), device=index.device)
    return -((1 - fraction) * logp[rows, index] + fraction * logp[rows, index + 1])


def numpy_soft_ce(logits, physical_factor, band, temperature=1.):
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    factor = np.asarray(physical_factor)
    band = np.asarray(band, dtype=np.int64)
    if np.any(~np.isfinite(factor)) or np.any((factor < 0) | (factor > 1)):
        raise ValueError("physical F must be finite in [0,1]")
    if np.any((band < 0) | (band >= 3)):
        raise ValueError("band must have index 0..2")
    z = np.asarray(logits) / temperature
    z = z - z.max(-1, keepdims=True)
    logp = z - np.log(np.exp(z).sum(-1, keepdims=True))
    coordinate = factor * K
    left = np.minimum(np.floor(coordinate).astype(np.int64), K - 1)
    fraction = coordinate - left
    index = band * (K + 1) + left
    rows = np.arange(len(index))
    return -((1 - fraction) * logp[rows, index] + fraction * logp[rows, index + 1])


def export_numpy(net, path, metadata=None):
    extra = dict(metadata or {})
    extra.update(schema="physical-joint195-v1", with_history=net.with_history,
                 query_dim=51, token_dim=24, notice_dim=129, meta_dim=16,
                 factor_knots=65, bands=["DARK", "BRIGHT", "BACKUP"])
    weights = {key: value.detach().cpu().numpy().astype(np.float32)
               for key, value in net.state_dict().items()}
    weights["__meta__"] = np.frombuffer(json.dumps(extra, sort_keys=True).encode(), dtype=np.uint8)
    np.savez_compressed(path, **weights)


class NumpyDistributionNet:
    def __init__(self, path):
        with np.load(path, allow_pickle=False) as stored:
            self.metadata = json.loads(stored["__meta__"].tobytes())
            self.weights = {key: stored[key].copy() for key in stored.files if key != "__meta__"}
        self.with_history = self.metadata["with_history"]

    def linear(self, key, value):
        return value @ self.weights[key + ".weight"].T + self.weights[key + ".bias"]

    def encode_state(self, batch):
        current = np.concatenate((batch["current_notice"], batch["current_meta"]), -1).astype(np.float32)
        if self.with_history:
            token = np.maximum(0., self.linear("token1", np.asarray(batch["past_tokens"], dtype=np.float32)))
            token = np.maximum(0., self.linear("token2", token))
            mask = np.asarray(batch["past_mask"], dtype=np.float32)[..., None]
            masked = token * mask
            mean = masked.sum(-2) / np.maximum(1., mask.sum(-2))
            maximum = masked.max(-2)
            past = np.concatenate((mean, maximum, batch["past_notice"], batch["past_meta"]), -1)
            state = np.concatenate((past.reshape(len(current), -1), current), -1).astype(np.float32)
        else:
            state = current
        return np.maximum(0., self.linear("context2", np.maximum(0., self.linear("context1", state))))

    def from_context(self, context, query, query_state, temperature=1., logits=False):
        if temperature <= 0:
            raise ValueError("temperature must be positive")
        combined = np.concatenate((context[np.asarray(query_state, dtype=np.int64)],
                                   np.asarray(query, dtype=np.float32)), -1)
        raw = self.linear("joint", np.maximum(0., self.linear("query1", combined)))
        if logits:
            return raw
        scaled = raw / np.float32(temperature)
        scaled -= scaled.max(-1, keepdims=True)
        prob = np.exp(scaled)
        prob /= prob.sum(-1, keepdims=True)
        return prob.reshape((-1, 3, K + 1))

    def predict(self, batch, query, query_state, temperature=1., logits=False):
        return self.from_context(self.encode_state(batch), query, query_state, temperature, logits)
