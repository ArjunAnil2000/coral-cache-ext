// ============================================================================
// SECTION: BPF KERNEL CODE
// ============================================================================
// EVOLVE-BLOCK-START
// Scan-aware two-list policy. Scan pages are identified by the harness scan_pids map OR
// by a per-thread sequential-add detector (the scan thread adds folios at consecutive
// indices of one file; GET threads add random ones). Scan pages go to scan_list and are
// evicted first (FIFO); a scan page touched by a non-scan thread is promoted to main.
// main_list is LRU (move to tail on access, evict from head).
#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>

#include "cache_ext_lib.bpf.h"
#include "dir_watcher.bpf.h"

char _license[] SEC("license") = "GPL";

#define SEQ_SCORE_MAX 64
#define SEQ_SCORE_SCAN 16
#define SCAN_MIN_PAGES 32

struct {
	__uint(type, BPF_MAP_TYPE_HASH);
	__type(key, int);
	__type(value, bool);
	__uint(max_entries, 100);
} scan_pids SEC(".maps");

struct thread_state {
	u64 host;
	u64 next_index;
	s32 score;
};

struct {
	__uint(type, BPF_MAP_TYPE_LRU_HASH);
	__type(key, u32);
	__type(value, struct thread_state);
	__uint(max_entries, 1024);
} thread_map SEC(".maps");

// value: 1 = on scan_list, 0 = on main_list
struct {
	__uint(type, BPF_MAP_TYPE_HASH);
	__type(key, u64);
	__type(value, u8);
	__uint(max_entries, 4000000);
} folio_map SEC(".maps");

static u64 main_list;
static u64 scan_list;
static s64 scan_pages = 0;

static inline bool is_folio_relevant(struct folio *folio)
{
	if (!folio || !folio->mapping || !folio->mapping->host)
		return false;
	return inode_in_watchlist(folio->mapping->host->i_ino);
}

static inline bool pid_is_scanner(u32 tid)
{
	if (bpf_map_lookup_elem(&scan_pids, &tid))
		return true;
	struct thread_state *ts = bpf_map_lookup_elem(&thread_map, &tid);
	return ts && ts->score >= SEQ_SCORE_SCAN;
}

// Called on folio add: update per-thread sequentiality and report scan-ness.
static inline bool classify_add(struct folio *folio)
{
	u32 tid = (u32)bpf_get_current_pid_tgid();
	bool pinned = bpf_map_lookup_elem(&scan_pids, &tid) != NULL;
	u64 host = (u64)folio->mapping->host;
	u64 idx = folio->index;

	struct thread_state *ts = bpf_map_lookup_elem(&thread_map, &tid);
	if (!ts) {
		struct thread_state init = { .host = host, .next_index = idx + 1, .score = 0 };
		bpf_map_update_elem(&thread_map, &tid, &init, BPF_ANY);
		return pinned;
	}
	if (ts->host == host && (idx == ts->next_index || idx == ts->next_index + 1)) {
		if (ts->score < SEQ_SCORE_MAX)
			ts->score++;
	} else {
		ts->score -= 4;
		if (ts->score < 0)
			ts->score = 0;
	}
	ts->host = host;
	ts->next_index = idx + 1;
	return pinned || ts->score >= SEQ_SCORE_SCAN;
}

s32 BPF_STRUCT_OPS_SLEEPABLE(evo_policy_init, struct mem_cgroup *memcg)
{
	main_list = bpf_cache_ext_ds_registry_new_list(memcg);
	if (main_list == 0)
		return -1;
	scan_list = bpf_cache_ext_ds_registry_new_list(memcg);
	if (scan_list == 0)
		return -1;
	return 0;
}

void BPF_STRUCT_OPS(evo_policy_folio_added, struct folio *folio)
{
	if (!is_folio_relevant(folio))
		return;
	u8 is_scan = classify_add(folio) ? 1 : 0;
	u64 list = is_scan ? scan_list : main_list;
	if (bpf_cache_ext_list_add_tail(list, folio))
		return;
	u64 key = (u64)folio;
	bpf_map_update_elem(&folio_map, &key, &is_scan, BPF_ANY);
	if (is_scan)
		__sync_fetch_and_add(&scan_pages, 1);
}

