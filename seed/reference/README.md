Reference material (read-only; NOT graded).

## Seeds: complete example policies, one file each
Every `<name>.c` here is a complete, working policy in exactly the same two-section
format as your `noop.c` (`SECTION: BPF KERNEL CODE` + `SECTION: USERSPACE LOADER`, each in
`EVOLVE-BLOCK` markers). A short description of the policy is at the top of each file.
Any of them can be copied over `noop.c` and submitted unchanged.

| file | policy |
|---|---|
| `fifo.c` | FIFO, accesses ignored |
| `mru.c` | MRU: evicts the most recently used first |
| `s3fifo.c` | S3-FIFO: small FIFO + main CLOCK queue + ghost map |
| `sampling.c` | Sampled LFU (+ LevelDB index-block bonus) |
| `get_scan.c` | GET-SCAN policy: scan-thread list + general list, sampled LFU (uses the harness's `scan_pids` map) |
| `mglru.c` | MGLRU: multi-generational LRU port |
| `lhd.c` | LHD: least hit density |

## cache_ext API headers
`cache_ext_lib.bpf.h` (list/sampling helpers and eviction types), `dir_watcher.bpf.h` and
`dir_watcher.h` (the watch-directory support every policy includes).
