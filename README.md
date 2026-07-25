# HCQ — Houdini Cook Queue

HCQ is a local queue runner and passive cook monitor for Houdini 21.0 on
Windows. It runs node operations sequentially in the currently open Houdini
session and shows non-blocking completion notifications.

HCQ is unrelated to SideFX HQueue. It does not submit work to a farm, launch
another Houdini process, or create helper nodes.

Project repository: [Taiyo1031/HCQ](https://github.com/Taiyo1031/HCQ)

## Download

[![Download HCQ for Windows](https://img.shields.io/badge/Download-HCQ_for_Windows-2ea44f?style=for-the-badge&logo=windows11&logoColor=white)](https://github.com/Taiyo1031/HCQ/archive/refs/heads/main.zip)
[![Release Downloads](https://img.shields.io/badge/View-Release_Downloads-0969da?style=for-the-badge&logo=github&logoColor=white)](https://github.com/Taiyo1031/HCQ/releases)
[![Download Houdini](https://img.shields.io/badge/Get-Houdini_21.0+-ff4713?style=for-the-badge)](https://www.sidefx.com/download/)

### What you need

| Required download | What to choose |
| --- | --- |
| **HCQ** | Click the green **Download HCQ for Windows** button above. |
| **Houdini** | Houdini 21.0 or later for Windows. Skip this if it is already installed. |
| **Python / PySide6** | Nothing. HCQ uses the versions bundled with Houdini. |

The green button downloads the current `main` branch as `HCQ-main.zip` and
works even before a GitHub Release is published. When a packaged release is
available, you can instead open **Release Downloads** and download only:

```text
HCQ-<version>-windows.zip
HCQ-<version>-windows.zip.sha256  (optional checksum)
```

Do not download GitHub's automatically generated **Source code** archives from
the Releases page when a packaged Windows ZIP is available.

## Requirements

- Windows 11
- Houdini 21.0 or later
- Houdini's bundled Python 3.11 and PySide6

No third-party Python package is required at runtime.

## Quick installation

### Option A — Install the green-button download

1. Close Houdini.
2. Click **Download HCQ for Windows** above and extract `HCQ-main.zip`.
3. Find your Houdini user preference directory. For Houdini 21.0 on Windows,
   the default location is:

   ```text
   C:\Users\<you>\Documents\houdini21.0
   ```

4. Open the extracted `HCQ-main` folder.
5. Copy these two folders directly into the Houdini user preference directory:

   ```text
   HCQ-main\HCQ       → C:\Users\<you>\Documents\houdini21.0\HCQ
   HCQ-main\packages  → C:\Users\<you>\Documents\houdini21.0\packages
   ```

6. Start Houdini 21.0 or later.
7. Click **HCQ** on the HCQ shelf. If the shelf is not visible, use the shelf
   `+` menu to show **HCQ**.

### Option B — Install a packaged Windows release

1. Close Houdini.
2. Open **Release Downloads** above.
3. Download `HCQ-<version>-windows.zip`. The `.sha256` file is optional and is
   provided for integrity verification.
4. Extract the **contents** of the Windows ZIP directly into the Houdini user
   preference directory. Do not add another version-named wrapper folder.
5. Confirm that the installed layout contains:

   ```text
   $HOUDINI_USER_PREF_DIR/packages/hcq.json
   $HOUDINI_USER_PREF_DIR/HCQ/python3.11libs/hcq
   $HOUDINI_USER_PREF_DIR/HCQ/python_panels/hcq.pypanel
   $HOUDINI_USER_PREF_DIR/HCQ/toolbar/HCQ.shelf
   ```

6. Start Houdini 21.0 or later.
7. Click **HCQ** on the HCQ shelf, or create a Python Panel and choose
   **HCQ — Houdini Cook Queue**.

### Confirm that HCQ is installed

If HCQ does not appear, confirm that `hcq.json` is inside the Houdini
`packages` directory and that its sibling `HCQ` directory was extracted at the
same level. Restart Houdini after correcting the layout.

### Load a source checkout for development

Keep the repository layout unchanged and add its `packages` directory to
`HOUDINI_PACKAGE_DIR` before starting Houdini:

```powershell
$env:HOUDINI_PACKAGE_DIR = "C:\path\to\HCQ\packages"
& "C:\Program Files\Side Effects Software\Houdini 21.0.729\bin\houdini.exe"
```

The Package JSON resolves the sibling `HCQ` directory automatically. Restart
Houdini after changing Python, Shelf, Python Panel, or Package files.

### Update an installed copy

HCQ 1.1.0 is the first release with the built-in updater, so install this
version manually using the archive instructions above. Future updates can be
prepared from the compact **Update** button in the panel header:

1. Click **Update**.
2. HCQ checks the latest stable GitHub Release.
3. The Windows ZIP and its SHA-256 checksum are downloaded and verified.
4. When **Update Ready** appears, close and restart Houdini.

Only files listed in the release manifest are replaced. Queues, Monitor
registrations, settings, logs, history, and recovery data are preserved. A
backup is made before replacement and restored if installation fails.
If an update changes a Package, Shelf, or Python Panel definition, restart
Houdini once more after HCQ reports that the update was installed.

If HCQ cannot prove that a failed update was rolled back safely, it stops
loading and writes `HCQ/updates/UPDATE_RECOVERY_REQUIRED.json`. Restore the
latest matching folder under `HCQ/updates/backups`, then restart Houdini.

Automatic replacement is disabled for Git source checkouts. In that case,
**Update** links to the release page and the checkout must be updated with Git.

## Main workflows

### Queue Runner

1. Open the **Queues** tab and create a Queue Template.
2. Add selected nodes or enter node paths. Queue Editor is modeless: keep it
   open, select nodes in a Network Editor, then click **Add Selected Nodes**.
3. Confirm each job's action, frame range, CPU limit, error behavior, and
   output verification.
4. Add one or more templates to the **Run** tab.
5. Run **Preflight Check** and resolve errors or warnings.
6. Click **Run Queue**.

HCQ snapshots the Run List before execution. Temporary changes to the Run List
do not overwrite saved Queue Templates unless you explicitly save them.

Only one job runs at a time. HCQ lets Houdini perform the normal foreground
operation and waits for it to return before starting the next job. Houdini may
be unresponsive while a foreground operation is running; this is expected.

### Cook Monitor

1. Open the **Monitor** tab.
2. Enable monitoring.
3. Select important Houdini nodes and click **Add Selected Nodes**.
4. Continue using Houdini normally.

Cook Monitor does not start cooks. It checks only registered nodes and shows a
notification when it detects a completed cook. Monitoring is suspended while
Queue Runner owns execution and resumes after its baselines are refreshed.

Both the global Monitor switch and the individual node row must be enabled.
The default **Minimum Cook Duration** is 5 seconds, so shorter cooks are
detected but do not show a notification. The Monitor tab shows why a
notification was suppressed. Change the threshold in **Settings**, click
**Save**, and use **Test Notification** to verify the current configuration.

In-Houdini notifications appear at the lower-right of the Houdini window.
They include the result, node name, duration, and **Go to Node** when
available. Success and warning notifications close automatically; errors stay
visible until dismissed.

Optional Windows notifications can be enabled in **Settings**. They use
Houdini's bundled Qt system-tray support and require Windows notifications to
be enabled for Houdini. Focus Assist or Do Not Disturb can suppress them;
in-Houdini notifications remain available.

## Supported job actions

- **Auto Detect** — chooses the most appropriate supported action.
- **File Cache — Save to Disk** — presses the standard foreground
  `Sop/filecache::2.0` Save to Disk button.
- **ROP Render** — calls the ROP's foreground render operation.
- **TOP Cook** — cooks the selected TOP node and waits for PDG completion.
- **Force Cook Node** — forces a generic node cook.
- **Press Button Parameter** — presses one selected Houdini Button parameter.

Imported JSON can select only these actions. HCQ never evaluates Python stored
in JSON.

## Preflight and safety

Before a run, HCQ checks:

- Houdini version and current HIP state
- HIP association mismatches
- missing, invalid, disabled, or bypassed nodes
- action compatibility and Button parameter types
- frame ranges and CPU limits
- output paths, folder permissions, free disk space, existing outputs, and
  duplicate output destinations
- another active HCQ session

The default save behavior is **Always Save**. New untitled HIP files require
**Save As**. Optional backup uses Houdini's native backup operation.

The default error behavior is **Stop Queue** with no automatic retry. HCQ never
force-terminates Houdini. Use Houdini's normal Escape cancellation when a
blocking foreground cook prevents the panel from processing input.

## CPU limits

HCQ can keep the current Houdini thread setting, use all available threads,
apply a fixed maximum, reserve logical threads, or request single-thread mode.
The previous Houdini setting is restored after every job, including failure,
cancellation, and exceptions.

This is an upper limit only. Individual nodes may use fewer threads or may be
limited by GPU, memory, or disk performance.

## Output verification

**Basic** verification combines Houdini's operation result with new node errors
and warnings. When an output pattern is known, HCQ also checks that matching
files exist, are non-empty, and were updated by the current job. File existence
alone is never treated as proof that the Houdini operation succeeded.

File Cache output files and parent directories do not need to exist before a
run. Preflight checks the nearest existing parent directory without blocking
the queue. Basic Verification still reports a failure when the File Cache
finishes without producing its configured output.

## JSON and local data

HCQ supports queue template, Run List, active status, and run result documents.
All JSON is UTF-8, human-readable, and schema-versioned. See
[docs/JSON_FORMAT.md](docs/JSON_FORMAT.md).

Imported documents are validated and previewed. Import never starts execution.
File-system path remapping does not rewrite Houdini network node paths.

Local data is stored under:

```text
$HOUDINI_USER_PREF_DIR/HCQ/
├─ settings.json
├─ monitor_registry.json
├─ queues/
├─ runs/
├─ logs/
├─ recovery/
└─ updates/
```

An active run is persisted after meaningful state changes. If Houdini closes or
crashes during a job, the next HCQ startup treats the session as interrupted
and does not assume that existing outputs prove completion.

## Development

Run dependency-free unit tests:

```powershell
python -m unittest discover -s tests -v
```

Run Houdini integration checks:

```powershell
powershell -ExecutionPolicy Bypass -File tools/run_houdini_tests.ps1
```

Build the Windows archive:

```powershell
python tools/build_release.py
```

Validate that the built archive loads from clean temporary Houdini preferences:

```powershell
python tools/test_release_install.py
```

The functional release gate is tracked in
[docs/ACCEPTANCE_CHECKLIST.md](docs/ACCEPTANCE_CHECKLIST.md).

## Uninstallation

Close Houdini, remove `$HOUDINI_USER_PREF_DIR/packages/hcq.json`, and remove the
installed `HCQ` plug-in directory. Remove `$HOUDINI_USER_PREF_DIR/HCQ` only if
you also want to delete saved queues, settings, logs, and run history.

## Known limitations

- HCQ 1.1 is supported on Windows only.
- A foreground Houdini cook may block panel repainting and input.
- Custom HDA buttons that open modal dialogs are not guaranteed to run
  unattended.
- Some Houdini operations ignore or only partially honor runtime CPU limits.
- HCQ does not clear Houdini caches automatically between jobs.
- Farm scheduling, simultaneous jobs, scheduled starts, remote notifications,
  arbitrary Python JSON, and automatic PC shutdown are out of scope.

No license is granted for this repository.
