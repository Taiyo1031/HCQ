# HCQ — Houdini Cook Queue

HCQ is a local queue runner and passive cook monitor for Houdini 21.0 on
Windows. It runs node operations sequentially in the currently open Houdini
session and shows non-blocking completion notifications.

HCQ is unrelated to SideFX HQueue. It does not submit work to a farm, launch
another Houdini process, or create helper nodes.

Project repository: [Taiyo1031/HCQ](https://github.com/Taiyo1031/HCQ)

## Project Docs

- [Fix Backlog](docs/FIX_BACKLOG.md)
- [Acceptance Checklist](docs/ACCEPTANCE_CHECKLIST.md)
- [Distribution Guide](docs/DISTRIBUTION.md)
- [JSON Format](docs/JSON_FORMAT.md)

## Download

<p>
  <a href="https://github.com/Taiyo1031/HCQ/releases/latest/download/HCQ-Setup-1.2.0.exe"><img src="docs/readme_assets/download-hcq-setup.svg" alt="Download HCQ Setup"></a>
  <a href="https://github.com/Taiyo1031/HCQ/releases/latest/download/HCQ-1.2.0-houdini-package.zip"><img src="docs/readme_assets/download-houdini-package.svg" alt="Download Houdini Package Archive"></a>
  <a href="https://github.com/Taiyo1031/HCQ/releases"><img src="docs/readme_assets/view-release-downloads.svg" alt="View all HCQ release downloads"></a>
</p>

### What you need

| Required download | What to choose |
| --- | --- |
| **HCQ** | Click the green **Download HCQ Setup** button. |
| **Houdini** | Houdini 21.x for Windows. Skip this if it is already installed. |
| **Python / PySide6** | Nothing. HCQ uses the versions bundled with Houdini. |

The Windows Setup is the recommended installation. It needs no administrator
access and registers the same HCQ installation with every detected Houdini
21.x version. Advanced users can use Houdini's Package Browser with the purple
Package Archive button.

```text
HCQ-Setup-<version>.exe
HCQ-<version>-houdini-package.zip
HCQ-<version>-windows.zip          (legacy updater bridge)
```

Each file has a matching `.sha256` download. Do not use GitHub's automatically
generated **Source code** archives for a normal installation.

## Requirements

- Windows 11
- Houdini 21.x
- Houdini's bundled Python 3.11 and PySide6

No third-party Python package is required at runtime.

## Quick installation

### Option A — Windows Setup (recommended)

1. Close Houdini.
2. Download and run `HCQ-Setup-<version>.exe`.
3. Keep the default current-user installation.
4. Start Houdini 21.x.
5. Click **HCQ** on the HCQ shelf. If the shelf is not visible, use the shelf
   `+` menu to show **HCQ**.

Setup installs the plug-in at:

```text
%LOCALAPPDATA%\Programs\HCQ
```

Only a small `packages/hcq.json` registration is added to the Houdini
preference folders. HCQ also registers the user-profile preference path used
by `hython`, so both graphical and command-line Houdini load the same code.

### Option B — Houdini Package Browser

1. Download `HCQ-<version>-houdini-package.zip`.
2. In Houdini, create or switch a pane to **Inspectors ▸ Package Browser**.
3. Choose **File ▸ Install Package Archive...**.
4. Select the downloaded ZIP and an installation folder.
5. Accept the installation, then open the HCQ shelf or Python Panel.

The archive contains a root-level `hcq.json` and an `HCQ` content folder as
required by Houdini's Package Browser. It can be installed without manually
copying files into Documents.

### Upgrade from HCQ 1.1.x

Running Windows Setup automatically detects the former copy-installed layout.
Files declared by the old release manifest are backed up and removed, while
settings, Queue Library data, history, logs, and recovery data remain in:

```text
$HOUDINI_USER_PREF_DIR\HCQ
```

The legacy `HCQ-<version>-windows.zip` remains available so the 1.1.2 Update
button can reach 1.2.0. After that bridge update, click **Update** again and
choose **Install and Restart** to move to the standard installation.

### Confirm that HCQ is installed

If HCQ does not appear, open Package Browser and confirm that `hcq.json` is
enabled without errors. For Setup installations, confirm that
`%LOCALAPPDATA%\Programs\HCQ` exists. Restart Houdini after correcting a
Package JSON registration.

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

Use the compact **Update** button in the panel header:

1. Click **Update**.
2. HCQ checks the latest stable GitHub Release.
3. The Windows ZIP and its SHA-256 checksum are downloaded and verified.
4. When **Update Ready** appears, choose **Restart Now** or **Later**.

Only files listed in the release manifest are replaced. Queues, Monitor
registrations, settings, logs, history, and recovery data are preserved. A
backup is made before replacement and restored if installation fails.

**Restart Now** refuses to continue while an HCQ queue or another Houdini
session is using the same installation. Houdini shows its normal unsaved HIP
prompt. If you confirm the exit, HCQ waits for the old process to close and
reopens the same saved HIP in the same Houdini edition. Canceling the save
prompt leaves the staged update untouched.

Update staging, locks, backups, and recovery journals are installation-scoped
under `%LOCALAPPDATA%\HCQ\updates`. They are shared by graphical Houdini and
`hython`; project data remains version-specific under Houdini preferences.

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

The default **Use Current Houdini Setting** leaves Houdini's existing maximum
thread setting unchanged. To keep the machine more responsive during a Queue,
choose **Leave Logical Threads Free** and enter how many logical processor
threads HCQ should leave unused by Houdini. For example, on a machine with 16
logical threads, leaving 1 free applies a Houdini limit of 15.

You can also use all logical threads, set an exact maximum, or request a single
logical thread. HCQ shows the effective limit directly below each CPU control.
The previous Houdini setting is restored after every job, including failure,
cancellation, and exceptions.

Thread limits are upper bounds, not target Windows CPU percentages. Individual
nodes may use fewer threads, may be limited by GPU, memory, or disk performance,
or may not fully honor Houdini's runtime thread limit.

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
└─ recovery/
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

Build all three Windows distributions with Inno Setup 6 installed:

```powershell
python tools/build_release.py
```

Validate both ZIP layouts and load them from clean temporary Houdini
preferences:

```powershell
python tools/test_release_install.py
```

The functional release gate is tracked in
[docs/ACCEPTANCE_CHECKLIST.md](docs/ACCEPTANCE_CHECKLIST.md).

## Uninstallation

For a Setup installation, close Houdini and uninstall **HCQ** from Windows
Installed Apps or the HCQ Start menu folder. The uninstaller removes the
program and only the Package JSON files owned by Setup. Choose **No** when
asked about user data to keep queues, settings, logs, history, and recovery.

For a Package Archive installation, use Package Browser to unload/delete the
HCQ package and remove its selected installation folder. User data is not
inside that folder.

## Known limitations

- HCQ 1.2 is supported on Windows 11 and Houdini 21.x only.
- A foreground Houdini cook may block panel repainting and input.
- Custom HDA buttons that open modal dialogs are not guaranteed to run
  unattended.
- Some Houdini operations ignore or only partially honor runtime CPU limits.
- HCQ does not clear Houdini caches automatically between jobs.
- Farm scheduling, simultaneous jobs, scheduled starts, remote notifications,
  arbitrary Python JSON, and automatic PC shutdown are out of scope.

No license is granted for this repository.
