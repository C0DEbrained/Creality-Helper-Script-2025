# creality_compat.py — the two JSON-RPC methods Creality's touchscreen needs and
# upstream Moonraker does not have. A Moonraker component; runs on the K1C 2025
# only, at components/creality_compat.py, enabled by `[creality_compat]` in
# moonraker.conf.
#
# WHY THIS EXISTS
# ---------------
# The 2025 ships two Moonrakers against one Klipper: Creality's `nexusp` on
# :7125 for the touchscreen, and the helper script's real one on :7126 for
# everything else. That split is an active trap — a query to the "wrong" port
# ANSWERS, plausibly and incorrectly — so the "Retire Nexusp Backend" option
# switches nexusp off and moves real Moonraker onto :7125. The screen
# (`vectorp`) reconnects on its own and works, with two exceptions, both of
# which are calls to methods only Creality's fork had:
#
#     server.files.get_directory_ex   the file browser's paging/sort/search
#     server.history.count            called once the moment the screen connects
#
# Without them the browser renders its first page (from stock `server.files.list`)
# and then cannot scroll, filter or search. This file closes that gap. It is a
# COMPATIBILITY SHIM, not a feature: every behaviour below was measured against
# a real nexusp before it was switched off, on one K1C 2025 running
# V1.0.0.22.20250711S. The measurements cannot be re-derived once a user has
# retired nexusp, so test_creality_compat.py beside this file is their only
# executable record.
#
# THE RULES, ALL MEASURED, NONE GUESSED
# -------------------------------------
# `path`, `start`, `limit` and `order` are ALL required. nexusp rejects a call
# missing `path` with "No data for argument: path" and one missing any of the
# other three with a bare "Invalid parameter" that names nothing — which is why
# the parameter names had to come out of the binary's strings in the first place.
# Being more lenient than the reference was considered and rejected: the only
# client is closed-source, so the safe shim is the one that cannot behave
# differently from what that client has always been handed.
#
# What is listed, in a directory:
#   - subdirectories, ALWAYS, and always sorted ahead of every file
#   - files whose name ends in `.gcode` — measured: an empty `.gcode` IS listed
#     (so this is an extension test, not a has-metadata test), while `.gco`,
#     `.txt` and anything else are NOT, even though Moonraker's own listing
#     accepts `.g` and `.gco` as gcode
#   - nothing whose name starts with `.` — which is why `gcodes/.thumbs` never
#     appears on the screen even though Fluidd shows it
#
# `order` is a comma-separated triple as the screen sends it —
# `name,asc,folder`, `datetime,desc,folder`, `size,asc,folder` — where the third
# token is always `folder` and nothing is keyed off it. Known fields are
# name/filename, datetime (mtime) and size. ANY unrecognised value — including
# "files", "type" and outright nonsense — falls back to name ascending rather
# than erroring, which is nexusp's behaviour and not an accident of this port.
#
# Name ordering is a NATURAL sort here: digit runs compare numerically and text
# compares case-insensitively. nexusp did a plain codepoint sort, which put every
# capitalised name ahead of every lowercase one and ordered `ss_ruin_2`,
# `ss_ruin_10`, `ss_ruin_3` in that order. This is the one deliberate improvement
# on the reference in this file.
#
# `keyword` is a case-insensitive substring match on the name, and it narrows
# `count` as well as the page.
#
# `since` and `before` are accepted and DELIBERATELY IGNORED, because that is
# what nexusp does. Measured, not assumed: a window excluding almost every file
# left `count` unchanged at 92. Implementing them properly would hide files the
# screen has always been shown, which is a worse failure than the one being
# fixed — a file that vanishes from the browser looks like a file that was
# deleted.
#
# `count` is the total AFTER keyword filtering and BEFORE paging, so the screen
# can size its scrollbar. `start` past the end returns an empty page with the
# count intact, and `limit: 0` returns an empty page — also measured.
#
# THUMBNAILS ARE READ OFF THE DISK, NOT OUT OF THE METADATA
# ---------------------------------------------------------
# The first version of this shim passed Moonraker's `thumbnails` through
# untouched, and 66 of 91 files came back thumbnail-less on the screen. The cause
# is not the shim and not the screen: Moonraker lists only the thumbnails the
# SLICER embedded in the gcode, while `nexusp` also rendered its own into
# `.thumbs` and listed those too. Measured — every file has 48/96/195/300 on
# disk, Moonraker lists 48 and 195 for NONE of them, and the 66 files whose
# slicer emitted 100/320 instead of 96/300 have no listed size the screen will
# take. Those 66 are exactly the ones that went blank.
#
# So each file's `thumbnails` is the union of Moonraker's parsed entries and
# every `<stem>-<W>x<H>.png` actually present in `.thumbs`. Reporting what exists
# rather than what was parsed is what makes this safe without knowing the
# screen's size-selection rule.
#
# It also GENERATES the two sizes nexusp used to render and Moonraker never
# does — 48x48 and 195x195 — for any file that lacks them, downscaling from the
# largest thumbnail present, once per file, and never by UPSCALING: a 32x32 blown
# up to a 195x195 tile is a blurred mess that reads as a broken thumbnail rather
# than an absent one. Set `generate_thumbnails: False` in `[creality_compat]` to
# turn it off and go back to listing only what exists.
#
# PILLOW IS NOT IN THE MOONRAKER VENV THIS REPO SHIPS
# ---------------------------------------------------
# Upstream Moonraker lists Pillow in requirements.txt, and it is NOT in
# `files/moonraker/moonraker.tar.gz` — the venv the helper actually installs is
# Python 3.8 with apprise, jinja2, ldap3, dbus_fast, inotify_simple and no PIL,
# and `install_moonraker_nginx` only ever runs `git pull` on the source repo.
# So on a clean helper box:
#
#   - generation here is off, and says so once in the log rather than throwing
#     a traceback per file;
#   - Moonraker's OWN metadata.py imports PIL at module scope, so it parses no
#     embedded thumbnails either — a freshly uploaded gcode has nothing on disk
#     AND nothing parsed, and there is no source image to downscale from. The
#     screen shows no thumbnail for it at all.
#
# Installing Pillow into moonraker-env fixes both — the second one for every
# helper user, retired nexusp or not. "Retire Nexusp Backend" offers to do it.
# A directory listing must never fail because an optional renderer is absent,
# so everything above degrades to "list what is on disk" and nothing else.
#
# WHAT IS NOT SHIMMED
# -------------------
# The gap analysis found four Creality-only methods. The other two stay missing
# on purpose: `server.history.debug.job` returns `{"last_row_id": N}` and is
# internal, and `server.debug.status` dumps nexusp's socket buffers and emits
# MALFORMED JSON (a trailing comma) that strict parsers reject. Neither is
# screen-facing; each was logged exactly once, at connect, with nothing visibly
# broken afterwards.
#
# `printer.info` and `printer.objects.list` are deliberately NOT registered here
# either, even though they answer `-32601 Method not found` for about four
# seconds after a cold boot while the screen polls. They are genuine Moonraker
# methods registered dynamically when klippy connects, and `register_endpoint`
# returns early for an already-registered path when the incoming registration is
# remote — klippy's are remote. A static registration would therefore not
# collide with klippy's later one, it would silently WIN it for the life of the
# process, and a stub answering `printer.info` forever is far worse than a
# four-second gap at boot.
#
# COUPLING, HONESTLY — THREE, NOT TWO
# -----------------------------------
# 1. `file_manager._list_directory` (private)
# 2. `file_manager._convert_request_path` (private)
# 3. raw SQL against `history.history_table`, Moonraker's own SQL table wrapper
#
# 1 and 2 are private because reimplementing metadata lookup and root resolution
# would be a second source of truth for the thing most likely to drift. Both are
# checked at COMPONENT LOAD, not at request time, and a missing one raises with
# the attribute's name: `install_moonraker_nginx` runs `git checkout master; git
# pull`, so every user's Moonraker is a moving target against a frozen venv, and
# the offline tests below use fakes and can never catch a rename. Failing at
# startup with the missing name is the only warning anyone gets.
#
# The table name for 3 is imported from Moonraker's own history component rather
# than repeated here, so a rename there is an ImportError at load for the same
# reason.

