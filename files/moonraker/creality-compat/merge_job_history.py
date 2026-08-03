#!/usr/bin/env python3
# merge_job_history.py — fold one of the K1C 2025's two print histories into the
# other. Runs ON the printer, with both daemons stopped. Not a service, not
# scheduled; "Retire Nexusp Backend" calls it once in each direction.
#
# THE PIPELINE
# ------------
#
#     source db (read-only)                  target db (written)
#          |                                        |
#          |  job_history rows                      |  job_history rows
#          v                                        v
#     +-------------------------------------------------------+
#     |  classify each source row against the target          |
#     |                                                       |
#     |    status == in_progress            -> SKIPPED        |
#     |    (filename, start_time +/-120s) matches -> DUPLICATE |
#     |    otherwise                        -> INSERT         |
#     +-------------------------------------------------------+
#          |                    |                   |
#          | listed             | counted           | listed
#          v                    v                   v
#     dry run prints all three, then stops unless --apply
#          |
#          |  --apply: no Moonraker or nexusp process alive
#          v
#     backup the target -> .bak-merge-<timestamp>
#          |
#          +--> insert the new rows (ids continue after the target's)
#          +--> job_totals: per-column max() of target vs source
#
# WHAT THIS IS FOR
# ----------------
# The 2025 runs two Moonrakers against one Klipper: Creality's `nexusp` (the
# touchscreen's backend, :7125) and the helper script's real one (:7126). They
# share `-d /usr/data/printer_data` — one gcode directory, one klippy socket —
# but Creality namespaced the databases, so each keeps its OWN print history:
#
#     printer_data/database/nexusp-sql.db      <- what the touchscreen shows
#     printer_data/database/moonraker-sql.db   <- what Fluidd shows
#
# Every print since the helper stack was installed is therefore written down
# twice, and everything BEFORE that install exists only in nexusp's copy. When
# real Moonraker takes over :7125 and nexusp is retired, the screen starts
# reading Fluidd's database — so without this the printer's history silently
# begins on the day the helper was installed. On the reference unit that was
# 22 of 42 rows that exist nowhere else, including two prints the helper's
# Moonraker had missed entirely.
#
# BOTH DIRECTIONS, AND WHY RESTORE NEEDS ONE TOO
# ----------------------------------------------
# `--direction to-moonraker` (the default) is retirement: nexusp's rows into
# Moonraker's database. `--direction to-nexusp` is the restore, and it is not
# optional. While nexusp is retired the touchscreen reads and WRITES
# moonraker-sql.db; handing it back a nexusp-sql.db frozen at the retirement
# date would make every print made in between vanish from the screen, with no
# warning and no reason for the user to connect the two events. Same dedupe,
# same backup, same second-run no-op — only the two paths swap.
#
# This is NOT a sync tool. It is one-shot per direction, for the swap window.
# Running it twice is harmless (the dedupe catches everything it already
# inserted), but it has no business existing as a cron job.
#
# THE DEDUPE, AND WHY IT IS FUZZY
# -------------------------------
# Both daemons watch the same klippy, so a print recorded by both produces two
# rows describing one physical job. They are NOT byte-identical: each daemon
# stamps its own `start_time` when it notices the state change, and on the
# reference unit those land ~0.2-1.1 s apart. So the match key is (filename,
# start_time within TOLERANCE_S) rather than equality.
#
# 120 s is deliberately far wider than the observed skew. The input that could
# defeat it is not two unrelated prints — it is a failed print and its immediate
# retry, same filename, minutes apart. Measured on the reference unit, the
# closest such pair is over 600 s apart, so the window keeps 5x margin against
# its own worst realistic case.
#
# JOB_TOTALS ARE NOT ADDITIVE
# ---------------------------
# `job_totals` holds lifetime counters, and the two rowsets OVERLAP, so summing
# them would double-count every shared print. It is also not a simple function of
# job_history: nexusp reports total_jobs=184 while holding 42 rows, because the
# counter survives rows that were pruned. So the merge takes max() PER COLUMN —
# `total` and `maximum` describe different things (a lifetime sum and a single
# job's record), and the row holding the larger sum is not guaranteed to hold the
# larger record. Nothing is invented; each column wins on its own merits. Expect
# Fluidd's "total jobs" to jump from double digits to the machine's real lifetime
# figure. That is the correct number; it only looks wrong because Fluidd has been
# reporting a post-install subset all along.
#
# SAFETY
# ------
# - Dry run by default. `--apply` is required to write anything.
# - Refuses to run while a Moonraker or nexusp process is alive: Moonraker caches
#   `job_totals` in memory and flushes its stale copy back at the next print,
#   straight over the merge.
# - That check is POINT IN TIME. Anything that can restart Moonraker behind your
#   back — a supervisor, a watchdog, a cron entry — must be stopped first, not
#   just the daemon, or it can start one in the gap between the check passing and
#   the write landing. This repo ships no such watchdog, so upstream this is a
#   warning rather than a step; a fork that adds one owns disarming it.
# - Backs the target up next to itself before the first write, and prints the
#   command that restores it. That file is the entire rollback story.
# - RENUMBERS job_id into start_time order, in the same transaction as the
#   inserts. An earlier version deliberately did not, on the stated grounds that
#   "nothing joins on job_id and every surface sorts by start_time". The second
#   half of that is false, and checkably so — Moonraker's own history list is:
#
#       sql_statement += f" ORDER BY job_id {order}"    # history.py, order="desc"
#
#   with no ORDER BY start_time anywhere in the file. Appended rows take the
#   highest ids, so without renumbering the recovered prints — the OLDEST on the
#   machine, which is the entire point of this merge — come back as the most
#   recent jobs in Fluidd and on the touchscreen, while server.history.count
#   reports the right total. A correct scrollbar over a wrongly ordered list is
#   exactly the plausible-wrong-answer failure retiring nexusp exists to remove.
#
#   What renumbering costs is the identity of rows a client may already hold: a
#   Fluidd tab left open across the merge could delete by an id that now names a
#   different print. That needs a tab open across a daemon restart AND a delete
#   issued into the seconds before the port moves and Moonraker comes back. The
#   mis-ordering it prevents is permanent and visible to everyone.

