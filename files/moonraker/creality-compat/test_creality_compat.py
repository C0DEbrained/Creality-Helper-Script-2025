#!/usr/bin/env python3
"""Offline checks for creality_compat.py — no printer, no Moonraker, no network.

Standalone, no conftest and no fixtures beyond this file:

    python3 -m pytest -q test_creality_compat.py

WHY THIS FILE EXISTS
--------------------
The component is a compatibility shim, and a shim's only job is to behave like
the thing it replaces. The thing it replaces — Creality's `nexusp` — is disabled
on any machine where this component runs, so "does it still behave right?" stops
being answerable by experiment the moment someone edits it. These tests are the
executable record of what the measurements found, and once a user has retired
nexusp they cannot be re-derived without reviving it on a spare port.

The rules being pinned are all counter-intuitive enough that a well-meaning
edit would break them:

  - directories sort BEFORE files, whatever the sort field
  - `.gco` and `.g` are hidden even though Moonraker itself calls them gcode
  - an EMPTY `.gcode` is shown, so the test is the extension, not the metadata
  - dotfiles are hidden, which is the only reason `gcodes/.thumbs` never
    appeared on the screen
  - `since`/`before` are accepted and IGNORED on purpose — implementing them
    would hide files the screen has always been shown
  - an unrecognised `order` falls back to name ascending rather than erroring
  - `count` is the total after filtering and before paging
  - thumbnail work happens AFTER the page is sliced, so a 91-file directory
    does not do 182 resizes to serve 20 rows

Nothing here touches Moonraker. The component is loaded into a synthetic package
with `..common` and `.history` stubbed, and `file_manager`/`history` are fakes
that return exactly the shapes the real ones do — which is the point: if
Moonraker renames `_list_directory`, these tests keep passing and the printer
breaks. That gap is why the component checks for those attributes at LOAD time;
the check itself is pinned below.

⚠ Add cases as `test_*` functions. A file named test_*.py whose assertions live
in a hand-rolled runner gets collected and runs nothing while reporting green.
"""
import asyncio
import importlib.machinery
import importlib.util
import os
import sys
import types

import pytest

REPO = os.path.dirname(os.path.abspath(__file__))
PKG = "k1c_compat_undertest"


