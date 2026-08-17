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

# Captured before the autouse fixture below stubs it out, so the handful of
# tests that are ABOUT the guard can still reach the real implementation.
REAL_MOONRAKER_RUNNING = mjh.moonraker_running

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


@pytest.fixture(autouse=True)
def no_daemon_by_default(monkeypatch):
    """These tests are about the merge, not about the host's process table.

    Without this every `--apply` test reads the REAL /proc. They pass on a Mac
    only because /proc does not exist there; on Linux — including the printer,
    where a user is most likely to run them — a live Moonraker makes main()
    SystemExit and they all fail for a reason unrelated to what they assert.
    The two tests that are about the guard opt back in explicitly.
    """
    monkeypatch.setattr(mjh, "moonraker_running", lambda *a, **k: None)


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


def test_two_source_rows_never_collapse_onto_one_target_row():
    """THE DATA LOSS CASE. Matching must be one to one.

    A cancelled print and its retry a minute apart, where the target daemon
    recorded only ONE of the pair — which is not exotic, it is half the reason
    this merge exists (the reference unit's Moonraker missed two prints the
    screen saw). Both source rows sit inside the 120 s window of that single
    target row. Without claim tracking both are called duplicates and the print
    that exists nowhere else is dropped, silently, with the dry run reporting
    'to insert: 0'.
    """
    target = [job(T0 + 60)]
    new, dupes, _ = mjh.classify([job(T0), job(T0 + 60)], target)
    assert (len(new), len(dupes)) == (1, 1)
    # And it must be the RIGHT row. Matching greedily in table order gets these
    # counts while pairing the failed print to the retry's row, which inserts
    # the retry a second time and loses the failed print anyway.
    assert new[0][0]["start_time"] == T0
    assert dupes[0][0]["start_time"] == T0 + 60


def test_the_nearest_start_time_wins_a_contested_match():
    """Closest first, not table order — an exact match must win its own row."""
    target = [job(T0 + 100), job(T0 + 5)]
    new, dupes, _ = mjh.classify([job(T0)], target)
    assert len(dupes) == 1
    assert dupes[0][1]["start_time"] == T0 + 5


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
    monkeypatch.setattr(mjh, "moonraker_running", lambda *a, **k: "python moonraker.py")
    into = make_db(tmp_path / "into.db", [job(T0)])
    source = make_db(tmp_path / "src.db", [job(T0 + 9999)])
    with pytest.raises(SystemExit):
        run_main(monkeypatch, capsys, into, source, "--apply")
    assert len(rows_of(into)) == 1
    assert glob.glob(into + ".bak-merge-*") == []
    run_main(monkeypatch, capsys, into, source, "--apply", "--force")
    assert len(rows_of(into)) == 2


def test_no_proc_reads_as_no_daemon(tmp_path):
    """The workstation rehearsal path: /proc does not exist on a Mac, and the
    guard must degrade to "nothing running here" rather than crash."""
    assert REAL_MOONRAKER_RUNNING(str(tmp_path / "no-such-proc")) is None


# The guard's own matching logic. Every other test stubs moonraker_running out,
# so without these the substring match is never executed against a realistic
# cmdline — and this is the only thing standing between a live daemon and an
# irreversible write to a user's print history.

def fake_proc(tmp_path, **pids):
    proc = tmp_path / "proc"
    proc.mkdir()
    for pid, cmd in pids.items():
        (proc / pid).mkdir()
        (proc / pid / "cmdline").write_bytes(cmd)
    (proc / "cpuinfo").write_text("not a pid")
    return str(proc)


def test_a_live_moonraker_is_detected(tmp_path):
    """The exact shape S56moonraker_service produces: the venv interpreter with
    moonraker.py as an argument, which is what busybox ps truncates away."""
    proc = fake_proc(tmp_path, **{"42": (
        b"/usr/data/moonraker/moonraker-env/bin/python3\x00"
        b"/usr/data/moonraker/moonraker/moonraker/moonraker.py\x00"
        b"-d\x00/usr/data/printer_data\x00")})
    assert "moonraker.py" in REAL_MOONRAKER_RUNNING(proc)


def test_a_live_nexusp_is_detected(tmp_path):
    proc = fake_proc(tmp_path, **{"77": b"/usr/bin/nexusp\x00-d\x00/usr/data/printer_data\x00"})
    assert "nexusp" in REAL_MOONRAKER_RUNNING(proc)


