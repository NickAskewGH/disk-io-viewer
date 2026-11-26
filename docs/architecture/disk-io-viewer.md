# Live disk I/O viewer

**Proposed architecture.** A local Linux desktop window shows one scrolling graph per configured storage device. Each graph overlays read and write throughput on the same positive vertical axis. All graphs show the same time window, so a burst of reads on one drive can be lined up with writes on another.

## Reading the graphs

Stack compact panels in configuration order, with vertical scrolling when the window fills. Put the device label and kernel name above each plot, alongside the latest values, for example **Scratch NVMe (nvme0n1) · Read 820 MiB/s · Write 36 MiB/s**.

- Follow the reference’s light background, fine gray grid and unfilled traces. Use solid two-pixel strokes, blue for reads and red for writes. Repeat the swatches beside the labeled values.
- Time runs left to right, with the newest sample at the right edge. Show the last 60 seconds by default. Join the samples with smooth, bounded cubic curves that pass through every measured peak. Scroll the timeline between samples. Leave a visible break wherever measurements are missing.
- Start each vertical axis at zero. Choose a ceiling that covers the larger of the two visible peaks, rounded up to a readable tick interval. Expand immediately on a burst and shrink only as peaks leave the window. Keep a minimum ceiling of 1 MiB/s so an idle graph has a valid scale.
- Scale each device independently so HDD activity stays legible beside NVMe traffic. Equal heights across panels can represent different speeds. Label each axis in MiB/s or GiB/s and keep the current rates visible for absolute comparisons.

## Runtime design

Use Python 3.12 and Tkinter Canvas. A native window gives the thin linework in the reference and can run in one process without a web service. The host needs a graphical session and a Python installation with Tk support. Keep the existing uv project and Ruff checks.

| Component | Responsibility |
| --- | --- |
| Configuration loader | Read local TOML with `tomllib`, validate entries and keep their display order. |
| Linux device reader | Resolve each configured path to a block device. Read its cumulative sector counts and record its identity and monotonic timestamp. |
| Rate calculation and history | Convert consecutive observations into read/write rates. Keep a time-bounded deque per configured device, including gap markers. |
| Window and chart panels | Use one Tk timer for all panels. Collect observations on sampling deadlines and move the plotted curves between readings at up to 30 frames per second. All panels use one shared time origin. Redraw from history on resize. |

For a handful of local drives, the timer can read the small sysfs statistics files directly on the UI thread. Schedule against monotonic deadlines and skip missed ticks. If profiling on the target system shows that collection delays window interaction, the device reader can move to a worker while Tk retains ownership of drawing.

## Selecting devices

Read `disk-io.toml` from the working directory at startup. A `--config PATH` argument selects another file. Restart the viewer to apply edits. The following example uses illustrative paths.

```toml
sample_interval_seconds = 1
history_seconds = 60

[[devices]]
path = "/dev/nvme0n1"
label = "Scratch NVMe"

[[devices]]
path = "/dev/disk/by-id/ata-EXAMPLE_SSD_SERIAL"
label = "System SSD"

[[devices]]
path = "/dev/disk/by-id/ata-EXAMPLE_HDD_SERIAL"
label = "Archive HDD"
```

The timing keys are optional and default to the values shown. Require a positive, finite sampling interval, a history window at least two intervals long and at least one device. Each entry needs an absolute device path. Its label defaults to the path’s basename. Report configuration errors with the offending key or entry at startup.

Use whole-disk paths for drives and namespace paths for NVMe devices. Prefer a whole-device link under `/dev/disk/by-id/` when a panel should follow a particular physical drive across reboots. A kernel-name path such as `/dev/sdb` follows whichever device currently owns that name. Resolve aliases to major/minor numbers and report duplicate selections. A missing drive keeps its place in the window while the viewer retries.

## Measuring throughput

Resolve the configured device node with `stat()` and use its major/minor numbers to locate `/sys/dev/block/<major>:<minor>/stat`. Read the statistics file once per device per sampling interval. Fields 3 and 7, counted from one, hold cumulative sectors read and written. Both count completed transfers in units of 512 bytes, including on drives with 4 KiB physical sectors. This measures traffic at the block device across all processes. Reads served entirely from the filesystem cache generate no device read. [Linux block statistics](https://docs.kernel.org/block/stat.html)

Store rates internally in bytes per second. For consecutive observations of the same device, use the actual elapsed monotonic time for both directions.

```text
read_Bps  = (current_read_sectors  - previous_read_sectors)  × 512 / elapsed_seconds
write_Bps = (current_write_sectors - previous_write_sectors) × 512 / elapsed_seconds
```

Divide by 1,048,576 for MiB/s. For example, an increase of 4,096 read sectors and 1,024 written sectors over two seconds produces **1 MiB/s read** and **0.25 MiB/s write**. A valid interval with unchanged counters produces zero.

The first observation establishes a baseline. If a read fails, a device disappears or changes identity, either counter decreases, or elapsed time falls outside `(0, 2 × sample_interval]`, break both traces. Drop the old baseline and use the next valid observation as the new baseline, including the current observation if valid. Show a short panel status such as **Unavailable**, **Permission denied** or **Collecting** until two consecutive valid observations yield a rate. Continue updating healthy panels and expire old points even when a device stays offline. [Linux I/O counter resets](https://docs.kernel.org/admin-guide/iostats.html)

## Verification before release

- Feed the rate calculator the two-second example above, an idle interval and a delayed tick. Check both rates against the measured interval.
- Simulate a disappearing disk, a counter reset and a replacement at the same path. Verify a gap, a fresh baseline and uninterrupted updates for the other disks.
- Load the example configuration with fixture device paths. Check panel order, a missing device, duplicate aliases and an invalid interval.
- Run on a Linux desktop during a file copy between two monitored drives. Compare the source’s read rate and destination’s write rate with independently sampled disk counters over matching intervals. Check that a short SSD burst remains visible while the HDD panel retains its own labeled scale.
