# Backport of upstream Klipper's extended-parameter parser to Creality's klippy.
#
# Deploys to: /usr/share/klipper/klippy/extras/extended_gcode_params.py
# Enabled by: a bare `[extended_gcode_params]` section in printer.cfg
# Needed on:  the K1C 2025 and the K1/K1C OG alike. The 2025 cannot pass '#',
#             ';' or '*'; the OG has a Creality fix for '#' and ';' that breaks
#             '|' instead. Neither is upstream's, and upstream's handles all four.
#
# WHAT THIS IS
# ------------
# Klipper fixed this upstream in PR #6749 ("gcode: Improve handling of extended
# g-code commands with '*;#' characters", Kevin O'Connor), merged 2024-12-01 as
# 2165c90. This module is that fix, ported verbatim, installed at runtime.
#
# The 2025's `gcode.pyc` best-fits upstream at **2024-11-26** (k25_sweep.json,
# 4 fitting revisions of 235) -- five days before the fix landed. So this is not
# Creality breaking something: it is a fork taken from upstream days before
# upstream fixed it, frozen there ever since. `gcode.pyc` is byte-identical
# between the installed V1.0.0.22 and the pending V1.0.0.26, so no vendor update
# will deliver it.
#
# THE BUG
# -------
# The old parser found the argument text with a regex that treats '#', '*' and
# ';' as comment characters, quotes or no quotes:
#
#     (?P<args>[^#*;]*?)\s*(?:[#*;].*)?$
#
# Because the group is non-greedy it stops at the FIRST such character, which
# inside `FILENAME="..."` is always after the opening quote and before the
# closing one. The quote is left unbalanced, `shlex` raises, and Klipper reports
# `Malformed command`. On Creality's builds that surfaces on the panel as the
# information-free `XS2000`.
#
# Upstream's fix hands the raw parameter text to `shlex` and lets shlex do the
# comment stripping, because shlex knows what a quote is:
#
#     s = shlex.shlex(rawparams, posix=True)
#     s.whitespace_split = True
#     s.commenters = '#;'
#
# Comments outside quotes still work; everything inside quotes is literal. '*'
# stops being a comment character here entirely -- upstream moved checksum
# handling into `get_raw_command_parameters()`, where it belongs, since '*NNN'
# is only a checksum on a line-numbered line.
#
# WHY A RUNTIME PATCH AND NOT AN EDIT TO gcode.pyc
# ------------------------------------------------
# `gcode.py` is on the encrypted/compiled tier and is core command dispatch. The
# extras directory, by contrast, is `ext4 (rw)` on mmcblk0p8 and already holds
# two files this repo ships (`gcode_shell_command.py`, `shaper_defs.py`).
#
# The patch point works because of how Klipper wraps extended commands:
#
#     func = lambda params: origfunc(self._get_extended_params(params))
#
# That resolves `_get_extended_params` through the INSTANCE on every command, so
# binding a replacement onto the gcode object catches every extended command,
# including ones registered before this module loaded. Ordering is irrelevant,
# so there are no config placement rules.
#
# ⚠ DO NOT "SIMPLIFY" THIS BY EDITING THE REGEX IN gcode.pyc.
# Swapping the comment class in place is even length-preserving, which makes it
# look free. It is not: `get_commandline()` returns the line INCLUDING its
# trailing ';' comment, so ';' must stay a comment character for every other
# extended command, or an ordinary line like
#     SET_HEATER_TEMPERATURE HEATER=extruder TARGET=200 ; heat it up
# starts failing. That is why the OG's own fix added a SECOND regex rather than
# widening the first, and why upstream moved to shlex instead of either.
#
# WHAT CHANGES, HONESTLY
# ----------------------
# This is a behaviour change, not a pure widening, and the difference is '*'.
# Under the old parser `FOO A=1*2` yielded `{A: '1'}`; under upstream's it
# yields `{A: '1*2'}`. That is upstream's deliberate choice -- a trailing '*NNN'
# is a checksum only on a line-numbered line, and it is handled there. Every
# other divergence from the old parser is strictly "a line that used to fail now
# succeeds"; `test_extended_gcode_params.py` characterises all of them against a
# model of the old parser rather than leaving them to be discovered.
#
# KNOWN LIMIT
# -----------
# Upstream's commit 7 ("Improve checksum detection in
# get_raw_command_parameters") only treats a trailing '*' as a checksum when the
# rest is digits. Both printers predate that, and their
# `get_raw_command_parameters` is otherwise identical to current upstream. So a
# LINE-NUMBERED command with '*' in a quoted argument -- `N42 SDCARD_PRINT_FILE
# FILENAME="a*b.gcode"` -- still truncates. Not reachable from Moonraker, which
# never sends line numbers, and not fixable from here without also rebinding
# GCodeCommand.get_raw_command_parameters. Recorded rather than fixed.
import logging
import shlex

# Upstream's comment characters for extended parameters. '*' is deliberately
# absent -- see the header.
COMMENTERS = '#;'


def parse_params(rawparams):
    """Upstream's parameter extraction, verbatim in behaviour.

    Returns the params dict, or raises ValueError exactly where upstream's
    `_get_extended_params` would raise `Malformed command`.

    Pure and side-effect free on purpose: this is the whole of the fix, and it
    is testable without a printer, a gcode object or a GCodeCommand.
    """
    s = shlex.shlex(rawparams, posix=True)
    s.whitespace_split = True
    s.commenters = COMMENTERS
    return {k.upper(): v for k, v in (arg.split('=', 1) for arg in s)}


class ExtendedGCodeParams:
    def __init__(self, config):
        self.printer = config.get_printer()
        gcode = self.printer.lookup_object('gcode')
        stock = getattr(gcode, '_get_extended_params', None)
        if stock is None:
            logging.warning(
                "extended_gcode_params: gcode object has no "
                "_get_extended_params; leaving the stock parser alone")
            return

        def _get_extended_params(gcmd):
            try:
                eparams = parse_params(gcmd.get_raw_command_parameters())
            except ValueError:
                # Unbalanced quotes, or a token with no '='. Hand it back to the
                # stock parser so the rejection keeps stock wording -- which on
                # Creality's builds is what the error_code table is keyed on.
                return stock(gcmd)
            gcmd._params.clear()
            gcmd._params.update(eparams)
            return gcmd

        gcode._get_extended_params = _get_extended_params
        logging.info("extended_gcode_params: upstream PR #6749 parser installed")


def load_config(config):
    return ExtendedGCodeParams(config)