import argparse
import os
import shutil
import sqlite3
import sys
import time

TOLERANCE_S = 120.0

DB_FOLDER = "/usr/data/printer_data/database"
MOONRAKER_DB = os.path.join(DB_FOLDER, "moonraker-sql.db")
NEXUSP_DB = os.path.join(DB_FOLDER, "nexusp-sql.db")

# direction -> (source, target). Retirement moves the screen's history into
# Moonraker's database; restore moves everything printed while retired back.
DIRECTIONS = {
    "to-moonraker": (NEXUSP_DB, MOONRAKER_DB),
    "to-nexusp": (MOONRAKER_DB, NEXUSP_DB),
}

# Column order is identical in both schemas — verified on the reference unit,
# where nexusp declares metadata/auxiliary_data as TEXT and moonraker declares
# them `pyjson`. That difference is cosmetic: sqlite type names are advisory and
# both store the same JSON text, which is what Moonraker's pyjson converter
# expects to read back.
COLUMNS = (
    "user", "filename", "status", "start_time", "end_time",
    "print_duration", "total_duration", "filament_used",
    "metadata", "auxiliary_data", "instance_id",
)

MAX_FIELDS = ("total_jobs", "total_time", "total_print_time",
              "total_filament_used", "longest_job", "longest_print")


def moonraker_running(proc="/proc"):
    """The cmdline of a live Moonraker or nexusp process, or None.

    None means BOTH "nothing is running" and "there is no /proc to look in" —
    the latter being a dry-run rehearsal against copied databases on a
    workstation, where there is no daemon to collide with. The caller cannot
    tell those apart and does not need to.

    /proc scan rather than pgrep: busybox ps on this board truncates the command
    line at a width that hides moonraker.py behind the venv python path.

    `proc` is an argument only so the scan itself can be tested against a fake
    tree — this is the single guard standing between a live daemon and an
    irreversible write, and stubbing the whole function out (which every other
    test does) leaves the matching logic never executed.
    """
    if not os.path.isdir(proc):
        return None
    for pid in os.listdir(proc):
        if not pid.isdigit():
            continue
        try:
            with open(os.path.join(proc, pid, "cmdline"), "rb") as fh:
                cmd = fh.read().decode("utf-8", "replace")
        except (IOError, OSError):
            continue
        if "moonraker.py" in cmd or "/bin/nexusp" in cmd:
            return cmd.replace("\0", " ").strip()
    return None


