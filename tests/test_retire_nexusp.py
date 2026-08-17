#!/usr/bin/env python3
"""Offline checks for scripts/retire_nexusp.sh — no printer, no daemons.

    python3 -m pytest -q tests/

WHY THIS FILE EXISTS
--------------------
retire_nexusp.sh runs as root and, in one uninterruptible sequence, stops two
daemons, rewrites a print-history database, renames an init script and re-points
two config files. Until this file existed the only automated check on any of it
was `bash -n`, which proves the syntax parses and nothing else.

Two defects found by reading rather than running motivated it, and both are
pinned below:

  1. THE ERREXIT CONTRACT. `set -e; return 1` re-arms errexit and then hands the
     caller a failing command — helper.sh sets -e globally and sources every
     script into that same shell, so the whole helper exited at the call site,
     at the point where both daemons are already stopped, with no message and no
     menu to return to. The guard that was supposed to catch it never ran.
  2. ABSENCE MUST NOT BE AN ERROR. A predicate loop that finds nothing returns
     the last failed `[ -f ]`. `svc="$(nexusp_enabled_service)"` then aborts the
     helper under the same global errexit.

Neither is visible in a diff and neither is catchable by any check this repo had.

The sed round-trips are here for a different reason: the substitutions use `\\s`,
a GNU extension, and busybox sed on the printer may not honour it. Running them
against the REAL config files this repo ships is the only thing that would
surface that.

⚠ Add cases as `test_*` functions. A file named test_*.py whose assertions live
in a hand-rolled runner gets collected and runs nothing while reporting green.
"""
import os
import shutil
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "retire_nexusp.sh")


def _gnu_sed_dir(tmp_path):
    """A PATH entry whose `sed` accepts GNU `-i` with no argument, or None.

    The script uses `sed -i` the way every other script in this repo does, which
    is GNU/busybox syntax. BSD sed (the macOS default) requires an argument
    there, so on a Mac these tests would fail for a reason that has nothing to
    do with the code. Use gsed when it is installed, and skip honestly when it
    is not, rather than quietly not testing the substitutions.
    """
    if subprocess.run(["sed", "--version"], capture_output=True).returncode == 0:
        return None  # already GNU, no shim needed
    gsed = shutil.which("gsed")
    if gsed is None:
        pytest.skip("needs GNU sed (`brew install gnu-sed`) — the script uses "
                    "`sed -i` as busybox and GNU spell it")
    # exist_ok / already-linked: several tests call run_sh more than once with
    # the same tmp_path, and a second invocation must reuse the shim rather
    # than blow up on it.
    shim = tmp_path / "gnubin"
    shim.mkdir(exist_ok=True)
    link = shim / "sed"
    if not link.exists():
        os.symlink(gsed, str(link))
    return str(shim)


def run_sh(body, tmp_path, want_sed=False):
    """Source retire_nexusp.sh with every path pointed into tmp_path, run `body`.

    `set -e` is on, exactly as helper.sh has it, because that is the condition
    half of these tests exist to check.
    """
    env = dict(os.environ)
    if want_sed:
        shim = _gnu_sed_dir(tmp_path)
        if shim:
            env["PATH"] = shim + os.pathsep + env["PATH"]
    initd = tmp_path / "initd"
    initd.mkdir(exist_ok=True)
    preamble = f"""
set -e
white=; yellow=; cyan=; green=; darkred=; red=
error_msg() {{ echo "ERR: $1"; }}
ok_msg() {{ echo "OK: $1"; }}
NEXUSP_SERVICE={initd}/CS56nexusp_service
NEXUSP_SERVICE_LEGACY={initd}/S56nexusp_service
MOONRAKER_CFG={tmp_path}/moonraker.conf
NGINX_CONF_FILE={tmp_path}/nginx.conf
MOONRAKER_DB={tmp_path}/moonraker-sql.db
NEXUSP_DB={tmp_path}/nexusp-sql.db
MOONRAKER_ENV_PYTHON={tmp_path}/nonexistent-python
MERGE_JOB_HISTORY_URL={tmp_path}/merge.py
CREALITY_COMPAT_FILE={tmp_path}/mr/moonraker/moonraker/components/creality_compat.py
CREALITY_COMPAT_URL={tmp_path}/source_component.py
. {SCRIPT}
"""
    return subprocess.run(["bash", "-c", preamble + body],
                          capture_output=True, text=True, env=env, cwd=REPO)


