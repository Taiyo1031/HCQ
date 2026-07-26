# HCQ 1.2.0 Acceptance Checklist

## Automated validation recorded on 2026-07-26

- [x] 71 dependency-free unit tests pass.
- [x] Houdini 21.0.729 integration checks pass for Generic SOP, File Cache,
  ROP, TOP, Button, CPU restoration, and Monitor rename tracking.
- [x] PySide6 offscreen smoke checks pass for all five tabs, modeless Queue
  Editor graph selection, full-width header actions, state-aware Run controls,
  History action sizing, CPU limit guidance, Settings notifications, Import
  Preview, and Missing Node resolution widgets.
- [x] Shelf and Python Panel XML validate against the SideFX Houdini 21.0
  XSD files.
- [x] `HCQ-1.2.0-windows.zip` and
  `HCQ-1.2.0-houdini-package.zip` validate and load `hcq` 1.2.0 through
  their respective Package JSON layouts from clean temporary preferences.
- [x] `HCQ-Setup-1.2.0.exe` compiles with Inno Setup 6.7, has a valid PE
  header and SHA-256 contract, and contains the same verified HCQ payload.
- [x] Legacy migration tests preserve settings and modified files while
  backing up and removing only unchanged manifest-owned plug-in files.
- [x] Migration from the actual `HCQ-1.1.2-windows.zip` preserves settings,
  Queue Library, run history, logs, and recovery data under a temporary
  OneDrive-style path containing spaces and Japanese characters.
- [x] Restart tests cover active Queue refusal, another-Houdini refusal,
  save-prompt cancellation, helper launch, installer sequencing, and HIP
  relaunch arguments.
- [x] Updater validates release manifests, detects development checkouts,
  rejects checksum mismatches, preserves user data, and rolls back failures.
- [x] Notification tests cover duration suppression reasons, live settings,
  rapid merge updates, negative-coordinate monitors, and Windows fallback.

The remaining unchecked items require an interactive Houdini UI session,
project-specific assets, performance workloads, or manual visual confirmation.

## Installation and UI

- [ ] Run the unsigned Setup EXE on a machine whose Application Control policy
  permits unsigned local installers.
- [ ] Setup new install, repair, default uninstall, and opt-in data removal.
- [ ] Setup registers Documents/OneDrive and user-profile Houdini 21.x paths.
- [x] Upgrade an actual 1.1.2 copy install and confirm all user data remains.
- [ ] Package JSON loads without startup errors in Houdini 21.0.729.
- [ ] The HCQ shelf and shelf tool appear.
- [ ] The Python Panel opens docked and as a floating pane.
- [ ] Monitor, Queues, Run, History, and Settings tabs are usable.

## Cook Monitor

- [ ] Add selected nodes and add by path.
- [ ] Enable or disable monitoring globally and per node.
- [ ] Detect generic, ROP, and TOP completion.
- [ ] Detect warnings, errors, rename, and deletion.
- [ ] Suppress playback notifications and duplicate notifications.
- [ ] Suspend during Queue Runner and refresh baselines before resuming.

## Queue management

- [ ] Create, edit, duplicate, rename, delete, group, and favorite queues.
- [ ] Add, reorder, duplicate, disable, and remove jobs.
- [ ] Preserve temporary Run List overrides without changing templates.
- [ ] Import and export schema-versioned JSON without automatic execution.
- [ ] Remap file paths and resolve missing node paths.

## Queue Runner

- [ ] File Cache foreground Save to Disk.
- [ ] ROP render, TOP cook, generic force cook, and button parameter.
- [ ] Multiple queues and jobs run in displayed order, one at a time.
- [ ] Preflight detects all required error and warning conditions.
- [ ] Stop, skip, wait-for-user, retry, pause-after-job, and cancel behavior.
- [ ] CPU setting is restored after success, warning, failure, cancellation, and exception.
- [ ] Active status updates on every state transition.
- [ ] Completion and failure are recorded in History.

## HIP, output, and recovery

- [ ] Always Save, Ask Every Time, Do Not Save, Save As, and backup.
- [ ] HIP mismatch never opens another file silently.
- [ ] Basic verification checks operation result, errors, size, and modification time.
- [ ] Interrupted runs are detected and can be inspected, retried, restarted, completed, or archived.
- [ ] Existing output Ask, Overwrite, Stop, and Skip decisions work.

## Performance

- [ ] Short, medium, long, simulation, and disk-heavy benchmarks recorded.
- [ ] Long-running foreground operations normally stay within the 1–3% overhead target.
- [ ] Monitor polls registered nodes only and does not scan the scene.

## Required specification test matrix

### Generic Operation

- [x] One generic SOP node.
- [ ] Multiple generic SOP nodes.
- [ ] Node warning.
- [ ] Node error.
- [ ] Node deletion.
- [x] Node rename.

### File Cache

- [x] Single frame.
- [ ] Frame range.
- [ ] Simulation enabled.
- [ ] Simulation disabled.
- [ ] Existing cache overwrite.
- [ ] Missing output directory.
- [ ] Read-only output directory.
- [ ] Cancelled cook.
- [ ] Failed cook.
- [ ] Consecutive connected File Cache nodes.

### ROP

- [x] Single-frame successful render.
- [ ] Frame range.
- [ ] Failed render.
- [ ] Cancelled render.

### TOP and PDG

- [x] Successful TOP cook.
- [ ] Failed TOP cook.
- [ ] Cancelled TOP cook.
- [ ] Cached work items.
- [ ] In-process work items.
- [ ] Out-of-process work items.

### Queue Management

- [ ] One queue.
- [ ] Multiple queues.
- [ ] Disabled job.
- [ ] Temporary job override.
- [x] Queue duplicate model behavior.
- [ ] JSON import through the interactive UI.
- [ ] JSON export through the interactive UI.
- [ ] Missing imported HIP.
- [x] Missing imported node resolution widget.
- [x] File-system path replacement.

### HIP Save

- [ ] Saved HIP.
- [ ] Dirty HIP.
- [ ] Unsaved untitled HIP.
- [ ] Save permission failure.
- [ ] Queue HIP mismatch.
- [ ] Backup enabled.
- [ ] Backup disabled.

### CPU

- [x] Current setting.
- [x] All threads.
- [x] One thread.
- [x] Fixed thread limit.
- [x] Reserved threads.
- [x] Leave-one-logical-thread-free UI guidance.
- [x] Reserved thread count exceeding available capacity warning.
- [x] Invalid imported thread count.
- [x] Exception during job.
- [ ] Cancellation during job in interactive Houdini.

### Recovery

- [ ] Houdini closes between jobs.
- [ ] Houdini crashes during a job.
- [ ] Status JSON is incomplete.
- [x] Output files exist while job status remains interrupted.
- [x] Retry interrupted job.
- [x] Restart full queue.
