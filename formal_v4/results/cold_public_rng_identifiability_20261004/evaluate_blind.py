"""Evaluator opens self-generated synthetic truth only after predictions freeze."""
import json
from fixture import ROOT, digest, dump, read_rows

prediction_file = ROOT / 'blind_predictions_frozen.json'
predictions = json.loads(prediction_file.read_text())
labels = json.loads((ROOT / 'SYNTHETIC_SEALED_LABELS.json').read_text())
by_id = {r['world_id']:r for r in predictions['worlds']}
records = []
for label in labels:
    prediction = by_id[label['world_id']]
    record = dict(label=label, prediction=prediction)
    if label['status'] != 'generated':
        record['pass'] = False
    elif not label['in_domain']:
        record['pass'] = prediction['status']=='abstain' and prediction['candidates']==[]
    else:
        path = ROOT / 'worlds_SYNTHETIC' / label['world_id'] / 'truth'
        truth = dict(weather_future=read_rows(path / 'v4_weather_truth.csv')[1:],
            events=read_rows(path / 'v4_events.csv'),
            earthquake_effects=read_rows(path / 'v4_earthquake_effects.csv'),
            stress=read_rows(path / 'v4_stress_events.csv'),
            requests=[json.loads(x) for x in (path / 'v4_observation_requests.jsonl').read_text().splitlines()])
        predicted = json.loads((ROOT / 'blind_predictions' / label['world_id'] / 'future_SYNTHETIC.json').read_text())
        # CSV serializes scalar values; normalize predictions to the same contract.
        scalar_csv = lambda row: {k:str(v) for k,v in row.items()}
        for key in ('weather_future', 'events', 'earthquake_effects', 'stress'):
            predicted[key] = [scalar_csv(r) for r in predicted[key]]
        record['future_equal'] = {key:predicted[key]==truth[key] for key in truth}
        record['pass'] = prediction['recovered_master']==label['SYNTHETIC_master'] and all(record['future_equal'].values())
    records.append(record)
result = dict(predictions_sha256_before_label_read=digest(prediction_file.read_bytes()),
    worlds=records, positives=sum(r['label']['in_domain'] for r in records),
    negatives=sum(not r['label']['in_domain'] for r in records),
    passed=sum(r['pass'] for r in records), failed=[r for r in records if not r['pass']])
dump(ROOT / 'blind_evaluation.json', result)
print(json.dumps({k:result[k] for k in ('positives','negatives','passed','failed')}))
