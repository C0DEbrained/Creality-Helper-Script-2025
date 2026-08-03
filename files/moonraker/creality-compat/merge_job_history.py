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
# - Does NOT renumber job_id. Inserted rows take ids after the target's existing
#   ones, so id order no longer matches time order — deliberately. Nothing joins
#   on job_id and every surface sorts by start_time, whereas renumbering rewrites
#   the identity of rows a client may already be holding: a Fluidd tab left open
#   across the merge would delete by an id that now names a different print.

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


def moonraker_running():
    """True if anything that looks like Moonraker holds a PID right now.

    /proc scan rather than pgrep: busybox ps on this board truncates the command
    line at a width that hides moonraker.py behind the venv python path.
    """
    if not os.path.isdir("/proc"):
        # Not the printer — a dry-run rehearsal against copied databases on a
        # workstation. There is no daemon here to collide with.
        return None
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as fh:
                cmd = fh.read().decode("utf-8", "replace")
        except (IOError, OSError):
            continue
        if "moonraker.py" in cmd or "/bin/nexusp" in cmd:
            return cmd.replace("\0", " ").strip()
    return None


def load_jobs(db):
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute("select * from job_history order by start_time").fetchall()
    totals = con.execute("select * from job_totals").fetchall()
    con.close()
    return rows, totals


def is_duplicate(row, targets):
    for t in targets:
        if row["filename"] == t["filename"] and \
                abs(row["start_time"] - t["start_time"]) <= TOLERANCE_S:
            return t
    return None


def classify(source_rows, target_rows):
    """Split the source into (insert, duplicate, skipped) buckets.

    `skipped` is its own bucket rather than a third kind of duplicate: an
    in_progress row is the live job, and copying a row whose end_time is still
    NULL leaves a job that never completes. Filing it under "duplicate" would
    report a DROP as a no-op, which is the one thing a dry run must not do.
    """
    new, dupes, skipped = [], [], []
    for row in source_rows:
        if row["status"] == "in_progress":
            skipped.append(row)
            continue
        match = is_duplicate(row, target_rows)
        (dupes if match else new).append((row, match))
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
    args = ap.parse_args()

    default_source, default_into = DIRECTIONS[args.direction]
    source_db = args.source or default_source
    into_db = args.into or default_into

    for path in (into_db, source_db):
        if not os.path.exists(path):
            sys.exit("missing database: %s" % path)

    target_rows, target_totals = load_jobs(into_db)
    source_rows, source_totals = load_jobs(source_db)

    new, dupes, skipped = classify(source_rows, target_rows)

    def when(t):
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))

    def listing(rows):
        for row in rows:
            print("   %s  %-44s %s" % (when(row["start_time"]),
                                       (row["filename"] or "")[:44], row["status"]))

    print("direction: %s" % args.direction)
    print("target %s: %d jobs" % (into_db, len(target_rows)))
    print("source %s: %d jobs" % (source_db, len(source_rows)))
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
    print("\nbackup: %s" % backup)
    print("rollback: stop Moonraker, cp %s %s, restart it" % (backup, into_db))

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
        total = con.execute("select count(*) from job_history").fetchone()[0]
        print("merged: %d jobs in %s" % (total, into_db))
    finally:
        con.close()


if __name__ == "__main__":
    main()
