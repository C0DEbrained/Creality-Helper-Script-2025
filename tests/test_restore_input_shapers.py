#!/usr/bin/env python3
"""Offline checks for scripts/restore_input_shapers.sh — no printer, no daemons.

    python3 -m pytest -q tests/

WHY THIS FILE EXISTS
--------------------
Creality's klippy ships a shaper_defs.pyc that defines only `ei`, and its
input_shaper raises "Unsupported shaper type" for any other model. Restore Input
Shapers adds the stock shaper_defs.py, so SHAPER_CALIBRATE + SAVE_CONFIG then
writes e.g. `shaper_type_x = mzv` into printer.cfg. Remove used to delete
shaper_defs.py and leave that type behind, and Klipper refused to start.

These tests pin that Remove leaves every shaper type as `ei` (Creality's klippy
can load it), puts back the values recorded at install time where they are now
set, and never leaves one key in both [input_shaper] and the #*# SAVE_CONFIG
block. The fixtures follow a real K1C 2025 printer.cfg: the stock file carries
the shaper values in the #*# block with the section's copies commented out.

They also pin the firmware gate: an unlisted build still stops by default and
installs only on an explicit "y" to "Proceed anyway?".

The awk here runs under the host's awk (macOS: the one-true-awk), not the
printer's busybox awk; the scripts use only POSIX awk features both share.

⚠ Add cases as `test_*` functions. A file named test_*.py whose assertions live
in a hand-rolled runner gets collected and runs nothing while reporting green.
"""
import os
import shutil
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "restore_input_shapers.sh")
BASH = shutil.which("bash")

VERIFIED_FW = "K1C-2025_V1.0.0.26.20251024S"
UNLISTED_FW = "K1MAX-2025_V1.0.0.25.20251015S"

HEAD = """[printer]
kinematics: corexy

[adxl345]
cs_pin: nozzle_mcu:PA4
"""
RESONANCE = """
[resonance_tester]
accel_chip: adxl345
probe_points:
   110,110,10
"""
TAIL = """
[gcode_macro START_PRINT]
gcode:
  G28
"""
BANNER = """#*# <---------------------- SAVE_CONFIG ---------------------->
#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.
#*#
"""
BED_MESH = """#*# [bed_mesh default]
#*# version = 1
#*# x_count = 7
"""

# Stock K1C 2025: the section exists with its values commented out by a past
# SAVE_CONFIG, and the effective values live in the #*# block.
CFG_AUTOSAVE = (HEAD + """
[input_shaper]
#shaper_type_x = ei
#shaper_freq_x = 69.4
#shaper_type_y = ei
#shaper_freq_y = 69.4
""" + RESONANCE + TAIL + "\n" + BANNER + """#*# [input_shaper]
#*# shaper_type_y = ei
#*# shaper_freq_y = 71.4
#*# shaper_type_x = ei
#*# shaper_freq_x = 71.4
#*#
""" + BED_MESH)

# Values set directly in the section, no [input_shaper] in the #*# block.
CFG_SECTION = (HEAD + """
[input_shaper]
shaper_type_x: ei
shaper_freq_x: 60.2
shaper_type_y: ei
shaper_freq_y: 55.8
""" + RESONANCE + TAIL + "\n" + BANNER + BED_MESH)

# No [input_shaper] anywhere.
CFG_NONE = HEAD + RESONANCE + TAIL + "\n" + BANNER + BED_MESH


def setup(tmp_path, cfg_text):
    cfg = tmp_path / "printer.cfg"
    cfg.write_text(cfg_text)
    (tmp_path / "extras").mkdir()
    (tmp_path / "shaper_defs.py").write_text("# stock shaper_defs\n")
    return cfg