# --------------------------------------------------------------------------
# The errexit contract — the defect that killed the helper mid-retirement
# --------------------------------------------------------------------------

def test_a_refusing_merge_leaves_the_caller_in_control(tmp_path):
    """The merge refuses (a daemon is alive, a schema drifted, the user says no)
    and the CALLER must get to run its rollback. Before this was fixed the shell
    exited inside the function, at stage 3, with Moonraker and nexusp both
    stopped and the user dropped to a bare prompt."""
    (tmp_path / "moonraker-sql.db").write_text("")
    (tmp_path / "nexusp-sql.db").write_text("")
    (tmp_path / "merge.py").write_text("import sys\nsys.exit(1)\n")
    r = run_sh("""
if ! nexusp_merge_history to-moonraker; then
  echo HANDLED
  exit 0
fi
echo UNEXPECTED_SUCCESS
exit 2
""", tmp_path)
    assert "HANDLED" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 0


def test_declining_the_merge_prompt_is_reported_as_a_refusal(tmp_path):
    """The confirmation gate: answering anything but y must abort the merge and
    hand a non-zero status back, not fall through to --apply."""
    (tmp_path / "moonraker-sql.db").write_text("")
    (tmp_path / "nexusp-sql.db").write_text("")
    (tmp_path / "merge.py").write_text(
        "import sys\n"
        "open(%r, 'a').write(' '.join(sys.argv[1:]) + chr(10))\n"
        % str(tmp_path / "calls.log"))
    r = run_sh("""
if ! echo n | nexusp_merge_history to-moonraker; then
  echo DECLINED
  exit 0
fi
echo UNEXPECTED_APPLY
exit 2
""", tmp_path)
    assert "DECLINED" in r.stdout, r.stdout + r.stderr
    calls = (tmp_path / "calls.log").read_text()
    assert "--apply" not in calls, calls


def test_nothing_to_merge_is_not_a_refusal(tmp_path):
    """One database missing means a printer that never ran both daemons. That
    is a normal state, not an error, and must not abort the retirement."""
    (tmp_path / "moonraker-sql.db").write_text("")
    r = run_sh("""
if nexusp_merge_history to-moonraker; then echo CONTINUED; fi
""", tmp_path)
    assert "CONTINUED" in r.stdout, r.stdout + r.stderr


# --------------------------------------------------------------------------
# The predicates — absence is an answer, not an error
# --------------------------------------------------------------------------

STATE_PROBE = """
state() {
  p=no; r=no; a=no; x=no
  nexusp_present && p=yes
  nexusp_retired && r=yes
  nexusp_absent && a=yes
  nexusp_resurrected && x=yes
  echo "present=$p retired=$r absent=$a resurrected=$x"
}
state
"""


def test_no_nexusp_at_all(tmp_path):
    r = run_sh(STATE_PROBE, tmp_path)
    assert "present=no retired=no absent=yes resurrected=no" in r.stdout
    assert r.returncode == 0, "a predicate that finds nothing must not abort"


def test_nexusp_enabled(tmp_path):
    (tmp_path / "initd").mkdir(exist_ok=True)
    (tmp_path / "initd" / "CS56nexusp_service").write_text("#!/bin/sh\n")
    r = run_sh(STATE_PROBE, tmp_path)
    assert "present=yes retired=no absent=no resurrected=no" in r.stdout


