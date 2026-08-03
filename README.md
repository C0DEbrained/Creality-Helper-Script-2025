# Creality Helper Script - 2025 Support

## About

This script intended for use on Creality **K1 Series** and **Ender-3 V3 Series** printers allows to add more features.

Additional support for K1 2025 by @C0DEbrained.

## Retire Nexusp Backend (K1C 2025)

The K1C 2025 runs **two Moonrakers against one Klipper**: Creality's forked
`nexusp` on `:7125` (the touchscreen's backend) and this script's real Moonraker
on `:7126`. They share `-d /usr/data/printer_data`, so one gcode directory and
one klippy socket, but Creality namespaced the databases.

That split is not merely redundant. Querying the wrong port does not fail — **it
answers**:

```sh
curl -s http://<printer>:7125/server/spoolman/status
# nexusp -> {"error": {"code": 404, "message": "Method not found"}}
```

Read at face value that says Spoolman was never connected on this printer. It is
wrong, and every command pasted from a Klipper forum at `:7125` hits it.

**Customize menu → Retire Nexusp Backend** turns nexusp off and moves the real
Moonraker to `:7125`, the port the rest of the Klipper ecosystem assumes. It is
opt-in and off by default. The touchscreen is never patched — `vectorp`
hardcodes `http://127.0.0.1:7125`, and what answers there becomes ours.

The option:

- merges the two print histories before anything is disabled, so the screen does
  not lose everything printed before this script was installed;
- installs a small Moonraker component implementing the two JSON-RPC methods the
  screen calls and stock Moonraker does not have
  (`server.files.get_directory_ex` and `server.history.count`);
- offers to install Pillow into Moonraker's virtualenv. Pillow is **not** in the
  Moonraker this script ships, and Moonraker's own thumbnail parser needs it —
  without it a freshly uploaded file has no thumbnail on the screen at all;
- renames the nexusp init script rather than deleting anything.

**Restore Nexusp Backend** undoes all of it, and merges the prints made while
nexusp was retired back into its database first — otherwise the touchscreen's
history would silently stop at the day you retired it.

### Caveats

- **A firmware update can put the nexusp service file back.** `/usr/apps/etc/init.d`
  survives a factory reset, but an OTA can recreate `CS56nexusp_service` beside
  the disabled copy. It then loses the race for `:7125` to Moonraker and dies
  silently at every boot. The Information menu reports this with `~`, and
  running Retire Nexusp Backend again repairs it.
- **For about four seconds after a cold boot** the screen polls two methods
  (`printer.info`, `printer.objects.list`) that Moonraker only registers once
  Klipper connects. It resolves itself and needs no action.
- Two of the four Creality-only RPC methods are deliberately not implemented:
  `server.history.debug.job` and `server.debug.status`. Neither is
  screen-facing.

### Running the component's tests

The component and the history merge ship with their tests beside them. They are
the executable record of what was measured against `nexusp` before it was
switched off — once it is retired those measurements cannot be re-derived
without reviving it. They need only Python and pytest, no printer and no
Moonraker:

```sh
python3 -m pytest -q files/moonraker/creality-compat
```

This repository has no CI, so nothing runs them automatically.
