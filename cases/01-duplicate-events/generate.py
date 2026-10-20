import csv
from pathlib import Path

def generate(root):
    rows = [(str(i), '2025-01-01', '2025-01-02', 0, i) for i in range(1, 101)]
    rows += [(str(i), '2025-01-03', '2025-01-04', 1, i + 10) for i in range(1, 21)]
    rows += [('1', '2025-01-03', '2025-01-04', 2, 999)]
    with (root / 'seeds/events.csv').open('w') as f:
        w = csv.writer(f); w.writerow(['event_id','source_updated_at','ingested_at','delivery_sequence','amount']); w.writerows(rows)