def table_columns(db, table):
    """{name: (notnull, has_default)} for one table, or {} if it is absent."""
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        rows = con.execute("pragma table_info(%s)" % table).fetchall()
    finally:
        con.close()
    # cid, name, type, notnull, dflt_value, pk
    return dict((r[1], (bool(r[3]), r[4] is not None or bool(r[5]))) for r in rows)


def schema_problems(into_db, source_db):
    """Everything about the two schemas that would make the write go wrong.

    Run during the DRY RUN, so drift is reported before anything is renamed or
    written - not from inside the transaction, where the traceback lands in the
    middle of a retirement with both daemons already stopped.

    COLUMNS is a hardcoded tuple checked once on one machine, and
    `install_moonraker_nginx` runs `git checkout master; git pull` against the
    Moonraker source - so job_history's schema is a MOVING TARGET under any
    printer. Two failure shapes matter and only one of them is loud:

      - a column in COLUMNS that no longer exists raises inside the transaction.
        Safe (it rolls back) but it aborts the retirement with a traceback.
      - a column ADDED to the target that COLUMNS does not know about is worse:
        the insert succeeds and every migrated row carries a NULL where
        Moonraker's own reader expects a value. Nothing complains, ever.

    Note the comment on COLUMNS worries about column ORDER; that is not the
    risk, because the insert names its columns. Existence and nullability are.
    """
    problems = []
    target = table_columns(into_db, "job_history")
    source = table_columns(source_db, "job_history")
    if not target or not source:
        return ["job_history table missing from %s"
                % (into_db if not target else source_db)]
    for name in COLUMNS:
        for label, cols in (("target", target), ("source", source)):
            if name not in cols:
                problems.append(
                    "%s job_history has no '%s' column - this script is older "
                    "than the Moonraker it is writing to" % (label, name))
    for name, (notnull, has_default) in target.items():
        if name in COLUMNS or name == "job_id":
            continue
        if notnull and not has_default:
            problems.append(
                "target job_history has a NOT NULL column '%s' this script does "
                "not write and that has no default" % name)
    return problems


def dropped_columns(source_db):
    """Source columns this script will not carry across. Reported, not fatal."""
    known = set(COLUMNS) | {"job_id"}
    return sorted(c for c in table_columns(source_db, "job_history") if c not in known)


def instance_ids(db):
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        rows = con.execute(
            "select distinct instance_id from job_history").fetchall()
    finally:
        con.close()
    return sorted(r[0] for r in rows)


def load_jobs(db):
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute("select * from job_history order by start_time").fetchall()
    totals = con.execute("select * from job_totals").fetchall()
    con.close()
    return rows, totals


def match_pairs(source_rows, target_rows, eligible):
    """Pair source rows to target rows ONE TO ONE, closest start_time first.

    Both properties matter and neither is obvious.

    ONE TO ONE, because otherwise N source rows all collapse onto the SAME
    target row and every one of them but the first is called a duplicate and
    silently dropped. That is not hypothetical: a cancelled print and its
    immediate retry, same file, a minute apart, is routine, and if the target
    daemon recorded only one of the pair - which happened twice on the reference
    unit, and is half the reason this merge exists - both source rows land
    inside the 120 s window of that single target row.

    CLOSEST FIRST rather than in table order, because a greedy pass in
    start_time order gets the right COUNTS and the wrong ROWS. With a target
    holding only the retry, source [failed, retry] pairs `failed` to the retry
    (60 s apart, within tolerance) and then inserts `retry` as new - so the
    target ends up with the retry twice and the failed print not at all. Sorting
    every candidate pair by distance and assigning greedily from the closest
    makes the exact match win its own row, which leaves the genuinely unmatched
    row to be inserted.

    `eligible` is the set of source indices that are up for matching at all;
    in_progress rows are excluded by the caller before we get here.
    """
    candidates = []
    for si in eligible:
        row = source_rows[si]
        for ti, t in enumerate(target_rows):
            if row["filename"] != t["filename"]:
                continue
            delta = abs(row["start_time"] - t["start_time"])
            if delta <= TOLERANCE_S:
                candidates.append((delta, si, ti))
    # Sorted by (delta, si, ti): the tie-break on the indices keeps the result
    # deterministic for two equidistant candidates rather than dependent on the
    # sort's stability guarantees.
    candidates.sort()
    matched = {}
    claimed = set()
    for _, si, ti in candidates:
        if si in matched or ti in claimed:
            continue
        matched[si] = ti
        claimed.add(ti)
    return matched