def test_nexusp_retired(tmp_path):
    (tmp_path / "initd").mkdir(exist_ok=True)
    (tmp_path / "initd" / "disabled.CS56nexusp_service").write_text("#!/bin/sh\n")
    r = run_sh(STATE_PROBE, tmp_path)
    assert "present=no retired=yes absent=no resurrected=no" in r.stdout


def test_a_firmware_update_resurrecting_the_service_is_detected(tmp_path):
    """Both forms present. /etc/init.d/rcK then starts the recreated one from
    the CS pass while Moonraker starts from the S pass, so nexusp loses the
    :7125 bind and dies silently at every boot."""
    (tmp_path / "initd").mkdir(exist_ok=True)
    (tmp_path / "initd" / "CS56nexusp_service").write_text("#!/bin/sh\n")
    (tmp_path / "initd" / "disabled.CS56nexusp_service").write_text("#!/bin/sh\n")
    r = run_sh(STATE_PROBE, tmp_path)
    assert "present=yes retired=yes absent=no resurrected=yes" in r.stdout


def test_the_legacy_s_prefix_is_recognised_too(tmp_path):
    """The init script name varies by firmware; tools.sh already probes both."""
    (tmp_path / "initd").mkdir(exist_ok=True)
    (tmp_path / "initd" / "S56nexusp_service").write_text("#!/bin/sh\n")
    r = run_sh(STATE_PROBE, tmp_path)
    assert "present=yes" in r.stdout


def test_an_absent_service_does_not_abort_a_variable_assignment(tmp_path):
    """The specific shape that bit: command substitution in an assignment is a
    simple command, so a non-zero function status kills the shell under -e."""
    r = run_sh("""
svc="$(nexusp_enabled_service)"
disabled="$(nexusp_disabled_service)"
port="$(nexusp_moonraker_port)"
echo "SURVIVED svc=[$svc] disabled=[$disabled] port=[$port]"
""", tmp_path)
    assert "SURVIVED svc=[] disabled=[] port=[]" in r.stdout, r.stdout + r.stderr


def test_a_config_without_a_port_line_reads_as_unknown(tmp_path):
    """grep finding nothing must not abort the helper — the pipe into sed is
    what keeps the status zero, so a refactor that drops it would be caught."""
    (tmp_path / "moonraker.conf").write_text("[server]\nhost: 0.0.0.0\n")
    r = run_sh('port="$(nexusp_moonraker_port)"; echo "PORT=[$port]"', tmp_path)
    assert "PORT=[]" in r.stdout, r.stdout + r.stderr


# --------------------------------------------------------------------------
# The port swap, against the config files this repo actually ships
# --------------------------------------------------------------------------

def _real_configs(tmp_path):
    shutil.copy(os.path.join(REPO, "files", "moonraker", "moonraker.conf"),
                str(tmp_path / "moonraker.conf"))
    (tmp_path / "nginx.conf").write_text(
        "upstream apiserver {\n  server 127.0.0.1:7126;\n}\n")


def test_the_port_swap_round_trips_byte_for_byte(tmp_path):
    """7126 -> 7125 -> 7126 must land exactly where it started. The shipped
    moonraker.conf says 7125, so the fixture starts it at 7126 the way a
    configured printer has it."""
    _real_configs(tmp_path)
    conf = tmp_path / "moonraker.conf"
    conf.write_text(conf.read_text().replace("port: 7125", "port: 7126"))
    before = conf.read_text(), (tmp_path / "nginx.conf").read_text()
    r = run_sh("nexusp_set_moonraker_port 7125 7126 > /dev/null\n"
               "nexusp_set_moonraker_port 7126 7125 > /dev/null\n"
               "echo DONE", tmp_path, want_sed=True)
    assert "DONE" in r.stdout, r.stdout + r.stderr
    assert (conf.read_text(), (tmp_path / "nginx.conf").read_text()) == before