void BPF_STRUCT_OPS(evo_policy_folio_accessed, struct folio *folio)
{
	if (!is_folio_relevant(folio))
		return;
	u64 key = (u64)folio;
	u8 *where = bpf_map_lookup_elem(&folio_map, &key);
	if (!where)
		return;
	u32 tid = (u32)bpf_get_current_pid_tgid();
	if (pid_is_scanner(tid))
		return;
	if (*where) {
		*where = 0;
		__sync_fetch_and_sub(&scan_pages, 1);
	}
	bpf_cache_ext_list_move(main_list, folio, true);
}

void BPF_STRUCT_OPS(evo_policy_folio_evicted, struct folio *folio)
{
	bpf_cache_ext_list_del(folio);
	u64 key = (u64)folio;
	u8 *where = bpf_map_lookup_elem(&folio_map, &key);
	if (where) {
		if (*where)
			__sync_fetch_and_sub(&scan_pages, 1);
		bpf_map_delete_elem(&folio_map, &key);
	}
}

static int evict_iter(int idx, struct cache_ext_list_node *node)
{
	if (idx < 200 && (!folio_test_uptodate(node->folio) || !folio_test_lru(node->folio)))
		return CACHE_EXT_CONTINUE_ITER;
	return CACHE_EXT_EVICT_NODE;
}

void BPF_STRUCT_OPS(evo_policy_evict_folios, struct cache_ext_eviction_ctx *eviction_ctx,
		    struct mem_cgroup *memcg)
{
	if (scan_pages > SCAN_MIN_PAGES) {
		bpf_cache_ext_list_iterate(memcg, scan_list, evict_iter, eviction_ctx);
		if (eviction_ctx->nr_folios_to_evict >= eviction_ctx->request_nr_folios_to_evict)
			return;
	}
	bpf_cache_ext_list_iterate(memcg, main_list, evict_iter, eviction_ctx);
}

SEC(".struct_ops.link")
struct cache_ext_ops evo_policy_ops = {
	.init = (void *)evo_policy_init,
	.evict_folios = (void *)evo_policy_evict_folios,
	.folio_accessed = (void *)evo_policy_folio_accessed,
	.folio_evicted = (void *)evo_policy_folio_evicted,
	.folio_added = (void *)evo_policy_folio_added,
};
// EVOLVE-BLOCK-END

// ============================================================================
// SECTION: USERSPACE LOADER
// ============================================================================
// Loader for the GET-SCAN policy: parses -w/-s/-c like every policy in this repo,
// attaches the struct_ops to the cgroup and waits for SIGINT/SIGTERM.
// EVOLVE-BLOCK-START
#include <argp.h>
#include <errno.h>
#include <signal.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <bpf/bpf.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include "evo_policy.skel.h"
#include "dir_watcher.h"

char *USAGE = "Usage: ./evo_policy --watch_dir <dir> --cgroup_path <path>\n";
struct cmdline_args {
	char *watch_dir;
	char *cgroup_path;
	uint64_t cgroup_size;	/* accepted for harness compatibility */
};

static struct argp_option options[] = { { "watch_dir", 'w', "DIR", 0, "Directory to watch" },
					{ "cgroup_path", 'c', "PATH", 0,
					  "Path to cgroup (e.g., /sys/fs/cgroup/cache_ext_test)" },
					{ "cgroup_size", 's', "SIZE", 0,
	  "Size of the cgroup in bytes (accepted for harness compatibility)" },
					{ 0 } };

static error_t parse_opt(int key, char *arg, struct argp_state *state)
{
	struct cmdline_args *args = state->input;
	switch (key) {
	case 'w':
		args->watch_dir = arg;
		break;
	case 'c':
		args->cgroup_path = arg;
		break;
	case 's':
		errno = 0;
		args->cgroup_size = strtoull(arg, NULL, 10);
		if (errno)
			args->cgroup_size = 0;
		break;
	default:
		return ARGP_ERR_UNKNOWN;
	}
	return 0;
}