def classify(source_rows, target_rows):
    """Split the source into (insert, duplicate, skipped) buckets.

    `skipped` is its own bucket rather than a third kind of duplicate: an
    in_progress row is the live job, and copying a row whose end_time is still
    NULL leaves a job that never completes. Filing it under "duplicate" would
    report a DROP as a no-op, which is the one thing a dry run must not do.
    """
    eligible = [i for i, row in enumerate(source_rows)
                if row["status"] != "in_progress"]
    matched = match_pairs(source_rows, target_rows, eligible)
    new, dupes, skipped = [], [], []
    for index, row in enumerate(source_rows):
        if row["status"] == "in_progress":
            skipped.append(row)
        elif index in matched:
            dupes.append((row, target_rows[matched[index]]))
        else:
            new.append((row, None))
    return new, dupes, skipped


def merge_totals(target_totals, source_totals):
    """Per-column max() of the two totals tables, keyed by (provider, field, instance).

    Per COLUMN, not per row: taking whole rows would let a genuine longest-print
    figure be discarded because its row happened to lose on `total`.
    """
    merged = {}
    for rowset in (target_totals, source_totals):
        for t in rowset:
            key = (t["provider"], t["field"], t["instance_id"])
            prev = merged.get(key)
            if prev is None:
                merged[key] = {"maximum": t["maximum"], "total": t["total"]}
                continue
            for col in ("maximum", "total"):
                incoming = t[col]
                if incoming is None:
                    continue
                if prev[col] is None or incoming > prev[col]:
                    prev[col] = incoming
    return merged


def renumber_by_start_time(con):
    """Make job_id order match start_time order, inside the caller's transaction.

    Moonraker pages history with `ORDER BY job_id`, so after appending older
    prints the id order IS the display order and it is wrong. See the SAFETY
    note in the header for why this is worth the id churn.

    Done as an offset pass rather than in place: job_id is `INTEGER PRIMARY KEY
    ASC`, so assigning 1..N directly would collide with rows that still hold
    those ids. Shifting every row above the current maximum first makes the
    second pass collision-free without needing a temp table.

    Ordered by (start_time, job_id) so rows sharing a timestamp keep their
    existing relative order rather than being permuted arbitrarily.
    """
    rows = con.execute(
        "select job_id from job_history order by start_time, job_id").fetchall()
    if not rows:
        return
    offset = con.execute(
        "select coalesce(max(job_id), 0) from job_history").fetchone()[0]
    for position, row in enumerate(rows, start=1):
        con.execute("update job_history set job_id = ? where job_id = ?",
                    (offset + position, row[0]))
    for position in range(1, len(rows) + 1):
        con.execute("update job_history set job_id = ? where job_id = ?",
                    (position, offset + position))