def test_the_port_swap_moves_moonraker_and_nginx_together(tmp_path):
    """They must always agree. A box where they disagree serves 502s from
    Fluidd and nothing says why."""
    _real_configs(tmp_path)
    conf = tmp_path / "moonraker.conf"
    conf.write_text(conf.read_text().replace("port: 7125", "port: 7126"))
    r = run_sh("nexusp_set_moonraker_port 7125 7126 > /dev/null\n"
               'echo "PORT=$(nexusp_moonraker_port)"', tmp_path, want_sed=True)
    assert "PORT=7125" in r.stdout, r.stdout + r.stderr
    assert "server 127.0.0.1:7125;" in (tmp_path / "nginx.conf").read_text()


def test_the_port_swap_is_idempotent(tmp_path):
    """Called twice in the same direction, the second call is a no-op — which
    is what makes it safe for configure_moonraker_nginx_k1_2025 to re-run it on
    every Moonraker reinstall."""
    _real_configs(tmp_path)
    run_sh("nexusp_set_moonraker_port 7125 7126 > /dev/null", tmp_path,
           want_sed=True)
    once = (tmp_path / "moonraker.conf").read_text()
    run_sh("nexusp_set_moonraker_port 7125 7126 > /dev/null", tmp_path,
           want_sed=True)
    assert (tmp_path / "moonraker.conf").read_text() == once


# --------------------------------------------------------------------------
# The compat component, on both moonraker.conf branches
# --------------------------------------------------------------------------

def _component_tree(tmp_path):
    (tmp_path / "mr" / "moonraker" / "moonraker" / "components").mkdir(parents=True)
    (tmp_path / "mr" / "moonraker" / ".git" / "info").mkdir(parents=True)
    (tmp_path / "mr" / "moonraker" / ".git" / "info" / "exclude").write_text("")
    (tmp_path / "source_component.py").write_text("# component\n")


def test_the_shipped_conf_block_is_uncommented_and_recommented(tmp_path):
    """The `[timelapse]` convention: the block ships commented and the install
    uncomments it. A round trip must leave the file usable either way."""
    _component_tree(tmp_path)
    shutil.copy(os.path.join(REPO, "files", "moonraker", "moonraker.conf"),
                str(tmp_path / "moonraker.conf"))
    conf = tmp_path / "moonraker.conf"
    assert "#[creality_compat]" in conf.read_text(), "shipped conf must carry it"
    r = run_sh("nexusp_install_compat_component > /dev/null\n"
               'grep -c "^\\[creality_compat\\]" ' + str(conf), tmp_path,
               want_sed=True)
    assert r.stdout.strip().endswith("1"), r.stdout + r.stderr
    assert os.path.islink(str(tmp_path / "mr" / "moonraker" / "moonraker" /
                              "components" / "creality_compat.py"))
    run_sh("nexusp_remove_compat_component > /dev/null", tmp_path, want_sed=True)
    assert "#[creality_compat]" in conf.read_text()
    assert not os.path.exists(str(tmp_path / "mr" / "moonraker" / "moonraker" /
                                  "components" / "creality_compat.py"))


def test_a_conf_predating_this_option_gets_the_block_appended(tmp_path):
    """The majority case. install_moonraker_nginx only rewrites moonraker.conf
    when Moonraker itself is reinstalled, so most users' configs have no block
    to uncomment — and without the append branch the component would be linked
    and never loaded, leaving the file browser broken with nothing to show."""
    _component_tree(tmp_path)
    (tmp_path / "moonraker.conf").write_text("[server]\nport: 7126\n\n[history]\n\n")
    r = run_sh("nexusp_install_compat_component > /dev/null\n"
               'grep -c "^\\[creality_compat\\]" ' +
               str(tmp_path / "moonraker.conf"), tmp_path, want_sed=True)
    assert r.stdout.strip().endswith("1"), r.stdout + r.stderr
    assert "generate_thumbnails: True" in (tmp_path / "moonraker.conf").read_text()