def _load():
    """Load creality_compat.py as a package member, with Moonraker stubbed.

    TWO package levels, not one. The component says `from ..common import
    RequestType` because on the printer it lives at
    `moonraker/components/creality_compat.py` — so it has to be loaded as
    `<pkg>.components.creality_compat` for that `..` to resolve. Flattening it
    one level up fails with "attempted relative import beyond top-level
    package", which is a confusing way to be told the fixture is wrong rather
    than the component.

    `<pkg>.components.history` is stubbed too: the component imports HIST_TABLE
    from Moonraker's own history component rather than repeating the table name,
    so that a rename upstream is an ImportError at load.
    """
    name = f"{PKG}.components.creality_compat"
    if name in sys.modules:
        return sys.modules[name]

    class RequestType:
        GET = "GET"

    class TransportType:
        HTTP = "HTTP"
        WEBSOCKET = "WEBSOCKET"

    root = types.ModuleType(PKG)
    root.__path__ = [REPO]
    components = types.ModuleType(f"{PKG}.components")
    components.__path__ = [REPO]
    common = types.ModuleType(f"{PKG}.common")
    common.RequestType = RequestType
    common.TransportType = TransportType
    history = types.ModuleType(f"{PKG}.components.history")
    history.HIST_TABLE = "job_history"
    root.components = components
    root.common = common
    components.history = history
    sys.modules[PKG] = root
    sys.modules[f"{PKG}.components"] = components
    sys.modules[f"{PKG}.common"] = common
    sys.modules[f"{PKG}.components.history"] = history

    path = os.path.join(REPO, "creality_compat.py")
    spec = importlib.util.spec_from_file_location(
        name, path, loader=importlib.machinery.SourceFileLoader(name, path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cc = _load()
WEBSOCKET = sys.modules[f"{PKG}.common"].TransportType.WEBSOCKET


class ServerError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class FakeCursor:
    def __init__(self, row):
        self._row = row

    async def fetchone(self):
        return self._row


class FakeTable:
    def __init__(self, row):
        self._row = row
        self.queries = []

    async def execute(self, sql, params=()):
        self.queries.append((sql, params))
        return FakeCursor(self._row)


class FakeHistory:
    def __init__(self, count, instance_id=None):
        self.history_table = FakeTable((count,))
        if instance_id is not None:
            self.instance_id = instance_id


class FakeFileManager:
    """Returns exactly what `_list_directory(..., extended=True)` returns."""

    def __init__(self, dirs=(), files=(), root="gcodes", permissions="rw",
                 disk_root=None):
        self.dirs, self.files = list(dirs), list(files)
        self.root, self.permissions = root, permissions
        self.converted = []
        self.reserved = {}
        # When set, `_convert_request_path` hands back a REAL directory so the
        # component's `.thumbs` scan has something to read.
        self.disk_root = disk_root

    def _convert_request_path(self, path):
        root = path.strip("/").split("/", 1)[0]
        if root != self.root:
            raise ServerError(f"Invalid root path ({root})")
        self.converted.append(path)
        return self.root, self.disk_root or ("/fake/" + path)

    def _list_directory(self, dir_path, root, extended=False):
        return {
            "dirs": [dict(d) for d in self.dirs],
            "files": [dict(f) for f in self.files],
            "disk_usage": {"total": 1, "used": 0, "free": 1},
            "root_info": {"name": root, "permissions": self.permissions},
        }

    def get_directory(self, root="gcodes"):
        return self.disk_root or ""

    def add_reserved_path(self, name, res_path, read_access=True):
        if name in self.reserved:
            return False
        self.reserved[name] = (str(res_path), read_access)
        return True


class FakeServer:
    def __init__(self, components):
        self.components = components
        self.registered = []

    def register_endpoint(self, endpoint, request_types, callback, **kwargs):
        self.registered.append((endpoint, kwargs.get("transports")))

    def lookup_component(self, name):
        return self.components[name]

    def error(self, message, status_code=400):
        return ServerError(message, status_code)


class FakeConfig:
    def __init__(self, server, **options):
        self._server = server
        # Defaults match moonraker.conf on the box: tracing off, generation on.
        self.options = options

    def get_server(self):
        return self._server

    def getboolean(self, key, default=None):
        return self.options.get(key, default)


class FakeWebRequest:
    def __init__(self, **args):
        self.args = args

    def get_args(self):
        return self.args

    def _get(self, key, default, cast):
        if key not in self.args:
            if default is _MISSING:
                raise ServerError(f"No data for argument: {key}")
            return default
        return cast(self.args[key])

    def get_str(self, key, default=None):
        return self._get(key, _MISSING if default is None else default, str)

    def get_int(self, key, default=None):
        return self._get(key, _MISSING if default is None else default, int)


class _Missing:
    pass


_MISSING = _Missing()


@pytest.fixture(autouse=True)
def pil_absent_by_default(monkeypatch):
    """Pin the workstation to the printer's shipped state: no Pillow.

    `files/moonraker/moonraker.tar.gz` has no PIL, so that is the default a
    helper user gets and the default these tests run against. Setting the
    sys.modules entry to None is what makes `from PIL import Image` raise.
    Tests about generation ask for `fake_pil`, which runs after this and wins.
    """
    monkeypatch.setitem(sys.modules, "PIL", None)
    monkeypatch.setitem(sys.modules, "PIL.Image", None)


def entry(name, is_dir=False, modified=100.0, size=10):
    key = "dirname" if is_dir else "filename"
    return {key: name, "modified": modified, "size": size, "permissions": "rw"}


def build(dirs=(), files=(), history=42, root="gcodes", disk_root=None,
          instance_id=None, **options):
    fm = FakeFileManager(dirs=dirs, files=files, root=root, disk_root=disk_root)
    server = FakeServer({"file_manager": fm,
                         "history": FakeHistory(history, instance_id)})
    return cc.CrealityCompat(FakeConfig(server, **options)), fm, server


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def call(shim, **args):
    args.setdefault("path", "gcodes")
    args.setdefault("start", 0)
    args.setdefault("limit", 100)
    args.setdefault("order", "name")
    return run(shim._handle_directory_ex(FakeWebRequest(**args)))


def names(result):
    return [(i["type"], i.get("filename") or i.get("dirname")) for i in result["items"]]


# --------------------------------------------------------------------------
# Registration and load-time guards
# --------------------------------------------------------------------------

def test_it_registers_exactly_the_two_missing_methods():
    _, _, server = build()
    assert [ep for ep, _ in server.registered] == [
        "/server/files/get_directory_ex", "/server/history/count"]


def test_both_methods_are_websocket_only():
    """`GET /server/files/directory_ex` returned 404 on nexusp — measured, and
    that 404 is exactly what made the method look absent. Registering on the
    default transports would answer it over HTTP instead."""
    _, _, server = build()
    assert [t for _, t in server.registered] == [WEBSOCKET, WEBSOCKET]


@pytest.mark.parametrize("missing", ["_list_directory", "_convert_request_path"])
def test_a_renamed_file_manager_method_fails_at_load_by_name(missing):
    """The only warning anyone gets. `install_moonraker_nginx` runs `git
    checkout master; git pull`, so every user's Moonraker is a moving target,
    and the fakes in this file can never catch a rename. Failing at startup with
    the attribute's name beats failing the first time somebody opens the file
    browser."""
    def gone(self):
        raise AttributeError(missing)

    renamed = type("RenamedFileManager", (FakeFileManager,),
                   {missing: property(gone)})
    server = FakeServer({"file_manager": renamed(), "history": FakeHistory(0)})
    with pytest.raises(ServerError) as exc:
        cc.CrealityCompat(FakeConfig(server))
    assert missing in exc.value.message


# --------------------------------------------------------------------------
# What is visible
# --------------------------------------------------------------------------

def test_directories_sort_before_files_whatever_the_order():
    shim, _, _ = build(dirs=[entry("zzz_dir", True, modified=1.0, size=1)],
                       files=[entry("aaa.gcode", modified=999.0, size=999)])
    for order in ("name", "name desc", "datetime desc", "size desc", "size"):
        assert names(call(shim, order=order))[0][0] == "d", order


def test_dotfiles_and_dotdirs_are_hidden():
    """The only reason `gcodes/.thumbs` never appeared on the touchscreen."""
    shim, _, _ = build(dirs=[entry(".thumbs", True), entry("keep", True)],
                       files=[entry(".hidden.gcode"), entry("keep.gcode")])
    assert names(call(shim)) == [("d", "keep"), ("f", "keep.gcode")]


def test_only_dot_gcode_counts_as_a_file():
    """`.g` and `.gco` ARE gcode to Moonraker and are NOT listed here.

    Measured against nexusp: a `.gco` file it could see was not returned. Being
    more permissive would put files on the screen that have never been there.
    """
    shim, _, _ = build(files=[entry("a.gcode"), entry("b.gco"), entry("c.g"),
                              entry("d.txt"), entry("e.GCODE")])
    assert names(call(shim)) == [("f", "a.gcode"), ("f", "e.GCODE")]


def test_an_empty_gcode_is_listed():
    """The test is the extension, not the metadata — measured with `touch`."""
    shim, _, _ = build(files=[entry("empty.gcode", size=0)])
    assert names(call(shim)) == [("f", "empty.gcode")]


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------

def test_name_order_is_case_insensitive():
    """A DELIBERATE divergence from nexusp, which sorted by codepoint and so put
    every capitalised name ahead of every lowercase one — `Assembly`, `BM`,
    `apple`, `ss_low`."""
    shim, _, _ = build(files=[entry("ss_low.gcode"), entry("Assembly.gcode"),
                              entry("apple.gcode"), entry("BM.gcode")])
    assert [n for _, n in names(call(shim, order="name"))] == [
        "apple.gcode", "Assembly.gcode", "BM.gcode", "ss_low.gcode"]


def test_digit_runs_sort_numerically():
    """`ss_ruin_2` before `ss_ruin_10`. Codepoint order put 10 before 2, which
    is what a directory of numbered parts looks wrong in."""
    shim, _, _ = build(files=[entry("ss_ruin_10.gcode"), entry("ss_ruin_2.gcode"),
                              entry("ss_ruin_3.gcode"), entry("ss_ruin_1.gcode")])
    assert [n for _, n in names(call(shim, order="name"))] == [
        "ss_ruin_1.gcode", "ss_ruin_2.gcode", "ss_ruin_3.gcode",
        "ss_ruin_10.gcode"]


def test_a_number_never_compares_against_a_letter():
    """The key is built so digit and text chunks are never compared directly —
    otherwise Python raises TypeError partway through a sort and the file
    browser 500s on one awkward filename."""
    shim, _, _ = build(files=[entry("2.gcode"), entry("a2.gcode"),
                              entry("2a.gcode"), entry("a.gcode")])
    got = [n for _, n in names(call(shim, order="name"))]
    assert len(got) == 4 and got[0] in ("2.gcode", "2a.gcode")


def test_case_only_differences_get_a_stable_order():
    shim, _, _ = build(files=[entry("Cube.gcode"), entry("cube.gcode")])
    first = [n for _, n in names(call(shim, order="name"))]
    second = [n for _, n in names(call(shim, order="name"))]
    assert first == second and set(first) == {"Cube.gcode", "cube.gcode"}


def test_desc_reverses_it():
    shim, _, _ = build(files=[entry("a.gcode"), entry("b.gcode")])
    assert [n for _, n in names(call(shim, order="name desc"))] == [
        "b.gcode", "a.gcode"]


def test_datetime_and_size_sort_on_their_own_fields():
    shim, _, _ = build(files=[entry("old_big.gcode", modified=1.0, size=900),
                              entry("new_small.gcode", modified=9.0, size=1)])
    assert [n for _, n in names(call(shim, order="datetime desc"))][0] == "new_small.gcode"
    assert [n for _, n in names(call(shim, order="size desc"))][0] == "old_big.gcode"


def test_an_unknown_order_falls_back_to_name_ascending():
    """nexusp answers 'files', 'type' and outright nonsense identically, and
    with a list rather than an error. Pinned so a future edit does not decide
    that an unrecognised sort deserves a 400."""
    shim, _, _ = build(files=[entry("b.gcode"), entry("a.gcode")])
    for order in ("files", "type", "bogus"):
        assert [n for _, n in names(call(shim, order=order))] == [
            "a.gcode", "b.gcode"], order


# --------------------------------------------------------------------------
# Keyword, paging, count
# --------------------------------------------------------------------------

def test_keyword_is_a_case_insensitive_substring():
    shim, _, _ = build(files=[entry("Cube-4m59s.gcode"), entry("Other.gcode")])
    for kw in ("cube", "CUBE", "ube-4"):
        assert names(call(shim, keyword=kw)) == [("f", "Cube-4m59s.gcode")], kw


def test_keyword_narrows_the_count_not_just_the_page():
    shim, _, _ = build(files=[entry("a.gcode"), entry("b.gcode"), entry("aa.gcode")])
    assert call(shim, keyword="a")["count"] == 2


def test_count_is_the_total_before_paging():
    shim, _, _ = build(files=[entry("%02d.gcode" % i) for i in range(10)])
    result = call(shim, start=0, limit=3)
    assert result["count"] == 10 and len(result["items"]) == 3


def test_start_is_a_row_offset():
    shim, _, _ = build(files=[entry("%02d.gcode" % i) for i in range(10)])
    assert names(call(shim, start=3, limit=2)) == [("f", "03.gcode"), ("f", "04.gcode")]


def test_start_past_the_end_is_an_empty_page_with_the_count_intact():
    shim, _, _ = build(files=[entry("a.gcode")])
    result = call(shim, start=500, limit=3)
    assert result["items"] == [] and result["count"] == 1


def test_limit_zero_returns_nothing():
    shim, _, _ = build(files=[entry("a.gcode")])
    result = call(shim, start=0, limit=0)
    assert result["items"] == [] and result["count"] == 1


def test_a_negative_start_does_not_wrap_to_the_end_of_the_listing():
    """Python would slice from the tail and hand back real files as if they
    were the first page, which reads as corruption rather than a bad request."""
    shim, _, _ = build(files=[entry("a.gcode"), entry("b.gcode"), entry("c.gcode")])
    assert names(call(shim, start=-2, limit=2)) == [("f", "a.gcode"), ("f", "b.gcode")]


# --------------------------------------------------------------------------
# Arguments
# --------------------------------------------------------------------------

@pytest.mark.parametrize("missing", ["start", "limit", "order"])
def test_start_limit_and_order_are_all_required(missing):
    shim, _, _ = build(files=[entry("a.gcode")])
    args = {"path": "gcodes", "start": 0, "limit": 5, "order": "name"}
    args.pop(missing)
    with pytest.raises(ServerError) as exc:
        run(shim._handle_directory_ex(FakeWebRequest(**args)))
    assert exc.value.message == "Invalid parameter"


def test_a_missing_path_says_so_by_name():
    shim, _, _ = build()
    with pytest.raises(ServerError) as exc:
        run(shim._handle_directory_ex(
            FakeWebRequest(start=0, limit=5, order="name")))
    assert exc.value.message == "No data for argument: path"


def test_since_and_before_are_accepted_and_ignored():
    """Deliberate. nexusp ignores them — measured, a window excluding almost
    every file left the count unchanged — and honouring them here would make
    files disappear from a browser that has always shown them."""
    shim, _, _ = build(files=[entry("old.gcode", modified=1.0),
                              entry("new.gcode", modified=9_000_000_000.0)])
    result = call(shim, since=8_000_000_000, before=8_000_000_001)
    assert result["count"] == 2


def test_an_unknown_root_propagates_the_file_managers_error():
    shim, _, _ = build()
    with pytest.raises(ServerError) as exc:
        call(shim, path="nosuchroot")
    assert exc.value.message == "Invalid root path (nosuchroot)"


# --------------------------------------------------------------------------
# root_info
# --------------------------------------------------------------------------

def test_root_info_carries_the_path_moonraker_does_not_supply():
    shim, _, _ = build(files=[entry("a.gcode")])
    info = call(shim, path="gcodes/sub")["root_info"]
    assert info == {"name": "gcodes", "permissions": "rw", "path": "gcodes/sub"}


# --------------------------------------------------------------------------
# server.history.count
# --------------------------------------------------------------------------

def test_history_count_returns_the_row_count():
    shim, _, _ = build(history=42)
    assert run(shim._handle_history_count(FakeWebRequest())) == {"count": 42}


def test_history_count_is_scoped_the_way_the_history_list_is():
    """A count that disagrees with the list it sizes is the same
    plausible-wrong-answer failure retiring nexusp exists to kill. Moonraker's
    `server.history.list` filters on a bare "default" literal today."""
    shim, _, server = build(history=7)
    run(shim._handle_history_count(FakeWebRequest()))
    sql, params = server.components["history"].history_table.queries[0]
    assert "COUNT(*)" in sql and "instance_id = ?" in sql and params == ("default",)


def test_history_count_follows_the_history_component_if_it_grows_an_instance_id():
    """Derived, not hardcoded, so the docstring's claim stays true when
    Moonraker stops using a literal."""
    shim, _, server = build(history=7, instance_id="printer-2")
    run(shim._handle_history_count(FakeWebRequest()))
    _, params = server.components["history"].history_table.queries[0]
    assert params == ("printer-2",)


def test_history_count_ignores_any_arguments_sent():
    shim, _, _ = build(history=3)
    result = run(shim._handle_history_count(
        FakeWebRequest(limit=10, order="datetime desc")))
    assert result == {"count": 3}


# --------------------------------------------------------------------------
# Thumbnails — read off the disk, not out of the metadata
# --------------------------------------------------------------------------

def thumbs_dir(tmp_path, *names_):
    """A `.thumbs` directory holding the named PNGs, with real byte sizes."""
    d = tmp_path / ".thumbs"
    d.mkdir()
    for i, name in enumerate(names_):
        (d / name).write_bytes(b"x" * (10 + i))
    return str(tmp_path)


def test_on_disk_thumbnails_are_added_to_the_metadatas(tmp_path):
    """The 66-blank-files bug. Moonraker parses the slicer's sizes out of the
    gcode; nexusp ALSO rendered 48/195 into .thumbs and listed them. Reporting
    only the parsed set is what left most of the browser blank."""
    root = thumbs_dir(tmp_path, "Cube-48x48.png", "Cube-195x195.png")
    shim, _, _ = build(disk_root=root, files=[
        dict(entry("Cube.gcode"), thumbnails=[
            {"width": 320, "height": 320, "size": 9,
             "relative_path": ".thumbs/Cube-320x320.png"}])])
    got = call(shim)["items"][0]["thumbnails"]
    assert [(t["width"], t["height"]) for t in got] == [(48, 48), (195, 195), (320, 320)]


def test_the_metadata_entry_wins_on_a_duplicate_size(tmp_path):
    """Moonraker read its entry out of the gcode, which is better provenance
    than a filename — so a same-size PNG on disk must not displace it."""
    root = thumbs_dir(tmp_path, "Cube-320x320.png")
    original = {"width": 320, "height": 320, "size": 4242,
                "relative_path": ".thumbs/from-metadata.png"}
    shim, _, _ = build(disk_root=root, generate_thumbnails=False,
                       files=[dict(entry("Cube.gcode"), thumbnails=[original])])
    got = call(shim)["items"][0]["thumbnails"]
    assert got == [original]


def test_a_file_with_no_metadata_thumbnails_still_gets_the_disk_ones(tmp_path):
    root = thumbs_dir(tmp_path, "Cube-195x195.png")
    shim, _, _ = build(disk_root=root, files=[entry("Cube.gcode")])
    got = call(shim)["items"][0]["thumbnails"]
    assert [(t["width"], t["height"]) for t in got] == [(195, 195)]


def test_thumbnails_are_matched_to_their_own_file(tmp_path):
    """Stems full of hyphens and digits are the norm here, so the size suffix
    is parsed from the END and the rest must match the gcode stem exactly."""
    root = thumbs_dir(tmp_path, "Cube-4m59s-0.2w-0.1h-195x195.png",
                      "Other-195x195.png")
    shim, _, _ = build(disk_root=root, files=[entry("Cube-4m59s-0.2w-0.1h.gcode")])
    got = call(shim)["items"][0]["thumbnails"]
    assert [t["relative_path"] for t in got] == [".thumbs/Cube-4m59s-0.2w-0.1h-195x195.png"]


def test_unparseable_names_in_thumbs_are_ignored(tmp_path):
    root = thumbs_dir(tmp_path, "Cube-195x195.png", "Cube.png", "README.txt",
                      "Cube-bigx195.png")
    shim, _, _ = build(disk_root=root, files=[entry("Cube.gcode")])
    got = call(shim)["items"][0]["thumbnails"]
    assert [t["relative_path"] for t in got] == [".thumbs/Cube-195x195.png"]


def test_the_reported_size_is_the_real_byte_size(tmp_path):
    root = thumbs_dir(tmp_path, "Cube-195x195.png")
    shim, _, _ = build(disk_root=root, files=[entry("Cube.gcode")])
    assert call(shim)["items"][0]["thumbnails"][0]["size"] == 10


def test_a_directory_with_no_thumbs_is_not_an_error(tmp_path):
    """Every root except gcodes. The scan must degrade to "none", not raise."""
    shim, _, _ = build(disk_root=str(tmp_path), files=[entry("Cube.gcode")])
    assert call(shim)["items"][0].get("thumbnails") in (None, [])


def test_only_the_page_is_decorated(tmp_path):
    """Thumbnail work happens AFTER the slice. Sorting reads filename/modified/
    size and never thumbnails, so nothing above needs it — and doing it first
    meant a 91-file directory did the work for all 91 to serve 20 rows, on the
    event loop that also serves klippy and Fluidd, during a print."""
    root = thumbs_dir(tmp_path, "a-195x195.png", "b-195x195.png")
    shim, _, _ = build(disk_root=root,
                       files=[entry("a.gcode"), entry("b.gcode")])
    result = call(shim, start=0, limit=1)
    assert result["count"] == 2
    assert result["items"][0]["filename"] == "a.gcode"
    assert result["items"][0]["thumbnails"]


def test_an_empty_page_does_no_thumbnail_work(tmp_path):
    root = thumbs_dir(tmp_path, "a-195x195.png")
    shim, _, _ = build(disk_root=root, files=[entry("a.gcode")])
    assert call(shim, start=0, limit=0)["items"] == []


# --------------------------------------------------------------------------
# Thumbnail generation — the sizes nexusp used to render and Moonraker does not
# --------------------------------------------------------------------------

class FakeImage:
    """Enough of PIL for this component, and no more.

    Pillow is in neither the workstation nor the venv this repo ships, so the
    generation path would otherwise be untestable — and it is the part that
    writes to the printer's flash, which is exactly the part worth pinning.
    `resize` records its arguments and `save` writes a real file, so assertions
    can be about intent (which sizes, from which source) rather than pixels.
    """

    calls = []

    def __init__(self, path, size):
        self.path = path
        self.size = size

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def convert(self, mode):
        return self

    def resize(self, size, resample=None):
        FakeImage.calls.append((self.path, size))
        return FakeImage(self.path, size)

    def save(self, dest):
        with open(dest, "wb") as fh:
            fh.write(b"png" * self.size[0])


@pytest.fixture
def fake_pil(monkeypatch):
    FakeImage.calls = []
    module = types.ModuleType("PIL")
    image_mod = types.ModuleType("PIL.Image")

    def _open(path):
        # Dimensions come from the filename, which is where they come from on
        # the box too — the component never asks PIL for them.
        stem = os.path.basename(path).rsplit(".", 1)[0]
        w, h = stem.rsplit("-", 1)[1].split("x")
        return FakeImage(path, (int(w), int(h)))

    image_mod.open = _open
    image_mod.LANCZOS = "LANCZOS"
    module.Image = image_mod
    monkeypatch.setitem(sys.modules, "PIL", module)
    monkeypatch.setitem(sys.modules, "PIL.Image", image_mod)
    return FakeImage


def test_it_renders_the_two_sizes_moonraker_never_makes(tmp_path, fake_pil):
    root = thumbs_dir(tmp_path, "Cube-300x300.png")
    shim, _, _ = build(disk_root=root, files=[entry("Cube.gcode")])
    got = call(shim)["items"][0]["thumbnails"]
    assert [(t["width"], t["height"]) for t in got] == [(48, 48), (195, 195), (300, 300)]
    assert os.path.exists(os.path.join(root, ".thumbs", "Cube-195x195.png"))


def test_it_scales_from_the_largest_source_available(tmp_path, fake_pil):
    root = thumbs_dir(tmp_path, "Cube-32x32.png", "Cube-300x300.png",
                      "Cube-96x96.png")
    shim, _, _ = build(disk_root=root, files=[entry("Cube.gcode")])
    call(shim)
    sources = {os.path.basename(path) for path, _ in fake_pil.calls}
    assert sources == {"Cube-300x300.png"}


def test_it_never_upscales(tmp_path, fake_pil):
    """A 32x32 blown up to a 195x195 tile looks broken, which is worse than
    looking absent. 48x48 is still skipped — 32 is smaller than that too."""
    root = thumbs_dir(tmp_path, "Cube-32x32.png")
    shim, _, _ = build(disk_root=root, files=[entry("Cube.gcode")])
    got = call(shim)["items"][0]["thumbnails"]
    assert [(t["width"], t["height"]) for t in got] == [(32, 32)]
    assert fake_pil.calls == []


def test_a_size_already_on_disk_is_not_re_rendered(tmp_path, fake_pil):
    """Once per file. This runs on every directory listing, and the write goes
    to flash."""
    root = thumbs_dir(tmp_path, "Cube-300x300.png", "Cube-48x48.png",
                      "Cube-195x195.png")
    shim, _, _ = build(disk_root=root, files=[entry("Cube.gcode")])
    call(shim)
    assert fake_pil.calls == []


def test_generation_can_be_turned_off(tmp_path, fake_pil):
    root = thumbs_dir(tmp_path, "Cube-300x300.png")
    shim, _, _ = build(disk_root=root, files=[entry("Cube.gcode")],
                       generate_thumbnails=False)
    got = call(shim)["items"][0]["thumbnails"]
    assert [(t["width"], t["height"]) for t in got] == [(300, 300)]
    assert fake_pil.calls == []


def test_a_file_with_no_thumbnails_at_all_is_left_alone(tmp_path, fake_pil):
    """Nothing to scale FROM. Generating would mean inventing an image — which
    is every freshly uploaded file on a box without Pillow, because Moonraker's
    own metadata parser needs Pillow to produce the embedded set."""
    root = thumbs_dir(tmp_path)
    shim, _, _ = build(disk_root=root, files=[entry("Cube.gcode")])
    assert call(shim)["items"][0].get("thumbnails") in (None, [])
    assert fake_pil.calls == []


def test_no_thumbs_directory_is_created_for_a_file_with_nothing_to_scale(
        tmp_path, fake_pil):
    """A directory of thumbnail-less gcode must not grow an empty `.thumbs`
    just because it was browsed."""
    shim, _, _ = build(disk_root=str(tmp_path), files=[entry("Cube.gcode")])
    call(shim)
    assert not os.path.exists(os.path.join(str(tmp_path), ".thumbs"))


def test_a_render_failure_does_not_break_the_listing(tmp_path, fake_pil, monkeypatch):
    """One unreadable PNG must not take the whole file browser down with it."""
    def boom(path):
        raise OSError("cannot identify image file")
    monkeypatch.setattr(sys.modules["PIL.Image"], "open", boom)
    root = thumbs_dir(tmp_path, "Cube-300x300.png")
    shim, _, _ = build(disk_root=root, files=[entry("Cube.gcode")])
    got = call(shim)["items"][0]["thumbnails"]
    assert [(t["width"], t["height"]) for t in got] == [(300, 300)]


def test_a_failed_render_is_not_retried_forever(tmp_path, fake_pil, monkeypatch):
    """Otherwise a broken PNG means a traceback on every listing, for as long as
    the file exists. A Moonraker restart clears the memo, so a repaired
    filesystem heals on its own."""
    attempts = []

    def boom(path):
        attempts.append(path)
        raise OSError("cannot identify image file")
    monkeypatch.setattr(sys.modules["PIL.Image"], "open", boom)
    root = thumbs_dir(tmp_path, "Cube-300x300.png")
    shim, _, _ = build(disk_root=root, files=[entry("Cube.gcode")])
    call(shim)
    first = len(attempts)
    call(shim)
    call(shim)
    assert first == 2 and len(attempts) == 2


# --------------------------------------------------------------------------
# Pillow is NOT in the venv this repo ships
# --------------------------------------------------------------------------

def test_a_missing_pillow_turns_generation_off_rather_than_failing(tmp_path):
    """`tar -tzf files/moonraker/moonraker.tar.gz | grep -ci "PIL/\\|pillow"`
    returns 0, so this is the state a clean helper install is in. A directory
    listing must never fail because an optional renderer is absent."""
    root = thumbs_dir(tmp_path, "Cube-300x300.png")
    shim, _, _ = build(disk_root=root, files=[entry("Cube.gcode")])
    assert shim.generate_thumbs is False
    got = call(shim)["items"][0]["thumbnails"]
    assert [(t["width"], t["height"]) for t in got] == [(300, 300)]


def test_a_missing_pillow_still_lists_every_thumbnail_on_disk(tmp_path):
    """The disk-union listing is most of the fix and does not need Pillow at
    all — it is what put the 66 blank files back."""
    root = thumbs_dir(tmp_path, "Cube-48x48.png", "Cube-195x195.png",
                      "Cube-300x300.png")
    shim, _, _ = build(disk_root=root, files=[entry("Cube.gcode")])
    got = call(shim)["items"][0]["thumbnails"]
    assert [(t["width"], t["height"]) for t in got] == [
        (48, 48), (195, 195), (300, 300)]


# --------------------------------------------------------------------------
# `.thumbs` is kept out of file_manager's inotify watch
# --------------------------------------------------------------------------

def test_existing_thumb_dirs_are_reserved_at_load(tmp_path, fake_pil):
    """Writing a PNG into a watched directory fires `notify_filelist_changed`,
    and file_manager has no dot-directory filter — so generating thumbnails
    inside a listing would broadcast a phantom `create_file` for every PNG to
    Fluidd and to the screen. Reserving has to happen before file_manager's
    initial scan, which runs in its `component_init`, after every component is
    constructed."""
    root = thumbs_dir(tmp_path, "Cube-195x195.png")
    sub = tmp_path / "sub" / ".thumbs"
    sub.mkdir(parents=True)
    _, fm, _ = build(disk_root=root)
    reserved = {path for path, _ in fm.reserved.values()}
    assert reserved == {os.path.join(root, ".thumbs"), str(sub)}


def test_reserved_thumb_dirs_stay_readable(tmp_path, fake_pil):
    """Read access is left on, or the thumbnails stop being served over HTTP
    and every tile goes blank — the exact failure this is meant to fix."""
    root = thumbs_dir(tmp_path, "Cube-195x195.png")
    _, fm, _ = build(disk_root=root)
    assert all(read_access for _, read_access in fm.reserved.values())


def test_a_new_thumb_dir_is_reserved_before_it_is_created(tmp_path, fake_pil):
    """The directory-create inotify event checks the reserved list, so the
    reservation only works if it lands first. Here `.thumbs` does not exist at
    load — the source is a slicer-embedded thumbnail — so the component has to
    reserve it on the way to creating it."""
    root = str(tmp_path)
    shim, fm, _ = build(disk_root=root, files=[
        dict(entry("Cube.gcode"), thumbnails=[
            {"width": 300, "height": 300, "size": 9,
             "relative_path": ".thumbs/Cube-300x300.png"}])])
    assert fm.reserved == {}
    call(shim)
    assert os.path.join(root, ".thumbs") in {p for p, _ in fm.reserved.values()}
    assert os.path.isdir(os.path.join(root, ".thumbs"))


def test_nothing_is_reserved_when_generation_is_off(tmp_path, fake_pil):
    """No writes, no phantom notifications, no reason to hide `.thumbs` from
    Fluidd's file list."""
    root = thumbs_dir(tmp_path, "Cube-195x195.png")
    _, fm, _ = build(disk_root=root, generate_thumbnails=False)
    assert fm.reserved == {}


def test_nothing_is_reserved_when_pillow_is_missing(tmp_path):
    """Same reasoning: without Pillow the component never writes a PNG, so
    there is nothing to keep out of the watch."""
    root = thumbs_dir(tmp_path, "Cube-195x195.png")
    _, fm, _ = build(disk_root=root)
    assert fm.reserved == {}


# --------------------------------------------------------------------------
# Sort parsing — the reason the screen's sort buttons did nothing
# --------------------------------------------------------------------------

def test_the_sort_field_is_matched_case_insensitively():
    """The bug. The first version compared the field case-sensitively, so a
    screen sending "Datetime" fell through to the name-ascending default —
    silently, because falling back rather than erroring is nexusp's behaviour."""
    shim, _, _ = build(files=[entry("a.gcode", modified=1.0),
                              entry("b.gcode", modified=9.0)])
    for order in ("DATETIME DESC", "Datetime Desc", "datetime desc"):
        assert [n for _, n in names(call(shim, order=order))] == [
            "b.gcode", "a.gcode"], order


@pytest.mark.parametrize("order", ["datetime,desc", "datetime;desc",
                                   "datetime|desc", "datetime  desc"])
def test_the_direction_survives_any_plausible_separator(order):
    """The screen's exact encoding was never measured — nexusp was only ever
    asked in the form the binary's strings suggested. Splitting on whitespace
    alone is a guess that fails silently, so this splits on all of them."""
    shim, _, _ = build(files=[entry("a.gcode", modified=1.0),
                              entry("b.gcode", modified=9.0)])
    assert [n for _, n in names(call(shim, order=order))] == ["b.gcode", "a.gcode"]


@pytest.mark.parametrize("alias", ["date desc", "time desc", "modified desc",
                                   "mtime desc"])
def test_time_aliases_all_sort_by_modified(alias):
    shim, _, _ = build(files=[entry("a.gcode", modified=1.0),
                              entry("b.gcode", modified=9.0)])
    assert [n for _, n in names(call(shim, order=alias))][0] == "b.gcode"


@pytest.mark.parametrize("alias", ["size desc", "filesize desc", "bytes desc"])
def test_size_aliases_all_sort_by_size(alias):
    shim, _, _ = build(files=[entry("small.gcode", size=1),
                              entry("big.gcode", size=999)])
    assert [n for _, n in names(call(shim, order=alias))][0] == "big.gcode"


def test_the_order_string_the_screen_actually_sends():
    """Measured from the box on 2026-08-02 with `log_requests: True`. The comma
    is the whole reason the sort buttons did nothing: split on whitespace alone,
    `name,asc,folder` is one token that matches no field."""
    shim, _, _ = build(files=[entry("a.gcode", modified=1.0, size=999),
                              entry("b.gcode", modified=9.0, size=1)])

    def order_of(o):
        return [n for _, n in names(call(shim, order=o))]

    assert order_of("name,asc,folder") == ["a.gcode", "b.gcode"]
    assert order_of("datetime,desc,folder") == ["b.gcode", "a.gcode"]
    assert order_of("datetime,asc,folder") == ["a.gcode", "b.gcode"]
    assert order_of("size,desc,folder") == ["a.gcode", "b.gcode"]
    assert order_of("size,asc,folder") == ["b.gcode", "a.gcode"]


def test_the_full_argument_set_the_screen_sends_is_accepted():
    """It sends `root` beside `path`, and zeroes for since/before plus an empty
    keyword on every call — none of which may be mistaken for a filter."""
    shim, _, _ = build(files=[entry("a.gcode"), entry("b.gcode")])
    result = call(shim, root="gcodes", path="gcodes", limit=5, start=0,
                  since=0, before=0, order="name,asc,folder", keyword="")
    assert result["count"] == 2 and len(result["items"]) == 2