def run_sh(body, tmp_path, fw=VERIFIED_FW):
    """Source the script under `set -e` (as helper.sh does) with paths pointed
    into tmp_path and the printer-only commands stubbed, then run `body`."""
    preamble = f"""
set -e
white=; yellow=; cyan=; green=; darkred=; red=
top_line() {{ :; }}; title() {{ :; }}; inner_line() {{ :; }}; hr() {{ :; }}; bottom_line() {{ :; }}
error_msg() {{ echo "ERR: $1"; }}
ok_msg() {{ echo "OK: $1"; }}
install_msg() {{ read -r $2; }}
remove_msg() {{ read -r $2; }}
check_fw_version() {{ echo "{fw}"; }}
restart_klipper() {{ echo "RESTART"; }}
PRINTER_CFG={tmp_path}/printer.cfg
HS_BACKUP_FOLDER={tmp_path}/backup
KLIPPER_EXTRAS_FOLDER={tmp_path}/extras
SHAPER_DEFS_FILE={tmp_path}/extras/shaper_defs.py
RESTORE_SHAPERS_URL={tmp_path}/shaper_defs.py
. {SCRIPT}
"""
    r = subprocess.run([BASH, "-c", preamble + body],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SURVIVED" in r.stdout, r.stdout + r.stderr
    return r


def install(tmp_path, answers="y\n", fw=VERIFIED_FW):
    return run_sh(f"printf '{answers}' | install_restore_input_shapers\necho SURVIVED",
                  tmp_path, fw)


def remove(tmp_path):
    return run_sh("echo y | remove_restore_input_shapers\necho SURVIVED", tmp_path)


def shaper_lines(text):
    """(where, key, value) for every uncommented shaper line in [input_shaper],
    using the same reading rules Klipper does for the two places."""
    out, sect = [], {"section": "", "autosave": ""}
    for raw in text.splitlines():
        where, line = "section", raw
        if raw.startswith("#*#"):
            where, line = "autosave", raw[3:].strip()
        elif raw.startswith(("#", ";")) or raw[:1].isspace():
            continue
        if line.startswith("["):
            sect[where] = line
            continue
        if sect[where] == "[input_shaper]" and line.startswith("shaper_"):
            key, _, val = line.replace(":", "=", 1).partition("=")
            out.append((where, key.strip(), val.strip()))
    return out


def effective(text):
    vals = {}
    for where, key, val in sorted(shaper_lines(text), key=lambda t: t[0] == "autosave"):
        vals[key] = val
    return vals


def calibrate(cfg, tx="mzv", fx="52.4", ty="zv", fy="40.0"):
    """What SHAPER_CALIBRATE + SAVE_CONFIG does: comment out the section's
    copies and write the result into the #*# block."""
    lines = cfg.read_text().splitlines()
    out, in_sect = [], False
    for line in lines:
        if line.startswith("["):
            in_sect = line == "[input_shaper]"
        elif in_sect and line.startswith("shaper_"):
            line = "#" + line
        out.append(line)
    text = "\n".join(out) + "\n"
    # Key order as a real K1C 2025 SAVE_CONFIG wrote it.
    new = (f"#*# [input_shaper]\n#*# shaper_type_y = {ty}\n#*# shaper_freq_y = {fy}\n"
           f"#*# shaper_type_x = {tx}\n#*# shaper_freq_x = {fx}\n#*#\n")
    if "#*# [input_shaper]" in text:
        head, _, rest = text.partition("#*# [input_shaper]\n")
        rest = rest[rest.index("#*#\n") + 4:]
        text = head + new + rest
    else:
        text = text.replace(BANNER, BANNER + new)
    cfg.write_text(text)


def assert_klipper_loadable(text):
    types = {k: v for k, v in effective(text).items() if k.startswith("shaper_type")}
    assert all(v == "ei" for v in types.values()), types
    seen = {}
    for where, key, _ in shaper_lines(text):
        seen.setdefault(key, set()).add(where)
    assert all(len(w) == 1 for w in seen.values()), seen


# --- Remove restores the install-time values -------------------------------

def test_stock_autosave_cfg_round_trips_through_calibrate_and_remove(tmp_path):
    cfg = setup(tmp_path, CFG_AUTOSAVE)
    install(tmp_path)
    assert "axis_x_use_y: false" in cfg.read_text()
    calibrate(cfg)
    assert effective(cfg.read_text())["shaper_type_x"] == "mzv"
    r = remove(tmp_path)
    assert cfg.read_text() == CFG_AUTOSAVE, cfg.read_text()
    assert "SHAPER_CALIBRATE" not in r.stdout
    assert not (tmp_path / "backup/restore-input-shapers/input_shaper.bak").exists()


def test_section_cfg_gets_original_values_in_the_autosave_block(tmp_path):
    """After SAVE_CONFIG the values live in the #*# block and the section copies
    are commented out; Remove writes the originals there, not in both places."""
    cfg = setup(tmp_path, CFG_SECTION)
    install(tmp_path)
    calibrate(cfg)
    remove(tmp_path)
    text = cfg.read_text()
    assert effective(text) == {"shaper_type_x": "ei", "shaper_freq_x": "60.2",
                               "shaper_type_y": "ei", "shaper_freq_y": "55.8"}, text
    assert_klipper_loadable(text)


def test_key_set_in_both_places_ends_up_only_in_the_autosave_block(tmp_path):
    cfg = setup(tmp_path, CFG_SECTION)
    install(tmp_path)
    text = cfg.read_text().replace(BANNER, BANNER + "#*# [input_shaper]\n"
                                   "#*# shaper_type_x = mzv\n#*# shaper_freq_x = 52.4\n#*#\n")
    cfg.write_text(text)
    remove(tmp_path)
    text = cfg.read_text()
    assert ("autosave", "shaper_type_x", "ei") in shaper_lines(text), text
    assert ("section", "shaper_type_x", "ei") not in shaper_lines(text), text
    assert effective(text)["shaper_freq_x"] == "60.2"
    assert_klipper_loadable(text)


def test_cfg_without_input_shaper_is_returned_to_none(tmp_path):
    cfg = setup(tmp_path, CFG_NONE)
    install(tmp_path)
    calibrate(cfg)
    remove(tmp_path)
    assert cfg.read_text() == CFG_NONE, cfg.read_text()


def test_section_cfg_edited_in_place_when_no_save_config_ran(tmp_path):
    cfg = setup(tmp_path, CFG_SECTION)
    install(tmp_path)
    cfg.write_text(cfg.read_text().replace("shaper_type_x: ei", "shaper_type_x: mzv"))
    remove(tmp_path)
    assert cfg.read_text() == CFG_SECTION, cfg.read_text()


def test_reinstall_keeps_the_first_backup(tmp_path):
    """A reinstall after a firmware update must not overwrite the pre-restore
    values with the calibrated (non-ei) ones."""
    cfg = setup(tmp_path, CFG_AUTOSAVE)
    install(tmp_path)
    calibrate(cfg)
    r = install(tmp_path)
    assert "Keeping the existing input-shaper settings backup" in r.stdout
    remove(tmp_path)
    assert cfg.read_text() == CFG_AUTOSAVE, cfg.read_text()


# --- Remove without a backup forces ei ------------------------------------

def test_no_backup_forces_ei_and_asks_for_recalibration(tmp_path):
    """An install from before this change has no backup."""
    cfg = setup(tmp_path, CFG_AUTOSAVE)
    calibrate(cfg)
    r = remove(tmp_path)
    text = cfg.read_text()
    assert_klipper_loadable(text)
    assert effective(text)["shaper_freq_x"] == "52.4"
    assert "Run SHAPER_CALIBRATE" in r.stdout, r.stdout


def test_no_backup_and_already_ei_says_nothing_about_recalibrating(tmp_path):
    cfg = setup(tmp_path, CFG_AUTOSAVE)
    r = remove(tmp_path)
    assert cfg.read_text() == CFG_AUTOSAVE
    assert "SHAPER_CALIBRATE" not in r.stdout


# --- Firmware gate ---------------------------------------------------------

def test_unlisted_firmware_stops_by_default(tmp_path):
    cfg = setup(tmp_path, CFG_AUTOSAVE)
    r = install(tmp_path, answers="y\n\n", fw=UNLISTED_FW)
    assert "not verified for this firmware" in r.stdout
    assert "ERR: Installation canceled!" in r.stdout
    assert not (tmp_path / "extras/shaper_defs.py").exists()
    assert cfg.read_text() == CFG_AUTOSAVE


def test_unlisted_firmware_stops_on_closed_input(tmp_path):
    setup(tmp_path, CFG_AUTOSAVE)
    r = install(tmp_path, answers="y\n", fw=UNLISTED_FW)
    assert "ERR: Installation canceled!" in r.stdout
    assert not (tmp_path / "extras/shaper_defs.py").exists()


def test_unlisted_firmware_installs_on_explicit_yes(tmp_path):
    setup(tmp_path, CFG_AUTOSAVE)
    r = install(tmp_path, answers="y\ny\n", fw=UNLISTED_FW)
    assert UNLISTED_FW in r.stdout
    assert "OK: Restore Input Shapers has been installed successfully!" in r.stdout
    assert (tmp_path / "extras/shaper_defs.py").exists()
    assert "After any Creality firmware update" in r.stdout


def test_verified_firmware_is_not_asked(tmp_path):
    setup(tmp_path, CFG_AUTOSAVE)
    r = install(tmp_path)
    assert "Proceed anyway" not in r.stdout
    assert (tmp_path / "extras/shaper_defs.py").exists()
