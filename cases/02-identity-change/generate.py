import csv

def generate(root):
    for name, header, rows in [
        ('users', ['tenant','user_id'], [(t,str(i)) for t in ['a','b'] for i in range(1,51)]),
        ('activity', ['tenant','raw_user_id'], [(t,str(i) if i <= 30 else f'usr:{i}') for t in ['a','b'] for i in range(1,51)]),
        ('identity_map', ['raw_user_id','canonical_user_id'], [(f'usr:{i}',str(i)) for i in range(31,51)])]:
        with (root / f'seeds/{name}.csv').open('w') as f:
            w=csv.writer(f); w.writerow(header); w.writerows(rows)
