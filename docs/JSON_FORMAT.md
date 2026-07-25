# HCQ JSON Format

HCQ 1.0 writes human-readable UTF-8 JSON. Importing JSON never starts a run.

## Common envelope

Every portable document contains:

```json
{
  "schema": "hcq.queue-template",
  "schema_version": 1,
  "hcq_version": "1.0.0"
}
```

Supported schemas are:

- `hcq.queue-template`
- `hcq.run-list`
- `hcq.run-status`
- `hcq.run-result`

HCQ rejects unknown schemas, unsupported schema versions, invalid node paths, and
actions outside this allowlist:

- `auto_detect`
- `filecache_save_to_disk`
- `rop_render`
- `top_cook`
- `force_cook`
- `press_button`

No JSON field is evaluated as Python.

## Queue template example

```json
{
  "schema": "hcq.queue-template",
  "schema_version": 1,
  "hcq_version": "1.0.0",
  "houdini_min_version": "21.0",
  "created_with_houdini": "21.0.729",
  "queues": [
    {
      "id": "queue-example",
      "name": "Daily Caches",
      "description": "Runs simulation and export caches.",
      "group": "Project/Caches",
      "favorite": true,
      "hip_file": "D:/Project/scene.hip",
      "cpu": {
        "mode": "current"
      },
      "jobs": [
        {
          "id": "job-example",
          "order": 1,
          "enabled": true,
          "display_name": "Simulation Cache",
          "node_path": "/obj/geo1/filecache1",
          "node_type": "Sop/filecache::2.0",
          "action": "filecache_save_to_disk",
          "frame_range": {
            "mode": "custom",
            "start": 1,
            "end": 240,
            "step": 1
          },
          "cpu": {
            "mode": "inherit"
          },
          "on_error": "stop_queue",
          "retry_count": 0,
          "verification": "basic",
          "notify_on_complete": true,
          "notify_on_failure": true,
          "expected_outputs": [
            "$HIP/cache/simulation.$F4.bgeo.sc"
          ]
        }
      ]
    }
  ]
}
```

`node_path` is a Houdini network path and is never changed by file-system path
remapping. Missing nodes must be resolved explicitly in the import preview.
