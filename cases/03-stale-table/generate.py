import csv

def generate(root):
    with (root / 'seeds/write_history.csv').open('w') as f:
        w=csv.writer(f); w.writerow(['table_name','write_date','rows_written','error_rows'])
        w.writerows([('legacy','2024-01-01',1000,800),('current','2025-01-01',1000,10),('current','2025-01-02',1000,10),('current','2025-01-03',1000,10)])