def test_installing_twice_adds_one_block_and_one_exclude_line(tmp_path):
    """Idempotency matters because configure_moonraker_nginx_k1_2025 re-runs
    this on every Moonraker reinstall of a retired box."""
    _component_tree(tmp_path)
    (tmp_path / "moonraker.conf").write_text("[server]\nport: 7126\n\n")
    run_sh("nexusp_install_compat_component > /dev/null", tmp_path, want_sed=True)
    run_sh("nexusp_install_compat_component > /dev/null", tmp_path, want_sed=True)
    conf = (tmp_path / "moonraker.conf").read_text()
    exclude = (tmp_path / "mr" / "moonraker" / ".git" / "info" / "exclude").read_text()
    assert conf.count("[creality_compat]") == 1
    assert exclude.count("creality_compat.py") == 1


def test_removal_drops_the_git_exclude_entry(tmp_path):
    """Symmetric with install: the entry exists so update_manager stops
    reporting the repo as dirty, and it has no business outliving the link."""
    _component_tree(tmp_path)
    (tmp_path / "moonraker.conf").write_text("[server]\nport: 7126\n\n")
    run_sh("nexusp_install_compat_component > /dev/null", tmp_path, want_sed=True)
    run_sh("nexusp_remove_compat_component > /dev/null", tmp_path, want_sed=True)
    exclude = (tmp_path / "mr" / "moonraker" / ".git" / "info" / "exclude").read_text()
    assert "creality_compat.py" not in exclude


# --------------------------------------------------------------------------
# Write failures are reported, not left to errexit
#
# A full /usr/data is the classic K1 failure — users pack it with gcode. Under
# helper.sh's global `set -e` an unguarded `sed -i` or `>>` failure exits the
# whole helper mid-swap: both daemons stopped, no rollback, no menu.
# --------------------------------------------------------------------------

@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_an_unwritable_conf_fails_the_port_swap_instead_of_the_helper(tmp_path):
    """The DIRECTORY has to be read-only, not the file: `sed -i` writes a temp
    beside the target and renames over it, so the target's own mode does not
    stop it. A full or read-only /usr/data presents exactly this way."""
    locked = tmp_path / "locked"
    locked.mkdir()
    shutil.copy(os.path.join(REPO, "files", "moonraker", "moonraker.conf"),
                str(locked / "moonraker.conf"))
    locked.chmod(0o555)
    try:
        r = run_sh(f"""
MOONRAKER_CFG={locked}/moonraker.conf
NGINX_CONF_FILE={tmp_path}/no-such-nginx.conf
if ! nexusp_set_moonraker_port 7126 7125; then echo REPORTED; exit 0; fi
echo SILENT_SUCCESS; exit 2
""", tmp_path, want_sed=True)
    finally:
        locked.chmod(0o755)
    assert "REPORTED" in r.stdout, r.stdout + r.stderr


def test_an_unlinkable_component_fails_the_install_instead_of_the_helper(tmp_path):
    """No components directory at all — the shape a partially extracted or
    removed Moonraker leaves behind."""
    (tmp_path / "source_component.py").write_text("# component\n")
    (tmp_path / "moonraker.conf").write_text("[server]\nport: 7126\n\n")
    r = run_sh("""
if ! nexusp_install_compat_component; then echo REPORTED; exit 0; fi
echo SILENT_SUCCESS; exit 2
""", tmp_path)
    assert "REPORTED" in r.stdout, r.stdout + r.stderr


def test_a_failed_nginx_reload_is_reported(tmp_path):
    """nginx is the only thing the browser talks to. A reload that quietly fails
    leaves it proxying the now-dead old port, so Fluidd 502s while Moonraker
    itself is perfectly healthy — and probing Moonraker directly cannot see it."""
    r = run_sh("""
NGINX_BIN=/nonexistent/nginx
if ! nexusp_reload_nginx; then echo REPORTED; exit 0; fi
echo SILENT_SUCCESS; exit 2
""", tmp_path)
    assert "REPORTED" in r.stdout, r.stdout + r.stderr