from __future__ import annotations

import asyncio
import logging
import os
import re

from ..common import RequestType, TransportType
from .history import HIST_TABLE

# Annotation imports
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

if TYPE_CHECKING:
    from ..confighelper import ConfigHelper
    from ..common import WebRequest

# Measured against nexusp: `.gcode` and nothing else. Moonraker's own
# VALID_GCODE_EXTS is wider (`.g`, `.gco`); matching it here would surface files
# on the screen that have never been there.
GCODE_EXT = ".gcode"

# The private file_manager methods this component calls. Checked by name at load
# so a Moonraker rename breaks at startup, loudly, instead of the first time
# somebody opens the file browser.
REQUIRED_FM_ATTRS = ("_list_directory", "_convert_request_path")

# order field -> (item key, default when the key is absent).
#
# MEASURED, at last, from the screen itself: it sends a COMMA-SEPARATED triple —
# `name,asc,folder`, `datetime,desc,folder`, `size,asc,folder`. Field, direction,
# and a third token that is always `folder` (and matches the dirs-always-first
# behaviour this shim already implements unconditionally; no other value has ever
# been observed, so nothing is keyed off it).
#
# That separator was the entire bug behind "sort buttons do nothing": the first
# version split on whitespace only, so `name,asc,folder` arrived as ONE token,
# matched no field, and fell through to the name-ascending default. Silently —
# and that silence is faithful, since falling back rather than erroring on an
# unknown sort is measured nexusp behaviour. The fallback was right; the split
# was wrong.
#
# `name`/`filename`, `datetime` and `size` are nexusp's own vocabulary. The
# aliases below were added while the screen's string was still unknown; they are
# kept because they cost nothing and document what was ruled out.
SORT_FIELDS = {
    "name": ("__name__", ""),
    "filename": ("__name__", ""),
    "file": ("__name__", ""),
    "datetime": ("modified", 0.0),
    "date": ("modified", 0.0),
    "time": ("modified", 0.0),
    "modified": ("modified", 0.0),
    "mtime": ("modified", 0.0),
    "size": ("size", 0),
    "filesize": ("size", 0),
    "bytes": ("size", 0),
}

