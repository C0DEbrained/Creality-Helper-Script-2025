#!/usr/bin/env python3
"""Offline checks for merge_job_history.py — no printer, no daemon, no network.

Standalone, no conftest and no fixtures beyond this file:

    python3 -m pytest -q test_merge_job_history.py

WHY THIS FILE EXISTS
--------------------
merge_job_history.py is the only artifact in the nexusp retirement that mutates
irreplaceable data. On the reference unit 22 of 42 print records existed in
exactly one place — nexusp's database — and the merge is the single event that
decides whether they survive. It runs once per direction, on a machine where a
mistake is discovered weeks later by noticing an absence. So the safety
properties get pinned down here, where they can be exercised as often as we
like, rather than on the printer.

Four of them are load-bearing and none is observable at merge time:

  1. THE BACKUP IS RESTORABLE. `.bak-merge-<ts>` is the entire rollback story,
     and until this file existed nothing had ever opened one. test_backup_
     restores_the_pre_merge_state does the whole round trip.
  2. THE DEDUPE WINDOW HAS THE RIGHT SHAPE. Too narrow and shared prints double
     up (visibly, harmlessly); too wide and a distinct print is silently
     swallowed by its neighbour and is simply gone. The boundary tests pin 120 s
     as inclusive and pin what falls either side of it.
  3. A DROPPED ROW IS REPORTED AS A DROP. in_progress rows are deliberately not
     copied. An earlier draft counted them as duplicates, which reads on the dry
     run as "already there" — the one lie a dry run must not tell.
  4. BOTH DIRECTIONS WORK. Restore hands the touchscreen back a database frozen
     at the retirement date unless the prints made while retired are merged into
     it first, and that loss is silent.

THE SCHEMAS ARE THE REAL ONES, copied verbatim from the reference unit
(2026-08-02) rather than written from memory. Both matter: `job_totals`'
composite PRIMARY KEY is what makes the merge's `insert or replace` a replace
instead of a duplicate, and `job_id INTEGER PRIMARY KEY ASC` is what makes
inserted ids continue after the target's.

⚠ Add cases as `test_*` functions. A file named test_*.py whose assertions live
in a hand-rolled runner gets collected and runs nothing while reporting green.
"""
import glob
import os
import shutil
import sqlite3
import sys

import pytest

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

import merge_job_history as mjh  # noqa: E402

# Verbatim from the reference unit. moonraker declares metadata/auxiliary_data
# as `pyjson` and nexusp as TEXT; sqlite type names are advisory and the script
# connects without detect_types, so one DDL serves both here.
JOB_HISTORY_DDL = """
CREATE TABLE job_history (
    job_id INTEGER PRIMARY KEY ASC,
    user TEXT NOT NULL,
    filename TEXT,
    status TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL,
    print_duration REAL NOT NULL,
    total_duration REAL NOT NULL,
    filament_used REAL NOT NULL,
    metadata pyjson,
    auxiliary_data pyjson NOT NULL,
    instance_id TEXT NOT NULL
)
"""

JOB_TOTALS_DDL = """
CREATE TABLE job_totals (
    provider TEXT NOT NULL,
    field TEXT NOT NULL,
    maximum REAL,
    total REAL,
    instance_id TEXT NOT NULL,
    PRIMARY KEY (provider, field, instance_id)
)
"""

T0 = 1_750_000_000.0  # an arbitrary fixed epoch; nothing here depends on "now"


def job(start, filename="a.gcode", status="completed", job_id=None, user="_TRUSTED",
        end=None, print_duration=100.0, total_duration=120.0, filament_used=1.0,
        instance_id="default"):
    """One job_history row as the dict the helpers below insert."""
    return {
        "job_id": job_id,
        "user": user,
        "filename": filename,
        "status": status,
        "start_time": start,
        "end_time": start + total_duration if end is None else end,
        "print_duration": print_duration,
        "total_duration": total_duration,
        "filament_used": filament_used,
        "metadata": "{}",
        "auxiliary_data": "[]",
        "instance_id": instance_id,
    }


