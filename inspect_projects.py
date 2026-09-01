import sqlite3, json

conn = sqlite3.connect('/home/dan11hermes/.hermes/profiles/implementer/projects.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
print('TABLES:', tabs)
for t in tabs:
    cols = [r[1] for r in c.execute(f'PRAGMA table_info({t})').fetchall()]
    print(f'  {t}: {cols}')
print('\n--- projects ---')
for r in c.execute('SELECT id, name, primary_path FROM projects').fetchall():
    print(dict(r))
print('\n--- planning_sources ---')
for r in c.execute('SELECT * FROM planning_sources').fetchall():
    print(dict(r))
conn.close()
