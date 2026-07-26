# HCQ Distribution Guide

HCQ 1.2 uses one source tree to produce three Windows assets:

| Asset | Purpose |
| --- | --- |
| `HCQ-Setup-<version>.exe` | Recommended per-user Windows installation |
| `HCQ-<version>-houdini-package.zip` | Houdini Package Browser installation |
| `HCQ-<version>-windows.zip` | Legacy 1.1.x updater bridge and manual fallback |

Every asset has a matching `.sha256` file. The version in the filename, Python
constant, release manifest, installation marker, documentation, and Git tag
must match.

## Installed layout

Windows Setup installs the shared program at:

```text
%LOCALAPPDATA%\Programs\HCQ
```

For every detected Houdini 21.x version it writes the same `hcq.json` to the
Documents and user-profile preference folders. This covers both desktop
Houdini and `hython`. The registration points to the shared program through
`$LOCALAPPDATA`; `houdini.env` is never modified.

User data remains under each Houdini preference directory:

```text
$HOUDINI_USER_PREF_DIR\HCQ
```

Update downloads, locks, backups, and recovery journals are stored by
installation identity under `%LOCALAPPDATA%\HCQ\updates`.

## Build

Install Inno Setup 6, then run:

```powershell
python tools/build_release.py --output dist
python tools/test_release_install.py --dist dist
```

The build rejects user-data paths, invalid package layouts, mismatched
versions, and missing manifest checksums. ZIP members are validated against
path traversal before the clean Houdini load test.

## Automated release

`.github/workflows/release.yml` runs unit tests and builds all assets on
`windows-2022`. Normal `main` and pull-request runs upload a workflow artifact.
A `v<version>` tag additionally creates a stable Latest GitHub Release. The
workflow refuses to overwrite an existing tag release.

Unsigned builds are supported. To enable Authenticode signing, configure both
repository secrets:

```text
HCQ_SIGNING_CERT_BASE64
HCQ_SIGNING_CERT_PASSWORD
```

The certificate is used only during the Windows build. No certificate or
password is included in artifacts.

## Legacy migration

Setup reads the old `HCQ_MANIFEST.json` and removes only unchanged,
manifest-owned plug-in files after verifying backups. Settings, Monitor
registrations, queues, runs, history, logs, and recovery data are reserved and
never migrated or deleted automatically. Modified files, unknown files,
custom Package JSON, and Git checkouts are preserved.

Uninstall removes the program and only unchanged Package JSON registrations
owned by Setup. User data removal is an explicit opt-in.
