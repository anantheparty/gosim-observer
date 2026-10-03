"""Tiny DeepSets action value network with an independent NumPy runtime.

Importing the public feature/runtime path never requires Torch or CUDA. This
module imports Torch optionally, and only construction/training needs it.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from research.structured_student_features import FEATURE_SCHEMA, PublicFeatures
from research.structured_student_runtime import NumpyValue, normalized as _normalized

try:
    import torch
    from torch import nn
except ImportError:
    torch, nn = None, None


def _moments(rows):
    joined = np.concatenate(rows, axis=0).astype(np.float64)
    return joined.mean(0).astype(np.float32), np.maximum(joined.std(0), 1e-3).astype(np.float32)


def fit_normalizer(features):
    """Fit on unique TRAINING STATE GROUPS; never on validation/test target rows."""
    target_mean,target_std = _moments([f.target_nodes for f in features])
    edge_mean,edge_std = _moments([a.edges for f in features for a in f.actions])
    global_mean,global_std = _moments([f.global_features[None] for f in features])
    scalar_mean,scalar_std = _moments([a.scalars[None] for f in features for a in f.actions])
    return dict(target_mean=target_mean,target_std=target_std,edge_mean=edge_mean,edge_std=edge_std,
                global_mean=global_mean,global_std=global_std,scalar_mean=scalar_mean,scalar_std=scalar_std)


def identity_normalizer(features):
    return {name+suffix: (np.zeros(size,np.float32) if suffix=="_mean" else np.ones(size,np.float32))
            for name,size in (("target",features.target_nodes.shape[1]),("edge",features.actions[0].edges.shape[1]),
                              ("global",features.global_features.size),("scalar",features.actions[0].scalars.size))
            for suffix in ("_mean","_std")}


if nn is not None:
    class StructuredValue(nn.Module):
        """Shared target/edge encoders; fixed mean/max/sqrt-count sum pools."""
        def __init__(self, target_dim, edge_dim, global_dim, scalar_dim, latent=8, hidden=16, output_dim=6):
            super().__init__()
            self.config = dict(target_dim=target_dim,edge_dim=edge_dim,global_dim=global_dim,
                               scalar_dim=scalar_dim,latent=latent,hidden=hidden,output_dim=output_dim)
            self.target = nn.Sequential(nn.Linear(target_dim,hidden),nn.ReLU(),nn.Linear(hidden,latent),nn.ReLU())
            self.edge = nn.Sequential(nn.Linear(latent+edge_dim,hidden),nn.ReLU(),nn.Linear(hidden,latent),nn.ReLU())
            self.head = nn.Sequential(nn.Linear(6*latent+global_dim+scalar_dim,hidden),nn.ReLU(),nn.Linear(hidden,output_dim))

        @staticmethod
        def pool(rows):
            if rows.shape[0] == 0:
                return rows.new_zeros(3*rows.shape[1])
            return torch.cat((rows.mean(0),rows.max(0).values,rows.sum(0)/np.sqrt(rows.shape[0])))

        def forward_group(self, features: PublicFeatures, normalizer):
            device = next(self.parameters()).device
            to_tensor = lambda array: torch.as_tensor(array,device=device,dtype=torch.float32)
            targets = self.target(to_tensor(_normalized(features.target_nodes,normalizer,"target")))
            target_pool = self.pool(targets)
            global_features = to_tensor(_normalized(features.global_features,normalizer,"global"))
            action_nodes = []
            for action in features.actions:
                idx = torch.as_tensor(action.target_index,device=device,dtype=torch.long)
                edges = to_tensor(_normalized(action.edges,normalizer,"edge"))
                embedding = self.edge(torch.cat((targets[idx],edges),dim=1))
                action_nodes.append(torch.cat((target_pool,self.pool(embedding),global_features,
                                               to_tensor(_normalized(action.scalars,normalizer,"scalar")))))
            return self.head(torch.stack(action_nodes))


    class FlatValue(nn.Module):
        """Same public inputs, direct fixed pooled features; parameter-matched comparator."""
        def __init__(self,input_dim,hidden=11,output_dim=6):
            super().__init__()
            self.config=dict(input_dim=input_dim,hidden=hidden,output_dim=output_dim)
            self.head=nn.Sequential(nn.Linear(input_dim,hidden),nn.ReLU(),nn.Linear(hidden,output_dim))

        def forward_group(self,features,normalizer):
            device=next(self.parameters()).device
            flat=features.flat()
            flat=np.clip((flat-normalizer["flat_mean"])/normalizer["flat_std"],-10,10)
            return self.head(torch.as_tensor(flat,device=device,dtype=torch.float32))
else:
    class StructuredValue:
        def __init__(self,*args,**kwargs):
            raise RuntimeError("Training/a Torch comparison requires the isolated Torch environment")

    FlatValue=StructuredValue


def export_numpy(model,normalizer,destination, *, output_scale=1.,metadata=None):
    """Weights preserve float32 Torch tensors; no pickle or Torch runtime artifact."""
    arrays={"weight."+k:v.detach().cpu().numpy() for k,v in model.state_dict().items()}
    arrays.update({"normalizer."+k:np.asarray(v,np.float32) for k,v in normalizer.items()})
    export_metadata=dict(metadata or {})
    # Training/audit exports cannot authorize an untested participant replacement.
    export_metadata["deployment_calibrated"]=False
    config={"schema":FEATURE_SCHEMA,"model_kind":"flat" if isinstance(model,FlatValue) else "structured",
            "model_config":model.config,"output_scale":float(output_scale),"metadata":export_metadata}
    arrays["config_json"]=np.asarray(json.dumps(config,sort_keys=True))
    Path(destination).parent.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(destination,**arrays)