def total(field, maximum=0.0, tot=0.0, provider="history", instance_id="default"):
    return {"provider": provider, "field": field, "maximum": maximum,
            "total": tot, "instance_id": instance_id}


def make_db(path, jobs=(), totals=()):
    con = sqlite3.connect(str(path))
    con.execute(JOB_HISTORY_DDL)
    con.execute(JOB_TOTALS_DDL)
    for j in jobs:
        cols = [c for c in j if not (c == "job_id" and j[c] is None)]
        con.execute("insert into job_history (%s) values (%s)"
                    % (",".join(cols), ",".join("?" * len(cols))),
                    tuple(j[c] for c in cols))
    for t in totals:
        con.execute("insert into job_totals (provider, field, maximum, total, "
                    "instance_id) values (?,?,?,?,?)",
                    (t["provider"], t["field"], t["maximum"], t["total"],
                     t["instance_id"]))
    con.commit()
    con.close()
    return str(path)


def rows_of(path, table="job_history", order="start_time"):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    out = [dict(r) for r in con.execute("select * from %s order by %s" % (table, order))]
    con.close()
    return out


def run_main(monkeypatch, capsys, into, source, *flags):
    """Drive main() with argv, returning its stdout. Raises SystemExit on refusal."""
    monkeypatch.setattr(sys, "argv",
                        ["merge_job_history.py", "--into", into,
                         "--source", source] + list(flags))
    mjh.main()
    return capsys.readouterr().out


def run_argv(monkeypatch, capsys, *flags):
    """Drive main() with no path overrides, so the direction defaults apply."""
    monkeypatch.setattr(sys, "argv", ["merge_job_history.py"] + list(flags))
    mjh.main()
    return capsys.readouterr().out


# --------------------------------------------------------------------------
# The dedupe window
# --------------------------------------------------------------------------

def test_same_file_inside_the_window_is_a_duplicate():
    target = [job(T0)]
    new, dupes, skipped = mjh.classify([job(T0 + 119)], target)
    assert (len(new), len(dupes), len(skipped)) == (0, 1, 0)


def test_the_window_boundary_is_inclusive():
    """Exactly TOLERANCE_S counts as the same print.

    Which side of the boundary the equal case falls on is arbitrary; that it is
    PINNED is not. Widening the window later without noticing this test is how a
    distinct print gets swallowed.
    """
    target = [job(T0)]
    new, dupes, _ = mjh.classify([job(T0 + mjh.TOLERANCE_S)], target)
    assert (len(new), len(dupes)) == (0, 1)


def test_same_file_outside_the_window_is_a_distinct_print():
    target = [job(T0)]
    new, dupes, _ = mjh.classify([job(T0 + 121)], target)
    assert (len(new), len(dupes)) == (1, 0)


def test_a_failed_print_and_its_retry_both_survive():
    """The realistic worst case for a time-based dedupe.

    Same filename, minutes apart, first one cancelled. Measured on the reference
    unit the closest such pair is >600 s; this asserts the pair stays two rows.
    """
    target = [job(T0, status="klippy_shutdown")]
    new, dupes, _ = mjh.classify([job(T0, status="klippy_shutdown"),
                                  job(T0 + 610)], target)
    assert (len(new), len(dupes)) == (1, 1)


def test_different_files_at_the_same_instant_are_distinct():
    target = [job(T0, filename="a.gcode")]
    new, dupes, _ = mjh.classify([job(T0, filename="b.gcode")], target)
    assert (len(new), len(dupes)) == (1, 0)


def test_empty_target_takes_everything():
    new, dupes, skipped = mjh.classify([job(T0), job(T0 + 9999)], [])
    assert (len(new), len(dupes), len(skipped)) == (2, 0, 0)


def test_empty_source_is_a_no_op():
    assert mjh.classify([], [job(T0)]) == ([], [], [])