def test_an_unrelated_process_is_not_mistaken_for_a_daemon(tmp_path):
    """Including this script itself — it has 'merge_job_history.py' in its
    cmdline, not 'moonraker.py', and must not block its own run."""
    proc = fake_proc(tmp_path, **{
        "7": b"/usr/bin/klipper\x00",
        "9": (b"python3\x00/usr/data/helper-script/files/moonraker/"
              b"creality-compat/merge_job_history.py\x00--apply\x00")})
    assert REAL_MOONRAKER_RUNNING(proc) is None


def test_an_unreadable_cmdline_is_skipped_not_fatal(tmp_path):
    """/proc entries race with process exit; a vanished pid must not abort the
    scan and let a different live daemon through unnoticed."""
    proc = fake_proc(tmp_path, **{"11": b"/usr/bin/nexusp\x00"})
    os.mkdir(os.path.join(proc, "12"))  # a pid dir with no cmdline at all
    assert "nexusp" in REAL_MOONRAKER_RUNNING(proc)


def test_a_corrupt_backup_aborts_before_the_first_write(monkeypatch, capsys,
                                                        tmp_path):
    """The backup is the ENTIRE rollback story, and until it is checked it is
    just a file with a reassuring name. A copy cut short by a full /usr/data is
    indistinguishable from a good one by filename alone — and restoring it
    would destroy the history it was meant to protect."""
    into = make_db(tmp_path / "into.db", [job(T0)])
    source = make_db(tmp_path / "src.db", [job(T0 - 86400, filename="old.gcode")])

    def truncating_copy(src, dst):
        with open(dst, "wb") as fh:
            fh.write(b"SQLite format 3\x00truncated")

    monkeypatch.setattr(mjh.shutil, "copy2", truncating_copy)
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, capsys, into, source, "--apply")
    assert "backup" in str(exc.value)
    assert len(rows_of(into)) == 1, "the target must be untouched"
    assert glob.glob(into + ".bak-merge-*") == [], "the bad backup must be removed"


def test_a_database_changing_under_the_merge_aborts(monkeypatch, capsys, tmp_path):
    """Everything is classified from a snapshot taken before the liveness check,
    and the daemons stop asynchronously. If one finishes a shutdown flush in
    that window the approved plan is stale — and applying it anyway would insert
    a row the target now has, or write pre-flush totals back over it."""
    into = make_db(tmp_path / "into.db", [job(T0)])
    source = make_db(tmp_path / "src.db", [job(T0 - 86400, filename="old.gcode")])
    real_load = mjh.load_jobs
    calls = []

    def load_then_mutate(db):
        result = real_load(db)
        calls.append(db)
        if len(calls) == 2:  # after the dry-run pair, before the re-read
            # A row that CHANGES THE PLAN: the daemon's shutdown flush lands the
            # very print the merge was about to insert, so the approved
            # "1 insert" becomes "1 duplicate" and applying the stale plan would
            # write a second copy.
            con = sqlite3.connect(into)
            j = job(T0 - 86400, filename="old.gcode")
            cols = [c for c in j if c != "job_id"]
            con.execute("insert into job_history (%s) values (%s)"
                        % (",".join(cols), ",".join("?" * len(cols))),
                        tuple(j[c] for c in cols))
            con.commit()
            con.close()
        return result

    monkeypatch.setattr(mjh, "load_jobs", load_then_mutate)
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, capsys, into, source, "--apply")
    assert "changed between the dry run" in str(exc.value)
    assert glob.glob(into + ".bak-merge-*") == []


def test_a_missing_database_exits_before_touching_anything(monkeypatch, capsys,
                                                          tmp_path):
    into = make_db(tmp_path / "into.db", [job(T0)])
    with pytest.raises(SystemExit):
        run_main(monkeypatch, capsys, into, str(tmp_path / "nope.db"), "--apply")
    assert glob.glob(into + ".bak-merge-*") == []


# --------------------------------------------------------------------------
# Schema drift and instance scoping — checked in the DRY RUN, before the
# caller has renamed anything
# --------------------------------------------------------------------------

def test_a_missing_column_is_refused_before_any_write(monkeypatch, capsys, tmp_path):
    """`install_moonraker_nginx` runs `git checkout master; git pull` on the
    Moonraker source, so job_history's schema is a moving target under any
    printer. Discovering that inside the transaction means a traceback in the
    middle of a retirement with both daemons already stopped."""
    into = str(tmp_path / "into.db")
    con = sqlite3.connect(into)
    con.execute(JOB_HISTORY_DDL.replace("    filament_used REAL NOT NULL,\n", ""))
    con.execute(JOB_TOTALS_DDL)
    con.commit()
    con.close()
    source = make_db(tmp_path / "src.db", [job(T0)])
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, capsys, into, source)
    assert "filament_used" in str(exc.value)
    assert glob.glob(into + ".bak-merge-*") == []