static volatile sig_atomic_t exiting;

static void sig_handler(int signo)
{
	exiting = 1;
}

int main(int argc, char **argv)
{
	int ret = 1;
	struct evo_policy_bpf *skel = NULL;
	struct bpf_link *link = NULL;
	int cgroup_fd = -1;
	libbpf_set_strict_mode(LIBBPF_STRICT_ALL);

	{
		struct sigaction sa;
		memset(&sa, 0, sizeof(sa));
		sigemptyset(&sa.sa_mask);
		sa.sa_handler = sig_handler;
		if (sigaction(SIGINT, &sa, NULL) || sigaction(SIGTERM, &sa, NULL)) {
			perror("Failed to set up signal handling");
			return 1;
		}
	}

	// Parse command line arguments
	struct cmdline_args args = { 0 };
	struct argp argp = { options, parse_opt, 0, 0 };
	argp_parse(&argp, argc, argv, 0, 0, &args);

	// Validate arguments
	if (args.watch_dir == NULL) {
		fprintf(stderr, "Missing required argument: watch_dir\n");
		return 1;
	}

	if (args.cgroup_path == NULL) {
		fprintf(stderr, "Missing required argument: cgroup_path\n");
		return 1;
	}

	// Does watch_dir exist?
	if (access(args.watch_dir, F_OK) == -1) {
		fprintf(stderr, "Directory does not exist: %s\n",
			args.watch_dir);
		return 1;
	}

	// Get full path of watch_dir
	char watch_dir_full_path[PATH_MAX];
	if (realpath(args.watch_dir, watch_dir_full_path) == NULL) {
		perror("realpath");
		return 1;
	}

	// TODO: Enable longer length
	if (strlen(watch_dir_full_path) > 128) {
		fprintf(stderr, "watch_dir path too long\n");
		return 1;
	}

	cgroup_fd = open(args.cgroup_path, O_RDONLY);
	if (cgroup_fd < 0) {
		perror("Failed to open cgroup path");
		return 1;
	}

	// Open skel
	skel = evo_policy_bpf__open();
	if (skel == NULL) {
		perror("Failed to open BPF skeleton");
		goto cleanup;
	}

	// Set watch_dir
	skel->rodata->watch_dir_path_len = strlen(watch_dir_full_path);
	strcpy(skel->rodata->watch_dir_path, watch_dir_full_path);

	// The benchmark harness creates and pins the scan_pids map before any policy loads
	// (and removes the pin afterwards). Reuse it; do not pin our own.
	{
		int scan_pids_fd = bpf_obj_get("/sys/fs/bpf/cache_ext/scan_pids");
		if (scan_pids_fd >= 0) {
			if (bpf_map__reuse_fd(skel->maps.scan_pids, scan_pids_fd))
				fprintf(stderr, "Failed to reuse scan_pids map fd\n");
			close(scan_pids_fd);
		} else {
			fprintf(stderr, "no scan_pids pin found\n");
		}
	}

	// Load programs
	ret = evo_policy_bpf__load(skel);
	if (ret) {
		perror("Failed to load BPF skeleton");
		goto cleanup;
	}

	// Initialize inode_watchlist map
	ret = initialize_watch_dir_map(args.watch_dir,
				       bpf_map__fd(skel->maps.inode_watchlist), false);

	// Attach cache_ext_ops to the specific cgroup
	link = bpf_map__attach_cache_ext_ops(skel->maps.evo_policy_ops, cgroup_fd);
	if (link == NULL) {
		perror("Failed to attach cache_ext_ops to cgroup");
		goto cleanup;
	}

	// Attach probes
	ret = evo_policy_bpf__attach(skel);
	if (ret) {
		perror("Failed to attach BPF programs");
		goto cleanup;
	}

	printf("evo_policy (GET-SCAN) running. Press Ctrl+C to exit...\n");
	fflush(stdout);
	while (!exiting)
		sleep(1);
	ret = 0;

cleanup:
	close(cgroup_fd);
	bpf_link__destroy(link);
	evo_policy_bpf__destroy(skel);
	return ret;
}
// EVOLVE-BLOCK-END
