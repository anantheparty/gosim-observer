#!/usr/bin/env python3
"""Audit a saved house graph locally; makes no network requests."""
import argparse
import collections
import hashlib
import json
from pathlib import Path


def audit(path):
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    rooms, first_line, duplicates, changes = {}, {}, [], []
    for line, row in enumerate(rows, 1):
        room, reply = row['room'], row['reply']
        doors = reply.get('doors', {})
        if room in rooms:
            duplicates.append({'room': room, 'lines': [first_line[room], line]})
            if rooms[room] != doors:
                changes.append({'room': room, 'before': rooms[room], 'after': doors})
        else:
            first_line[room] = line
        rooms[room] = doors
    edges = {(src, label, dst) for src, doors in rooms.items() for label, dst in doors.items()}
    targets = {dst for _, _, dst in edges}
    root = rows[0]['room']
    reached, parent = {root}, {}
    queue = collections.deque([root])
    while queue:
        src = queue.popleft()
        for label, dst in rooms.get(src, {}).items():
            if dst not in reached:
                reached.add(dst)
                parent[dst] = (src, label)
                queue.append(dst)
    label_counts = collections.Counter(label for _, label, _ in edges)
    tree_counts = collections.Counter(label for _, label in parent.values())
    special = []
    for room in rooms:
        row = next(row for row in rows if row['room'] == room)
        reply = row['reply']
        if 'note' in reply or 'flag' in reply:
            steps, cur = [], room
            while cur in parent:
                src, label = parent[cur]
                steps.append({'from': src, 'door': label, 'to': cur})
                cur = src
            special.append({'room': room, 'line': first_line[room],
                            'kind': 'note' if 'note' in reply else 'flag',
                            'path': list(reversed(steps))})
    return {
        'source': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
        'records': len(rows), 'statuses': dict(collections.Counter(row['status'] for row in rows)),
        'root': root, 'unique_rooms': len(rooms), 'duplicates': duplicates,
        'changed_door_snapshots': changes, 'directed_doors': len(edges),
        'unread_targets': sorted(targets - rooms.keys()),
        'reachable_rooms': len(reached & rooms.keys()),
        'unreachable_rooms': sorted(rooms.keys() - reached),
        'nonreciprocal_doors': sorted((src, label, dst) for src, label, dst in edges
                                    if src not in rooms.get(dst, {}).values()),
        'door_types': dict(sorted(label_counts.items())),
        'bfs_discovery_door_types': dict(sorted(tree_counts.items())),
        'special_rooms': special,
        'scope': 'Snapshot graph coverage, not evidence that every directed edge was traversed; applies only to this saved instance.'
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('map', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.map), ensure_ascii=False, indent=2))