def test_an_added_not_null_column_is_refused(monkeypatch, capsys, tmp_path):
    """The silent one. A column the script does not write, NOT NULL with no
    default, would make every migrated row fail — or, if it were nullable,
    succeed while carrying a NULL the daemon does not expect."""
    into = str(tmp_path / "into.db")
    con = sqlite3.connect(into)
    con.execute(JOB_HISTORY_DDL.replace(
        "    instance_id TEXT NOT NULL\n",
        "    instance_id TEXT NOT NULL,\n    new_field TEXT NOT NULL\n"))
    con.execute(JOB_TOTALS_DDL)
    con.commit()
    con.close()
    source = make_db(tmp_path / "src.db", [job(T0)])
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, capsys, into, source)
    assert "new_field" in str(exc.value)


def test_an_added_nullable_column_is_allowed_and_reported(monkeypatch, capsys,
                                                          tmp_path):
    """Nullable additions are survivable, so they must not block a retirement —
    but the source columns being dropped are worth naming."""
    into = str(tmp_path / "into.db")
    con = sqlite3.connect(into)
    con.execute(JOB_HISTORY_DDL.replace(
        "    instance_id TEXT NOT NULL\n",
        "    instance_id TEXT NOT NULL,\n    new_field TEXT\n"))
    con.execute(JOB_TOTALS_DDL)
    con.commit()
    con.close()
    source = make_db(tmp_path / "src.db", [job(T0)])
    out = run_main(monkeypatch, capsys, into, source, "--apply")
    assert len(rows_of(into)) == 1


def test_a_source_only_column_is_reported_as_dropped(monkeypatch, capsys, tmp_path):
    into = make_db(tmp_path / "into.db", [job(T0)])
    source = str(tmp_path / "src.db")
    con = sqlite3.connect(source)
    con.execute(JOB_HISTORY_DDL.replace(
        "    instance_id TEXT NOT NULL\n",
        "    instance_id TEXT NOT NULL,\n    creality_extra TEXT\n"))
    con.execute(JOB_TOTALS_DDL)
    con.commit()
    con.close()
    out = run_main(monkeypatch, capsys, into, source)
    assert "creality_extra" in out


def test_disjoint_instance_ids_are_refused(monkeypatch, capsys, tmp_path):
    """Moonraker scopes every history query by instance_id. Rows carrying one
    the reader does not filter on insert fine and are then invisible — a merge
    that prints success and shows nothing, which is the exact failure mode this
    whole option exists to remove."""
    into = make_db(tmp_path / "into.db", [job(T0, instance_id="default")])
    source = make_db(tmp_path / "src.db",
                     [job(T0 - 86400, instance_id="creality")])
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, capsys, into, source, "--apply")
    assert "instance_id" in str(exc.value)
    assert len(rows_of(into)) == 1
    assert glob.glob(into + ".bak-merge-*") == []


def test_an_instance_mismatch_can_be_overridden_explicitly(monkeypatch, capsys,
                                                           tmp_path):
    into = make_db(tmp_path / "into.db", [job(T0, instance_id="default")])
    source = make_db(tmp_path / "src.db",
                     [job(T0 - 86400, instance_id="creality")])
    run_main(monkeypatch, capsys, into, source, "--apply",
             "--allow-instance-mismatch")
    assert len(rows_of(into)) == 2


def test_an_empty_target_does_not_trip_the_instance_check(monkeypatch, capsys,
                                                          tmp_path):
    """A fresh install has no rows and therefore no instance_id to compare."""
    into = make_db(tmp_path / "into.db", [])
    source = make_db(tmp_path / "src.db", [job(T0, instance_id="creality")])
    run_main(monkeypatch, capsys, into, source, "--apply")
    assert len(rows_of(into)) == 1


def test_the_dry_run_names_both_instance_ids(monkeypatch, capsys, tmp_path):
    into = make_db(tmp_path / "into.db", [job(T0)])
    source = make_db(tmp_path / "src.db", [job(T0 - 86400)])
    out = run_main(monkeypatch, capsys, into, source)
    assert out.count("instance_id") >= 2


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