# Sizes nexusp rendered itself, on top of whatever the slicer embedded, and which
# Moonraker therefore never produces. Measured: all 92 pre-swap files have both.
GENERATED_THUMB_SIZES = ((48, 48), (195, 195))

# The instance the job_history rows the screen pages through are scoped to.
# Moonraker's own `server.history.list` filters on a bare "default" literal in
# this version, and every row it writes carries that value — so the count and
# the list it sizes cannot disagree. The value is looked up off the history
# component first (see _history_instance) so that stays true if Moonraker ever
# grows a real instance id; this is the fallback, not the answer.
HIST_INSTANCE_FALLBACK = "default"

# Where Creality's thumbnails live, and how they are named:
# <dir>/.thumbs/<gcode stem>-<width>x<height>.png. Parsed from the END because a
# gcode stem is full of hyphens and digits ("Cube-4m59s-0.2w-0.1h").
THUMB_DIR = ".thumbs"
THUMB_RE = re.compile(r"^(?P<stem>.+)-(?P<w>\d+)x(?P<h>\d+)\.png$")

# Bound on the load-time walk that finds `.thumbs` directories to reserve. A
# gcodes root deep or wide enough to exceed this is not a printer this option
# was measured on, and the walk runs before Moonraker serves anything.
MAX_RESERVE_WALK_DIRS = 2000

# The screen sends commas (`name,asc,folder`). The rest are accepted because the
# cost of another separator turning up is a sort that silently does nothing.
ORDER_SPLIT = re.compile(r"[\s,;|]+")

# Natural sort: digit runs compare as numbers, text compares case-insensitively.
# A DELIBERATE DIVERGENCE from nexusp, which did a plain codepoint sort — so it
# put every capitalised name ahead of every lowercase one, and ordered
# `ss_ruin_2`, `ss_ruin_10`, `ss_ruin_3` in that order. Everything else in this
# file matches the reference; this is the one place where being better than it
# was the point.
NATURAL_SPLIT = re.compile(r"(\d+)")