# --------------------------------------------------------------------------
# in_progress: dropped, and REPORTED as dropped
# --------------------------------------------------------------------------

def test_in_progress_is_skipped_not_counted_as_a_duplicate():
    target = [job(T0)]
    new, dupes, skipped = mjh.classify(
        [job(T0 + 1, status="in_progress", end=None)], target)
    assert (len(new), len(dupes), len(skipped)) == (0, 0, 1)


def test_in_progress_without_a_twin_is_still_skipped():
    """No twin in the target, so it is a genuine loss — and must still not be
    copied: a row with end_time NULL is a job that never completes."""
    new, dupes, skipped = mjh.classify(
        [job(T0, status="in_progress", end=None)], [])
    assert (len(new), len(dupes), len(skipped)) == (0, 0, 1)


def test_the_dry_run_lists_every_skipped_row(monkeypatch, capsys, tmp_path):
    into = make_db(tmp_path / "into.db", [job(T0)])
    source = make_db(tmp_path / "src.db",
                     [job(T0 + 1, filename="live.gcode", status="in_progress",
                          end=None)])
    out = run_main(monkeypatch, capsys, into, source)
    assert "in_progress (NOT copied): 1" in out
    assert "live.gcode" in out


# --------------------------------------------------------------------------
# job_totals
# --------------------------------------------------------------------------

def test_totals_take_the_max_of_each_column_independently():
    """Row A holds the bigger lifetime sum, row B the bigger single-job record;
    taking whole rows would throw one of them away."""
    a = [total("longest_print", maximum=100.0, tot=5000.0)]
    b = [total("longest_print", maximum=900.0, tot=10.0)]
    merged = mjh.merge_totals(a, b)
    assert merged[("history", "longest_print", "default")] == {
        "maximum": 900.0, "total": 5000.0}


def test_a_null_column_never_wins():
    a = [total("total_jobs", maximum=None, tot=184.0)]
    b = [total("total_jobs", maximum=7.0, tot=None)]
    merged = mjh.merge_totals(a, b)
    assert merged[("history", "total_jobs", "default")] == {
        "maximum": 7.0, "total": 184.0}


def test_instances_do_not_merge_into_each_other():
    a = [total("total_jobs", tot=184.0, instance_id="default")]
    b = [total("total_jobs", tot=17.0, instance_id="other")]
    merged = mjh.merge_totals(a, b)
    assert merged[("history", "total_jobs", "default")]["total"] == 184.0
    assert merged[("history", "total_jobs", "other")]["total"] == 17.0


def test_fields_do_not_merge_into_each_other():
    merged = mjh.merge_totals([total("total_jobs", tot=184.0)],
                              [total("total_time", tot=3.0)])
    assert len(merged) == 2


def test_totals_land_in_the_database_as_a_replace(monkeypatch, capsys, tmp_path):
    """job_totals' composite PRIMARY KEY is what makes `insert or replace` a
    replace. If that key were ever lost the row count would grow instead."""
    into = make_db(tmp_path / "into.db", [], [total("total_jobs", tot=17.0)])
    source = make_db(tmp_path / "src.db", [], [total("total_jobs", tot=184.0)])
    run_main(monkeypatch, capsys, into, source, "--apply")
    after = rows_of(into, "job_totals", "field")
    assert len(after) == 1
    assert after[0]["total"] == 184.0


# --------------------------------------------------------------------------
# The guards
# --------------------------------------------------------------------------

