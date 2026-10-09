# Database changes

`changes.csv` is the single list of database changes. Two kinds of row, no header:

    install,<path to an .sql file>
    uninstall,<path to an .sql file>

All `install` rows come first, then all `uninstall` rows. Paths are relative to the repo root.

    python scripts/db_changes.py install     # run every install row, in order
    python scripts/db_changes.py uninstall   # run every uninstall row, in order
    python scripts/db_changes.py redeploy    # uninstall, then install
    python scripts/db_changes.py install --dry-run   # list what would run

Each file runs in its own transaction. The connection string needs DDL rights, so it is
NOT the engine's `atom_api` login: pass it in `ATOM_ADMIN_DATABASE_URL`.

To change a database object: add its SQL file as a new `install` row, add the file that
removes it as an `uninstall` row, then `redeploy`. Uninstall files drop what the install
files create, written so they can be run on their own. Uninstalls run in the order listed,
so list them in dependency order (dependants first).
