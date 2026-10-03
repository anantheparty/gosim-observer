"""NumPy-only deployment runtime. This module never imports Torch."""
from __future__ import annotations

import json

import numpy as np

from research.structured_student_features import FEATURE_SCHEMA, SchemaError, _pool


def normalized(array, normalizer, name):
    return np.clip((array-normalizer[name+"_mean"])/normalizer[name+"_std"],-10,10).astype(np.float32)


class NumpyValue:
    def __init__(self,path):
        with np.load(path,allow_pickle=False) as archive:
            self.config=json.loads(str(archive["config_json"]))
            self.weights={k[7:]:archive[k].copy() for k in archive.files if k.startswith("weight.")}
            self.normalizer={k[11:]:archive[k].copy() for k in archive.files if k.startswith("normalizer.")}
        if self.config["schema"]!=FEATURE_SCHEMA:
            raise SchemaError("Incompatible exported feature schema")

    def _linear(self,values,prefix):
        # Small fixed layers avoid a BLAS dependency/thread pool at deployment.
        return np.einsum("...i,oi->...o",values,self.weights[prefix+".weight"],optimize=False)+self.weights[prefix+".bias"]

    def _encoder(self,values,prefix):
        return np.maximum(self._linear(np.maximum(self._linear(values,prefix+".0"),0),prefix+".2"),0)

    def predict(self,features):
        declared=self.config.get("metadata",{}).get("feature_names")
        if declared is not None:
            actual=dict(target=features.target_names,edge=features.edge_names,global_features=features.global_names,scalar=features.scalar_names)
            if any(tuple(declared.get(name,()))!=tuple(names) for name,names in actual.items()):
                raise SchemaError("Exported model feature names/order differ from runtime")
        if self.config["model_kind"]=="flat":
            flat=features.flat()
            inp=np.clip((flat-self.normalizer["flat_mean"])/self.normalizer["flat_std"],-10,10).astype(np.float32)
        else:
            target=self._encoder(normalized(features.target_nodes,self.normalizer,"target"),"target")
            shared=_pool(target)
            global_values=normalized(features.global_features,self.normalizer,"global")
            inp=[]
            for action in features.actions:
                edges=normalized(action.edges,self.normalizer,"edge")
                encoded=self._encoder(np.column_stack((target[action.target_index],edges)),"edge")
                inp.append(np.concatenate((shared,_pool(encoded),global_values,normalized(action.scalars,self.normalizer,"scalar"))))
            inp=np.asarray(inp,np.float32)
        result=self._linear(np.maximum(self._linear(inp,"head.0"),0),"head.2")*float(self.config["output_scale"])
        if not np.isfinite(result).all():
            raise SchemaError("Non-finite NumPy inference result")
        return result

    def advantages(self,features):
        result=self.predict(features)
        control=[a.name for a in features.actions].index("control")
        return result-result[control]

    def choose(self,features, *, minimum_advantage=None):
        """Explicit abstention: uncalibrated exports ALWAYS return native control."""
        metadata=self.config.get("metadata",{})
        if not metadata.get("deployment_calibrated",False):
            return "control"
        if not metadata.get("feature_names"):
            raise SchemaError("Calibrated deployment requires frozen feature names")
        threshold=metadata.get("minimum_advantage",None) if minimum_advantage is None else minimum_advantage
        if threshold is None or threshold<0:
            raise SchemaError("Calibrated deployment requires a nonnegative heldout threshold")
        prediction=self.advantages(features)[:,0]
        winner=int(np.argmax(prediction))
        return features.actions[winner].name if prediction[winner]>threshold else "control"
