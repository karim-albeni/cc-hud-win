"""Print the first column of every row a query returns. The smoke test's stand-in for the sqlite3 CLI."""

import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as db:
    for row in db.execute(sys.argv[2]):
        print("" if row[0] is None else row[0])
