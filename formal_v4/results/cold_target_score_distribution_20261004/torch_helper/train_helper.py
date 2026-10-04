"""Training helper only; importing this module never starts training.

Caller owns data generation, balanced world sampling, calibration, validation,
checkpoint selection and final refitting. This helper saves every epoch.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import torch

try:
    from .score_distribution_model import JointScoreDistributionModel, masked_soft_cross_entropy
except ImportError:
    from score_distribution_model import JointScoreDistributionModel, masked_soft_cross_entropy

PUBLIC_KEYS = ("ht", "hn", "hm", "cn", "cm", "q")
DATASET_KEYS = (*PUBLIC_KEYS, "F", "b", "mask")


@dataclass(frozen=True)
class TrainConfig:
    epochs: int = 12
    learning_rate: float = 0.001
    weight_decay: float = 0.0001
    gradient_clip: float = 5.0
    seed: int = 949200
    batch_states: int = 8
    device: str = "cpu"
    preload_device: bool = True


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, torch.Tensor):
        return _json_value(value.detach().cpu().numpy())
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    return value


def _dataset_tensors(dataset: Mapping[str, Any]) -> dict[str, torch.Tensor]:
    # Accept the long alias but keep the canonical dataset key b in checkpoints.
    values = dict(dataset)
    if "b" not in values and "band" in values:
        values["b"] = values["band"]
    missing = [key for key in DATASET_KEYS if key not in values]
    if missing:
        raise ValueError(f"dataset is missing required keys: {missing}")
    tensors: dict[str, torch.Tensor] = {}
    for key in DATASET_KEYS:
        dtype = torch.long if key == "b" else torch.bool if key == "mask" else torch.float32
        raw = torch.as_tensor(values[key]).detach().cpu()
        if key == "b":
            valid = torch.as_tensor(values["mask"], dtype=torch.bool)
            valid_band = raw[valid]
            if not bool(torch.isfinite(valid_band).all()) or bool((valid_band != valid_band.long()).any()):
                raise ValueError("valid b labels must be finite integers before casting")
            # Padded labels may be arbitrary/NaN; make them safe before casting.
            raw = torch.where(valid, raw, 0)
        tensors[key] = raw.to(dtype=dtype)
    states = tensors["q"].shape[0]
    if states <= 0:
        raise ValueError("dataset must contain at least one state")
    if any(tensor.shape[0] != states for tensor in tensors.values()):
        raise ValueError("all dataset arrays must have the same state axis")
    q = tensors["q"]
    if q.ndim != 3 or q.shape[-1] != 51:
        raise ValueError("q must have shape [N,Q,51]")
    expected = {
        "ht": (states, 8, 16, 24), "hn": (states, 8, 129),
        "hm": (states, 8, 16), "cn": (states, 129), "cm": (states, 16),
        "F": tuple(q.shape[:2]), "b": tuple(q.shape[:2]), "mask": tuple(q.shape[:2]),
    }
    for key, shape in expected.items():
        if tuple(tensors[key].shape) != shape:
            raise ValueError(f"{key} must have shape {shape}")
    return tensors


def train_model(
    dataset: Mapping[str, Any],
    output_dir: str | Path,
    context_mode: str = "fullhistory",
    config: TrainConfig | None = None,
    checkpoint: Callable[[JointScoreDistributionModel, int], Mapping[str, Any] | None] | None = None,
) -> tuple[JointScoreDistributionModel, list[dict[str, Any]]]:
    """Train on supplied arrays and save every epoch, without choosing a winner.

    Dataset keys: ht/hn/hm/cn/cm/q (float32), F (float32), b (integer),
    mask (boolean). Loss first averages valid queries per state, then averages
    nonempty states. Provide equal state counts per world; every state appears
    once per uniformly shuffled epoch. By default all arrays are preloaded to
    the selected device, keeping the permutation generator on CPU.
    callback checkpoint(model, epoch), with epochs numbered 1..12 by default,
    runs under inference_mode and may return JSON-compatible cal/val metrics.
    Callback gets no training labels and owns the separate evaluation arrays.
    """
    config = config or TrainConfig()
    if config.epochs <= 0 or config.batch_states <= 0:
        raise ValueError("epochs and batch_states must be positive")
    random.seed(config.seed)
    np.random.seed(config.seed)
    torch.manual_seed(config.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(config.seed)
    tensors = _dataset_tensors(dataset)
    device = torch.device(config.device)
    if config.preload_device:
        tensors = {key: tensor.to(device) for key, tensor in tensors.items()}
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    log_path = destination / "training_log.jsonl"
    if log_path.exists():
        raise FileExistsError(f"refusing to overwrite an existing training log: {log_path}")
    (destination / "train_config.json").write_text(
        json.dumps({"context_mode": context_mode, **asdict(config)}, indent=2) + "\n",
        encoding="utf-8",
    )
    model = JointScoreDistributionModel(context_mode).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    permutation_generator = torch.Generator().manual_seed(config.seed)
    records: list[dict[str, Any]] = []
    for epoch in range(1, config.epochs + 1):
        epoch_started = time.perf_counter()
        model.train()
        order = torch.randperm(tensors["q"].shape[0], generator=permutation_generator)
        total_loss, valid_queries, valid_states, updates, skipped = 0.0, 0, 0, 0, 0
        for start in range(0, len(order), config.batch_states):
            indices = order[start : start + config.batch_states]
            if config.preload_device:
                indices = indices.to(device)
                batch = {key: tensor.index_select(0, indices) for key, tensor in tensors.items()}
            else:
                batch = {key: tensor.index_select(0, indices).to(device) for key, tensor in tensors.items()}
            count = int(batch["mask"].sum().item())
            if count == 0:
                skipped += 1
                continue
            optimizer.zero_grad(set_to_none=True)
            logits = model(*(batch[key] for key in PUBLIC_KEYS))
            loss = masked_soft_cross_entropy(
                logits, batch["F"], batch["b"], batch["mask"], state_balanced=True
            )
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError(f"non-finite training loss at epoch {epoch}")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), config.gradient_clip)
            optimizer.step()
            state_count = int(batch["mask"].any(dim=1).sum().item())
            total_loss += float(loss.detach()) * state_count
            valid_queries += count
            valid_states += state_count
            updates += 1
        if updates == 0:
            raise ValueError("dataset has no valid query labels")
        model.eval()
        callback_metrics: Mapping[str, Any] | None = None
        if checkpoint is not None:
            with torch.inference_mode():
                callback_metrics = checkpoint(model, epoch)
        export_path = model.export_npz(destination / f"epoch_{epoch:02d}.npz")
        checkpoint_path = destination / f"epoch_{epoch:02d}.pt"
        torch.save(
            {"epoch": epoch, "context_mode": context_mode, "config": asdict(config),
             "model_state_dict": model.state_dict(), "optimizer_state_dict": optimizer.state_dict()},
            checkpoint_path,
        )
        record = {
            "epoch": epoch, "train_soft_ce": total_loss / valid_states,
            "loss_reduction": "mean_of_nonempty_state_query_means",
            "valid_queries": valid_queries, "valid_states": valid_states,
            "optimizer_updates": updates, "epoch_elapsed_seconds": time.perf_counter() - epoch_started,
            "skipped_empty_batches": skipped, "npz_path": str(export_path),
            "checkpoint_path": str(checkpoint_path),
            "checkpoint_metrics": _json_value(callback_metrics or {}),
        }
        serialized = json.dumps(record, allow_nan=False)
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(serialized + "\n")
        records.append(record)
        print(
            f"{context_mode} epoch={epoch}/{config.epochs} "
            f"soft_ce={record['train_soft_ce']:.6f} "
            f"elapsed_s={record['epoch_elapsed_seconds']:.3f}",
            flush=True,
        )
    return model, records


def load_world_arrays(paths: list[str | Path]) -> dict[str, np.ndarray]:
    """Load caller-supplied world files; reject unequal numbers of states."""
    worlds: list[dict[str, np.ndarray]] = []
    for path in paths:
        with np.load(path, allow_pickle=False) as archive:
            worlds.append({key: archive[key].copy() for key in DATASET_KEYS})
    if not worlds:
        raise ValueError("at least one world NPZ is required")
    sizes = [world["q"].shape[0] for world in worlds]
    if len(set(sizes)) != 1:
        raise ValueError("world NPZs must have equal state counts; caller owns balancing")
    return {key: np.concatenate([world[key] for world in worlds], axis=0) for key in DATASET_KEYS}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", nargs="+", required=True, help="caller-supplied equal-size world NPZs")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--context-mode", choices=("fullhistory", "current-public-only"), default="fullhistory")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--no-preload-device", action="store_true")
    args = parser.parse_args()
    _, records = train_model(
        load_world_arrays(args.data), args.output_dir, args.context_mode,
        TrainConfig(device=args.device, preload_device=not args.no_preload_device),
    )
    print(json.dumps({"epochs_saved": len(records), "last": records[-1]}, allow_nan=False))


if __name__ == "__main__":
    main()