def test_a_live_daemon_blocks_and_force_overrides(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(mjh, "moonraker_running", lambda: "python moonraker.py")
    into = make_db(tmp_path / "into.db", [job(T0)])
    source = make_db(tmp_path / "src.db", [job(T0 + 9999)])
    with pytest.raises(SystemExit):
        run_main(monkeypatch, capsys, into, source, "--apply")
    assert len(rows_of(into)) == 1
    assert glob.glob(into + ".bak-merge-*") == []
    run_main(monkeypatch, capsys, into, source, "--apply", "--force")
    assert len(rows_of(into)) == 2


def test_no_proc_reads_as_no_daemon(monkeypatch):
    """The workstation rehearsal path: /proc does not exist on a Mac, and the
    guard must degrade to "nothing running here" rather than crash."""
    monkeypatch.setattr(os.path, "isdir", lambda p: False)
    assert mjh.moonraker_running() is None


def test_a_missing_database_exits_before_touching_anything(monkeypatch, capsys,
                                                          tmp_path):
    into = make_db(tmp_path / "into.db", [job(T0)])
    with pytest.raises(SystemExit):
        run_main(monkeypatch, capsys, into, str(tmp_path / "nope.db"), "--apply")
    assert glob.glob(into + ".bak-merge-*") == []


# --------------------------------------------------------------------------
# Direction
# --------------------------------------------------------------------------

def test_the_default_direction_is_nexusp_into_moonraker():
    assert mjh.DIRECTIONS["to-moonraker"] == (mjh.NEXUSP_DB, mjh.MOONRAKER_DB)


def test_the_restore_direction_is_the_exact_reverse():
    """Restore hands the screen back nexusp-sql.db, frozen at the retirement
    date, unless everything printed while retired goes back into it first — and
    that loss is silent, with nothing to connect it to the restore."""
    assert mjh.DIRECTIONS["to-nexusp"] == (mjh.MOONRAKER_DB, mjh.NEXUSP_DB)


def test_direction_picks_the_databases(monkeypatch, capsys, tmp_path):
    moonraker = make_db(tmp_path / "moonraker-sql.db",
                        [job(T0, filename="while_retired.gcode")])
    nexusp = make_db(tmp_path / "nexusp-sql.db",
                     [job(T0 - 86400, filename="before_retirement.gcode")])
    monkeypatch.setattr(mjh, "DIRECTIONS", {
        "to-moonraker": (nexusp, moonraker),
        "to-nexusp": (moonraker, nexusp),
    })
    run_argv(monkeypatch, capsys, "--direction", "to-nexusp", "--apply")
    assert [r["filename"] for r in rows_of(nexusp)] == [
        "before_retirement.gcode", "while_retired.gcode"]
    # The forward database is untouched by a backward merge.
    assert [r["filename"] for r in rows_of(moonraker)] == ["while_retired.gcode"]


def test_the_direction_is_reported_on_the_dry_run(monkeypatch, capsys, tmp_path):
    """The one thing a user can check before letting it write."""
    into = make_db(tmp_path / "into.db", [job(T0)])
    source = make_db(tmp_path / "src.db", [job(T0 + 9999)])
    out = run_main(monkeypatch, capsys, into, source, "--direction", "to-nexusp")
    assert "direction: to-nexusp" in out


def test_a_round_trip_does_not_duplicate_the_shared_prints(monkeypatch, capsys,
                                                           tmp_path):
    """Retire, print, restore. The prints made while retired must arrive in
    nexusp's database exactly once, and the ones that were merged forward at
    retirement must not come back as copies."""
    moonraker = make_db(tmp_path / "moonraker-sql.db",
                        [job(T0, filename="shared.gcode")])
    nexusp = make_db(tmp_path / "nexusp-sql.db",
                     [job(T0 + 0.7, filename="shared.gcode"),
                      job(T0 - 86400, filename="ancient.gcode")])
    run_main(monkeypatch, capsys, moonraker, nexusp, "--apply")
    assert sorted(r["filename"] for r in rows_of(moonraker)) == [
        "ancient.gcode", "shared.gcode"]

    # ... a print happens while nexusp is retired ...
    con = sqlite3.connect(moonraker)
    j = job(T0 + 500000, filename="while_retired.gcode")
    cols = [c for c in j if c != "job_id"]
    con.execute("insert into job_history (%s) values (%s)"
                % (",".join(cols), ",".join("?" * len(cols))),
                tuple(j[c] for c in cols))
    con.commit()
    con.close()

    run_main(monkeypatch, capsys, nexusp, moonraker, "--apply")
    assert sorted(r["filename"] for r in rows_of(nexusp)) == [
        "ancient.gcode", "shared.gcode", "while_retired.gcode"]


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------

def test_the_dry_run_writes_nothing(monkeypatch, capsys, tmp_path):
    into = make_db(tmp_path / "into.db", [job(T0)])
    source = make_db(tmp_path / "src.db", [job(T0 + 9999), job(T0 + 19999)])
    before = rows_of(into)
    out = run_main(monkeypatch, capsys, into, source)
    assert "to insert: 2" in out
    assert rows_of(into) == before
    assert glob.glob(into + ".bak-merge-*") == []


def test_apply_inserts_the_missing_prints(monkeypatch, capsys, tmp_path):
    into = make_db(tmp_path / "into.db", [job(T0, filename="shared.gcode")])
    source = make_db(tmp_path / "src.db",
                     [job(T0 + 0.7, filename="shared.gcode"),
                      job(T0 - 86400, filename="older.gcode")])
    run_main(monkeypatch, capsys, into, source, "--apply")
    got = [r["filename"] for r in rows_of(into)]
    assert got == ["older.gcode", "shared.gcode"]


def test_backup_restores_the_pre_merge_state(monkeypatch, capsys, tmp_path):
    """THE ROLLBACK. Nothing else in this change verifies that the file the
    script writes before its first insert can actually be put back."""
    into = make_db(tmp_path / "into.db", [job(T0, filename="shared.gcode")],
                   [total("total_jobs", tot=17.0)])
    source = make_db(tmp_path / "src.db", [job(T0 - 86400, filename="older.gcode")],
                     [total("total_jobs", tot=184.0)])
    before_jobs, before_totals = rows_of(into), rows_of(into, "job_totals", "field")

    run_main(monkeypatch, capsys, into, source, "--apply")
    assert len(rows_of(into)) == 2
    assert rows_of(into, "job_totals", "field")[0]["total"] == 184.0

    backups = glob.glob(into + ".bak-merge-*")
    assert len(backups) == 1
    shutil.copy2(backups[0], into)

    assert rows_of(into) == before_jobs
    assert rows_of(into, "job_totals", "field") == before_totals


def test_a_second_apply_inserts_nothing(monkeypatch, capsys, tmp_path):
    into = make_db(tmp_path / "into.db", [job(T0)])
    source = make_db(tmp_path / "src.db", [job(T0 - 86400, filename="older.gcode")])
    run_main(monkeypatch, capsys, into, source, "--apply")
    first = rows_of(into)
    out = run_main(monkeypatch, capsys, into, source, "--apply")
    assert "to insert: 0" in out
    assert rows_of(into) == first


def test_existing_job_ids_are_never_rewritten(monkeypatch, capsys, tmp_path):
    """Renumbering would rewrite the identity of rows a client may already
    hold — a Fluidd tab left open across the merge would then delete by an id
    that names a different print. Inserted rows continue after the target's.
    """
    into = make_db(tmp_path / "into.db",
                   [job(T0, job_id=41, filename="a.gcode"),
                    job(T0 + 20000, job_id=42, filename="b.gcode")])
    source = make_db(tmp_path / "src.db",
                     [job(T0 - 86400, filename="ancient.gcode")])
    run_main(monkeypatch, capsys, into, source, "--apply")
    by_name = {r["filename"]: r["job_id"] for r in rows_of(into)}
    assert by_name["a.gcode"] == 41
    assert by_name["b.gcode"] == 42
    # The oldest print by time gets the HIGHEST id. That inversion is the
    # deliberate trade: ids stay stable, ordering is start_time's job.
    assert by_name["ancient.gcode"] == 43