def natural_key(name: str) -> Any:
    """Sort key: "img2" before "img10", and "apple" beside "Apple".

    Each element is a 3-tuple of the same shape so nothing ever compares an int
    against a str — digit runs become `(0, <value>, "")` and text becomes
    `(1, 0, <casefolded>)`, which also settles the "do numbers sort before
    letters" question consistently rather than by accident.

    The raw name is the final tiebreak, so two names differing only in case get a
    stable order instead of an arbitrary one.
    """
    parts = NATURAL_SPLIT.split(name)
    key = [(0, int(part), "") if index % 2 else (1, 0, part.casefold())
           for index, part in enumerate(parts)]
    return key, name


class CrealityCompat:
    def __init__(self, config: ConfigHelper) -> None:
        self.server = config.get_server()
        self.log_requests = config.getboolean("log_requests", False)
        self.generate_thumbs = config.getboolean("generate_thumbnails", True)

        # Fail at LOAD, with the missing name, rather than the first time the
        # screen opens the file browser. See COUPLING, HONESTLY above.
        fm = self.server.lookup_component("file_manager")
        for attr in REQUIRED_FM_ATTRS:
            if not hasattr(fm, attr):
                raise self.server.error(
                    f"creality_compat: file_manager has no '{attr}'. This "
                    "Moonraker is newer than the component; the touchscreen's "
                    "file browser needs it. Report it against the helper "
                    "script rather than editing this file blind.", 500
                )

        # Pillow, once, here — not per request. Missing PIL must cost one log
        # line at startup, not a traceback per file forever.
        self._image = self._load_pillow()
        # (destination png path) -> already logged. Keyed on the destination
        # because it encodes directory, stem and size. In memory only, so a
        # repaired filesystem heals at the next Moonraker restart.
        self._failed_renders: Set[str] = set()
        self._reserved_thumb_dirs: Set[str] = set()
        if self.generate_thumbs:
            self._reserve_existing_thumb_dirs(fm)

        # WEBSOCKET only, deliberately. `register_endpoint` defaults to every
        # transport, which would answer `GET /server/files/directory_ex` over
        # HTTP — measured: nexusp returned 404 there, and that 404 is exactly
        # what made the method look absent while it was being reverse
        # engineered. `server.history.count` follows by symmetry: the screen is
        # the only caller and only ever calls it over the websocket.
        self.server.register_endpoint(
            "/server/files/get_directory_ex", RequestType.GET,
            self._handle_directory_ex, transports=TransportType.WEBSOCKET
        )
        self.server.register_endpoint(
            "/server/history/count", RequestType.GET,
            self._handle_history_count, transports=TransportType.WEBSOCKET
        )

    # -- optional dependencies and side channels ----------------------------

    def _load_pillow(self) -> Optional[Any]:
        """PIL.Image, or None with one explanatory line in the log.

        Not a hard dependency: without it this component still serves the
        disk-union listing, which is most of the fix. See the PILLOW header
        section for why the shipped venv does not have it.
        """
        if not self.generate_thumbs:
            return None
        try:
            from PIL import Image
        except Exception as why:
            self.generate_thumbs = False
            logging.info(
                "creality_compat: Pillow is not available in Moonraker's "
                "virtualenv (%s), so the 48x48 and 195x195 thumbnails the "
                "touchscreen expects will not be generated. Thumbnails already "
                "on disk are still listed. Note that Moonraker's own metadata "
                "parser needs Pillow too, so without it a newly uploaded file "
                "has no thumbnail at all. Install it with: "
                "/usr/data/moonraker/moonraker-env/bin/python -m pip install Pillow",
                why
            )
            return None
        return Image

    def _reserve_thumb_dir(self, fm: Any, thumb_dir: str) -> None:
        """Keep `.thumbs` out of file_manager's inotify watch.

        Writing a PNG into a watched directory fires `notify_filelist_changed`,
        and file_manager has no dot-directory filter — so generating thumbnails
        inside a listing would broadcast a phantom `create_file` for every PNG
        to Fluidd and to the screen. A reserved path is skipped both by the
        initial scan and by the directory-create handler, and read access is
        left on so the thumbnails are still served over HTTP.

        This must happen BEFORE the directory is scanned or created, which is
        why the existing ones are reserved at load (file_manager's initial scan
        runs in its `component_init`, after every component is constructed) and
        a new one is reserved before it is made. Both `add_reserved_path` and
        `get_directory` are public API; a failure here is cosmetic, so it is
        logged and swallowed rather than raised.
        """
        if thumb_dir in self._reserved_thumb_dirs:
            return
        self._reserved_thumb_dirs.add(thumb_dir)
        try:
            fm.add_reserved_path(f"creality_compat:{thumb_dir}", thumb_dir, True)
        except Exception:
            logging.exception(
                "creality_compat: could not reserve %s; thumbnail writes there "
                "will emit spurious filelist notifications", thumb_dir
            )

    def _ensure_thumb_dir(self, dir_path: str) -> bool:
        """Reserve `<dir>/.thumbs`, then make sure it exists. Order matters.

        Reserving first is what stops the directory-create event from starting a
        watch on it, which is what stops every PNG written afterwards from
        broadcasting a phantom `create_file`. Called only when there is actually
        something to render, so a directory of thumbnail-less files never grows
        an empty `.thumbs`.
        """
        thumb_dir = os.path.join(dir_path, THUMB_DIR)
        self._reserve_thumb_dir(
            self.server.lookup_component("file_manager"), thumb_dir)
        if os.path.isdir(thumb_dir):
            return True
        try:
            os.makedirs(thumb_dir)
        except OSError as why:
            logging.warning(
                "creality_compat: cannot create %s (%s); listing only the "
                "thumbnails already on disk", thumb_dir, why
            )
            return False
        return True

    def _reserve_existing_thumb_dirs(self, fm: Any) -> None:
        try:
            gcode_root = fm.get_directory("gcodes")
        except Exception:
            gcode_root = ""
        if not gcode_root or not os.path.isdir(gcode_root):
            return
        seen = 0
        for dir_path, subdirs, _ in os.walk(gcode_root):
            seen += 1
            if seen > MAX_RESERVE_WALK_DIRS:
                logging.info(
                    "creality_compat: stopped reserving .thumbs directories "
                    "after %d directories; deeper ones will emit spurious "
                    "filelist notifications when a thumbnail is written",
                    MAX_RESERVE_WALK_DIRS
                )
                return
            if THUMB_DIR in subdirs:
                subdirs.remove(THUMB_DIR)
                self._reserve_thumb_dir(fm, os.path.join(dir_path, THUMB_DIR))

    def _history_instance(self, history: Any) -> str:
        """The instance id `server.history.list` scopes to.

        Derived rather than hardcoded so the docstring on `_handle_history_count`
        stays true: a count that disagrees with the list it sizes is exactly the
        plausible-wrong-answer failure retiring nexusp exists to kill. Today's
        Moonraker has no such attribute and uses a bare "default" literal in
        both the insert and the list query, so the fallback is the answer — but
        it is the fallback.
        """
        instance = getattr(history, "instance_id", None)
        if isinstance(instance, str) and instance:
            return instance
        return HIST_INSTANCE_FALLBACK

    # -- server.files.get_directory_ex --------------------------------------

    def _require(self, web_request: WebRequest, *names: str) -> None:
        """Reject a missing argument the way nexusp does.

        `path` is left to Moonraker's own getter, whose "No data for argument:
        path" happens to match nexusp's wording exactly. The other three get the
        bare "Invalid parameter" — unhelpful, but it is what the screen has
        always received and what any future debugger will find in the capture.
        """
        args = web_request.get_args()
        for name in names:
            if name not in args:
                raise self.server.error("Invalid parameter", 400)

    def _visible(self, name: str, is_dir: bool) -> bool:
        if name.startswith("."):
            return False
        return is_dir or name.lower().endswith(GCODE_EXT)

    def _disk_thumbnails(self, dir_path: str) -> Dict[str, List[Dict[str, Any]]]:
        """Every PNG actually sitting in `<dir>/.thumbs`, keyed by gcode stem.

        Moonraker lists only the thumbnails the SLICER embedded in the gcode, and
        `nexusp` rendered its own on top of those. Measured on the reference unit:
        all 92 files have 48/96/195/300 on disk, and Moonraker lists 48 and 195
        for none of them — while the 66 files whose slicer emitted 100/320 have
        no listed size the screen will accept at all. Those 66 are exactly the
        files that came back thumbnail-less after the swap.

        So the shim reports what EXISTS rather than what was parsed. The listing
        becomes a superset of both daemons' — which is what makes it safe without
        knowing the screen's size-selection rule, since whatever it looks for is
        now there.
        """
        found: Dict[str, List[Dict[str, Any]]] = {}
        thumb_dir = os.path.join(dir_path, THUMB_DIR)
        try:
            names = os.listdir(thumb_dir)
        except OSError:
            # No .thumbs here at all. Normal for every root except gcodes.
            return found
        for name in names:
            match = THUMB_RE.match(name)
            if match is None:
                continue
            try:
                size = os.path.getsize(os.path.join(thumb_dir, name))
            except OSError:
                continue
            found.setdefault(match.group("stem"), []).append({
                "width": int(match.group("w")),
                "height": int(match.group("h")),
                "size": size,
                "relative_path": f"{THUMB_DIR}/{name}",
            })
        return found

    def _generate_missing(
        self, dir_path: str, stem: str, have: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Render the sizes nexusp used to render, from the biggest one present.

        Only for files that lack them, only the two sizes in
        GENERATED_THUMB_SIZES, and only ever by DOWNSCALING — upscaling a 32x32
        into a 195x195 tile produces a blurred mess that looks like a broken
        thumbnail rather than an absent one, which is worse than blank.

        A file with nothing on disk and nothing parsed gets nothing: there is no
        source image, and inventing one is not on the table. On a box without
        Pillow that is every freshly uploaded file, because Moonraker's metadata
        parser needs Pillow too — see the header.

        Runs in a worker thread (see `_decorate_page`), never on the event loop:
        LANCZOS resizes plus flash writes for a whole page would otherwise block
        the loop that also serves klippy and Fluidd, during a print.
        """
        if not self.generate_thumbs or self._image is None:
            return []
        source = None
        for thumb in have:
            if source is None or thumb["width"] * thumb["height"] > \
                    source["width"] * source["height"]:
                source = thumb
        if source is None:
            return []
        wanted = [
            (width, height) for width, height in GENERATED_THUMB_SIZES
            if not any(t["width"] == width and t["height"] == height for t in have)
            and source["width"] >= width and source["height"] >= height
        ]
        if not wanted or not self._ensure_thumb_dir(dir_path):
            return []
        made: List[Dict[str, Any]] = []
        for width, height in wanted:
            name = f"{stem}-{width}x{height}.png"
            dest = os.path.join(dir_path, THUMB_DIR, name)
            # One attempt per destination per process. Retrying a render that
            # has already failed means a traceback on every listing forever;
            # a Moonraker restart clears the set, so a repaired filesystem heals
            # on its own.
            if dest in self._failed_renders:
                continue
            try:
                with self._image.open(
                    os.path.join(dir_path, source["relative_path"])
                ) as im:
                    im.convert("RGBA").resize(
                        (width, height), self._image.LANCZOS).save(dest)
                made.append({
                    "width": width, "height": height,
                    "size": os.path.getsize(dest),
                    "relative_path": f"{THUMB_DIR}/{name}",
                })
            except Exception as why:
                # A directory listing must not fail because one PNG would not
                # scale. One warning per destination, then silence.
                self._failed_renders.add(dest)
                logging.warning(
                    "creality_compat: could not render %s (%s); not trying "
                    "again until Moonraker restarts", dest, why
                )
        return made

    def _merge_thumbnails(
        self, entry: Dict[str, Any], on_disk: Dict[str, List[Dict[str, Any]]],
        dir_path: str
    ) -> None:
        """Add the on-disk thumbnails this file has that the metadata omits.

        Moonraker's own entries are kept as-is and win on duplicate dimensions —
        it read them out of the gcode, which is the better provenance. Sorted by
        area so the result is deterministic; nexusp's own order was its database's
        insertion order and the screen evidently searches the list rather than
        taking the first, since it accepted several different orders.
        """
        stem = os.path.splitext(entry.get("filename", ""))[0]
        thumbs = list(entry.get("thumbnails") or [])
        have = {(t.get("width"), t.get("height")) for t in thumbs}
        thumbs.extend(t for t in on_disk.get(stem, [])
                      if (t["width"], t["height"]) not in have)
        thumbs.extend(self._generate_missing(dir_path, stem, thumbs))
        if not thumbs:
            return
        entry["thumbnails"] = sorted(thumbs, key=lambda t: t["width"] * t["height"])

    def _decorate_page(self, dir_path: str, page: List[Dict[str, Any]]) -> None:
        """Thumbnail work for the page only, off the event loop.

        Deliberately AFTER the slice: sorting reads `filename`, `modified` and
        `size` and never `thumbnails`, so nothing above needs this. Doing it
        before the slice meant the first browse of a 91-file directory with no
        `.thumbs` was up to 182 LANCZOS resizes plus flash writes inside one
        request — during a print, on the loop serving klippy and Fluidd.
        """
        files = [item for item in page if item.get("type") == "f"]
        if not files:
            return
        on_disk = self._disk_thumbnails(dir_path)
        for entry in files:
            self._merge_thumbnails(entry, on_disk, dir_path)

    def _sorted(self, items: List[Dict[str, Any]], order: str) -> List[Dict[str, Any]]:
        # Case-folded, and split on commas/semicolons as well as whitespace: the
        # screen sends `name,asc,folder`, and the cost of another separator
        # turning up is a sort that silently does nothing. "desc" anywhere after
        # the field means descending.
        tokens = [t for t in ORDER_SPLIT.split(order.strip().lower()) if t]
        field = tokens[0] if tokens else "name"
        reverse = "desc" in tokens[1:]
        key, default = SORT_FIELDS.get(field, SORT_FIELDS["name"])
        if key == "__name__":
            def sort_key(item: Dict[str, Any]) -> Any:
                return natural_key(
                    item.get("filename") or item.get("dirname") or "")
        else:
            def sort_key(item: Dict[str, Any]) -> Any:
                value = item.get(key)
                return default if value is None else value
        return sorted(items, key=sort_key, reverse=reverse)

    async def _handle_directory_ex(self, web_request: WebRequest) -> Dict[str, Any]:
        self._require(web_request, "start", "limit", "order")
        path = web_request.get_str("path")
        start = web_request.get_int("start")
        limit = web_request.get_int("limit")
        order = web_request.get_str("order")
        keyword = web_request.get_str("keyword", "").lower()
        # A negative offset would wrap the slice and hand back the END of the
        # listing, which reads as data corruption rather than a bad request.
        start = max(start, 0)

        fm = self.server.lookup_component("file_manager")
        root, dir_path = fm._convert_request_path(path)
        listing = fm._list_directory(dir_path, root, True)

        if self.log_requests:
            # The screen is the only caller and it is closed source; this line is
            # the only way to learn what it actually sends. Cheap, and off by
            # default once the questions it answers are answered.
            logging.info("creality_compat: get_directory_ex %s", web_request.get_args())

        dirs: List[Dict[str, Any]] = []
        files: List[Dict[str, Any]] = []
        for entry in listing["dirs"]:
            name = entry.get("dirname", "")
            if self._visible(name, True) and keyword in name.lower():
                dirs.append(dict(entry, type="d"))
        for entry in listing["files"]:
            name = entry.get("filename", "")
            if self._visible(name, False) and keyword in name.lower():
                files.append(dict(entry, type="f"))

        # Directories first, always, whatever the sort — measured, and it is what
        # makes the screen's "up one level" row sit where the user expects.
        items = self._sorted(dirs, order) + self._sorted(files, order)
        count = len(items)
        page = items[start:start + limit] if limit > 0 else []
        if page:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._decorate_page, dir_path, page)

        root_info = dict(listing.get("root_info", {}))
        # nexusp carries `path` here and Moonraker does not. The screen is the
        # only reader and it has always been given one.
        root_info.setdefault("name", root)
        root_info["path"] = path
        return {"items": page, "count": count, "root_info": root_info}

    # -- server.history.count -----------------------------------------------

    async def _handle_history_count(self, web_request: WebRequest) -> Dict[str, Any]:
        """Rows in job_history for this instance.

        nexusp takes no arguments here and ignores any that are sent; the
        instance filter matches what `server.history.list` already scopes to, so
        the number the screen shows cannot disagree with the list it pages.
        """
        history = self.server.lookup_component("history")
        cursor = await history.history_table.execute(
            f"SELECT COUNT(*) FROM {HIST_TABLE} WHERE instance_id = ?",
            (self._history_instance(history),)
        )
        row = await cursor.fetchone()
        return {"count": int(row[0]) if row is not None else 0}


def load_component(config: ConfigHelper) -> CrealityCompat:
    return CrealityCompat(config)
