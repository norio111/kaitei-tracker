import sqlite3

conn = sqlite3.connect('db/kaitei.db')
row = conn.execute("SELECT url FROM revision_document WHERE title LIKE '%その10%'").fetchone()
print(row)