def test_a_closed_stdin_cancels_rather_than_killing_the_helper(tmp_path):
    """`read` returns non-zero on EOF, and under helper.sh's global set -e that
    exits the whole helper with no message. Piping input, running over a dropped
    SSH session, or any non-interactive invocation hits it. Failing to read an
    answer is a "no", not a crash."""
    (tmp_path / "initd").mkdir(exist_ok=True)
    (tmp_path / "initd" / "CS56nexusp_service").write_text("#!/bin/sh\n")
    (tmp_path / "mr").mkdir(exist_ok=True)
    r = run_sh(f"""
top_line(){{ :; }}; inner_line(){{ :; }}; hr(){{ :; }}; bottom_line(){{ :; }}; title(){{ :; }}
MOONRAKER_FOLDER={tmp_path}/mr
retire_nexusp < /dev/null
echo SURVIVED
""", tmp_path)
    assert "SURVIVED" in r.stdout, r.stdout + r.stderr
    assert "canceled" in r.stdout


def test_the_rollback_cannot_abort_partway_through(tmp_path):
    """A rollback that can itself exit under errexit turns a detected failure
    into the persistent dead-port state it exists to prevent, halfway through
    undoing it. Every step is best-effort and the outcome is reported from what
    the printer looks like afterwards."""
    (tmp_path / "initd").mkdir(exist_ok=True)
    locked = tmp_path / "locked"
    locked.mkdir()
    shutil.copy(os.path.join(REPO, "files", "moonraker", "moonraker.conf"),
                str(locked / "moonraker.conf"))
    locked.chmod(0o555)
    try:
        r = run_sh(f"""
MOONRAKER_CFG={locked}/moonraker.conf
NGINX_CONF_FILE={tmp_path}/no-such-nginx.conf
start_moonraker(){{ echo "(moonraker restarted)"; }}
NEXUSP_RETIRE_STAGE=8
nexusp_rollback_retire
echo REACHED_THE_END
""", tmp_path, want_sed=True)
    finally:
        locked.chmod(0o755)
    assert "REACHED_THE_END" in r.stdout, r.stdout + r.stderr
    assert "(moonraker restarted)" in r.stdout, "daemons must be restarted anyway"
    assert "did not fully complete" in r.stdout, "and the shortfall must be said"


# --------------------------------------------------------------------------
# The /server/info verification, which decides whether a swap is rolled back
# --------------------------------------------------------------------------

def test_a_component_in_failed_components_is_detected(tmp_path):
    """Moonraker loads optional components with `load_component(config, section,
    None)`, which swallows any exception into failed_components and KEEPS
    SERVING. So /server/info answering 200 is not the success condition — an
    earlier version treated it as one and reported a dead file browser as a
    successful retirement."""
    body = ('{"result": {"components": ["file_manager", "history"], '
            '"failed_components": ["creality_compat"]}}')
    r = run_sh(f"""
if nexusp_compat_load_failed '{body}'; then echo FAILED_DETECTED; else echo MISSED; fi
""", tmp_path)
    assert "FAILED_DETECTED" in r.stdout, r.stdout + r.stderr


def test_a_healthy_component_is_not_read_as_failed(tmp_path):
    """The component name appears in the healthy list too, so a naive substring
    match on the whole body would report every good install as broken."""
    body = ('{"result": {"components": ["file_manager", "creality_compat"], '
            '"failed_components": []}}')
    r = run_sh(f"""
if nexusp_compat_load_failed '{body}'; then echo FALSE_ALARM; else echo HEALTHY; fi
""", tmp_path)
    assert "HEALTHY" in r.stdout, r.stdout + r.stderr


def test_another_components_failure_is_not_attributed_to_this_one(tmp_path):
    body = ('{"result": {"components": ["creality_compat"], '
            '"failed_components": ["spoolman"]}}')
    r = run_sh(f"""
if nexusp_compat_load_failed '{body}'; then echo MISATTRIBUTED; else echo HEALTHY; fi
""", tmp_path)
    assert "HEALTHY" in r.stdout, r.stdout + r.stderr