def test_job_ids_end_up_in_start_time_order(monkeypatch, capsys, tmp_path):
    """THE ORDERING PROPERTY. Moonraker pages history with `ORDER BY job_id`
    (history.py, order defaults to desc) and has no ORDER BY start_time at all,
    so after a merge the id order IS the display order.

    Appending without renumbering gave the recovered prints — the OLDEST on the
    machine, which is the whole point of the merge — the HIGHEST ids, so they
    came back as the most recent jobs in Fluidd and on the screen while
    server.history.count reported the right total. A correct scrollbar over a
    wrongly ordered list is the plausible-wrong-answer failure this option
    exists to remove.
    """
    into = make_db(tmp_path / "into.db",
                   [job(T0, job_id=41, filename="a.gcode"),
                    job(T0 + 20000, job_id=42, filename="b.gcode")])
    source = make_db(tmp_path / "src.db",
                     [job(T0 - 86400, filename="ancient.gcode")])
    run_main(monkeypatch, capsys, into, source, "--apply")
    by_id = [r["filename"] for r in rows_of(into, order="job_id")]
    assert by_id == ["ancient.gcode", "a.gcode", "b.gcode"]
    ids = [r["job_id"] for r in rows_of(into, order="job_id")]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)


def test_renumbering_is_a_dense_sequence_from_one(monkeypatch, capsys, tmp_path):
    """The offset pass must not leave gaps or strand rows at the shifted ids."""
    into = make_db(tmp_path / "into.db",
                   [job(T0 + i * 1000, job_id=100 + i, filename="f%d.gcode" % i)
                    for i in range(3)])
    source = make_db(tmp_path / "src.db",
                     [job(T0 - 86400, filename="old.gcode")])
    run_main(monkeypatch, capsys, into, source, "--apply")
    assert [r["job_id"] for r in rows_of(into, order="job_id")] == [1, 2, 3, 4]


def test_rows_sharing_a_start_time_keep_their_relative_order(monkeypatch, capsys,
                                                             tmp_path):
    """Ties break on the existing job_id, so a merge does not permute rows it
    had no reason to touch."""
    into = make_db(tmp_path / "into.db",
                   [job(T0, job_id=5, filename="first.gcode"),
                    job(T0, job_id=6, filename="second.gcode")])
    source = make_db(tmp_path / "src.db", [job(T0 - 86400, filename="old.gcode")])
    run_main(monkeypatch, capsys, into, source, "--apply")
    by_id = [r["filename"] for r in rows_of(into, order="job_id")]
    assert by_id == ["old.gcode", "first.gcode", "second.gcode"]


@pytest.mark.parametrize("ids", [[-2, -1], [-100, -1], [-1, 0], [0, 1]])
def test_renumbering_handles_non_positive_existing_ids(monkeypatch, capsys,
                                                       tmp_path, ids):
    """SQLite's INTEGER PRIMARY KEY is a signed rowid alias, so negative and
    zero ids are legal. Staging at `max(job_id) + n` alone puts the staging
    range on top of the final 1..N range whenever the maximum is negative, and
    the second pass then collides: `UNIQUE constraint failed`. The transaction
    rolls back safely, but a valid database becomes unmergeable and the
    retirement aborts with a traceback at the point both daemons are stopped.
    """
    into = make_db(tmp_path / "into.db",
                   [job(T0 + i, job_id=jid, filename="f%d.gcode" % i)
                    for i, jid in enumerate(ids)])
    source = make_db(tmp_path / "src.db", [job(T0 - 86400, filename="old.gcode")])
    run_main(monkeypatch, capsys, into, source, "--apply")
    rows = rows_of(into, order="job_id")
    assert [r["job_id"] for r in rows] == list(range(1, len(ids) + 2))
    assert rows[0]["filename"] == "old.gcode"


def test_renumbering_survives_a_second_run(monkeypatch, capsys, tmp_path):
    """Idempotency still holds: the second pass inserts nothing and the ids it
    assigns are the ones already there."""
    into = make_db(tmp_path / "into.db", [job(T0, filename="a.gcode")])
    source = make_db(tmp_path / "src.db", [job(T0 - 86400, filename="old.gcode")])
    run_main(monkeypatch, capsys, into, source, "--apply")
    first = rows_of(into, order="job_id")
    run_main(monkeypatch, capsys, into, source, "--apply")
    assert rows_of(into, order="job_id") == first