def main():
    ap = argparse.ArgumentParser(
        description="fold one K1C 2025 print history into the other")
    ap.add_argument("--direction", choices=sorted(DIRECTIONS), default="to-moonraker",
                    help="to-moonraker when retiring nexusp (default), "
                         "to-nexusp when restoring it")
    ap.add_argument("--into", default=None,
                    help="override the target database, written to")
    ap.add_argument("--source", default=None,
                    help="override the source database, read only")
    ap.add_argument("--apply", action="store_true", help="actually write")
    ap.add_argument("--force", action="store_true",
                    help="write even with a daemon alive — it will then overwrite "
                         "the merged job_totals from its stale in-memory copy")
    ap.add_argument("--allow-instance-mismatch", action="store_true",
                    help="copy rows even when the two databases scope their "
                         "history to different instance_ids — the copies will "
                         "not be visible to the daemon reading them")
    args = ap.parse_args()

    default_source, default_into = DIRECTIONS[args.direction]
    source_db = args.source or default_source
    into_db = args.into or default_into

    for path in (into_db, source_db):
        if not os.path.exists(path):
            sys.exit("missing database: %s" % path)

    # Schema first, before anything is read or reported. A mismatch here means
    # the write would fail (or, worse, silently half-succeed), and the only safe
    # moment to say so is before the caller starts renaming init scripts.
    problems = schema_problems(into_db, source_db)
    if problems:
        sys.exit("refusing: schema mismatch\n  " + "\n  ".join(problems))
    dropped = dropped_columns(source_db)
    if dropped:
        print("note: source columns not copied: %s" % ", ".join(dropped))

    target_rows, target_totals = load_jobs(into_db)
    source_rows, source_totals = load_jobs(source_db)

    new, dupes, skipped = classify(source_rows, target_rows)

    def when(t):
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))

    def listing(rows):
        for row in rows:
            print("   %s  %-44s %s" % (when(row["start_time"]),
                                       (row["filename"] or "")[:44], row["status"]))

    # Moonraker scopes every history query by instance_id (its own list handler
    # filters on a bare "default"), so rows carrying a different one insert
    # successfully and are then invisible in Fluidd and in the screen's count -
    # a merge that reports success and shows nothing. Report both sets always,
    # and refuse when they cannot see each other.
    target_instances = instance_ids(into_db)
    source_instances = instance_ids(source_db)
    print("direction: %s" % args.direction)
    print("target %s: %d jobs, instance_id %s"
          % (into_db, len(target_rows), target_instances or ["(empty)"]))
    print("source %s: %d jobs, instance_id %s"
          % (source_db, len(source_rows), source_instances or ["(empty)"]))
    if target_instances and source_instances and \
            not set(target_instances) & set(source_instances):
        if not args.allow_instance_mismatch:
            sys.exit(
                "refusing: the two databases scope their history to different\n"
                "instance_ids (%s vs %s). Copied rows would be invisible to the\n"
                "daemon that reads them, and the merge would report success.\n"
                "Re-run with --allow-instance-mismatch if that is really wanted."
                % (target_instances, source_instances))
        print("warning: instance_id mismatch, copying anyway (--allow-instance-mismatch)")
    print("duplicate (skipped): %d" % len(dupes))
    print("in_progress (NOT copied): %d" % len(skipped))
    listing(skipped)
    print("to insert: %d" % len(new))
    listing([row for row, _ in new])

    merged_totals = merge_totals(target_totals, source_totals)
    print("job_totals after merge:")
    for (provider, field, inst), t in sorted(merged_totals.items()):
        if field in MAX_FIELDS:
            print("   %-22s total=%s maximum=%s" % (field, t["total"], t["maximum"]))

    if not args.apply:
        print("\ndry run — nothing written. re-run with --apply")
        return

    alive = moonraker_running()
    if alive and not args.force:
        sys.exit("refusing: a daemon is still alive -> %s\n"
                 "stop it before merging; its cached job_totals would land on "
                 "top of the merge at the next print." % alive)

    backup = "%s.bak-merge-%s" % (into_db, time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(into_db, backup)
    # Name the daemon that actually owns the file being replaced. The forward
    # merge writes Moonraker's database and the reverse one writes nexusp's, so
    # a fixed "stop Moonraker" tells the user to stop the wrong daemon on the
    # restore path - and this line is the only rollback instruction that appears
    # anywhere.
    owner = "nexusp" if into_db == NEXUSP_DB else "Moonraker"
    print("\nbackup: %s" % backup)
    print("rollback: stop %s, cp %s %s, restart it" % (owner, backup, into_db))

    con = sqlite3.connect(into_db)
    con.row_factory = sqlite3.Row
    try:
        with con:
            for row, _ in new:
                con.execute(
                    "insert into job_history (%s) values (%s)"
                    % (",".join(COLUMNS), ",".join("?" * len(COLUMNS))),
                    tuple(row[c] for c in COLUMNS))
            for (provider, field, inst), t in merged_totals.items():
                con.execute(
                    "insert or replace into job_totals "
                    "(provider, field, maximum, total, instance_id) values (?,?,?,?,?)",
                    (provider, field, t["maximum"], t["total"], inst))
            renumber_by_start_time(con)
        total = con.execute("select count(*) from job_history").fetchone()[0]
        print("merged: %d jobs in %s" % (total, into_db))
    finally:
        con.close()


if __name__ == "__main__":
    main()
