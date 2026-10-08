// ============================================================================
// SECTION: BPF KERNEL CODE
// ============================================================================
// EVOLVE-BLOCK-START
// Probationary scan-resistant LRU on one list. New folios go to the HEAD
// (eviction end); a folio is promoted to the TAIL only after >=2 re-accesses
// whose inter-access EWMA is short, so one-shot scan pages are evicted first
// and hot GET pages are protected.
#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>

#include "cache_ext_lib.bpf.h"
#include "dir_watcher.bpf.h"

char _license[] SEC("license") = "GPL";

#define PROMOTE_MIN_COUNT 2
#define PROMOTE_MAX_INTERVAL_NS 3950000000ULL

#define SCAN_LIST_FLOOR 64

static u64 main_list;
static u64 scan_list;
static s64 scan_pages;

struct {
	__uint(type, BPF_MAP_TYPE_HASH);
	__type(key, int);
	__type(value, bool);
	__uint(max_entries, 1024);
} scan_pids SEC(".maps");

static inline bool is_scanning_tid(void) {
	int tid = (int)(bpf_get_current_pid_tgid() & 0xFFFFFFFF);
	return bpf_map_lookup_elem(&scan_pids, &tid) != NULL;
}

struct folio_metadata {
	u64 last_ts;
	u64 ewma;
	u32 count;
	u32 is_scan;
};

struct {
	__uint(type, BPF_MAP_TYPE_HASH);
	__type(key, u64);
	__type(value, struct folio_metadata);
	__uint(max_entries, 4000000);
} folio_metadata_map SEC(".maps");

__u64 g_promotions;
__u64 g_demotions;

static inline bool is_folio_relevant(struct folio *folio) {
	if (!folio || !folio->mapping || !folio->mapping->host)
		return false;
	return inode_in_watchlist(folio->mapping->host->i_ino);
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

static int evict_cb(int idx, struct cache_ext_list_node *a)
{
	if ((idx < 200) && (!folio_test_uptodate(a->folio) || !folio_test_lru(a->folio)))
		return CACHE_EXT_CONTINUE_ITER;
	return CACHE_EXT_EVICT_NODE;
}

void BPF_STRUCT_OPS(evo_policy_evict_folios, struct cache_ext_eviction_ctx *eviction_ctx,
		    struct mem_cgroup *memcg)
{
	if (scan_pages > SCAN_LIST_FLOOR)
		bpf_cache_ext_list_iterate(memcg, scan_list, evict_cb, eviction_ctx);
	if (eviction_ctx->nr_folios_to_evict < eviction_ctx->request_nr_folios_to_evict)
		bpf_cache_ext_list_iterate(memcg, main_list, evict_cb, eviction_ctx);
}

void BPF_STRUCT_OPS(evo_policy_folio_accessed, struct folio *folio) {
	if (!is_folio_relevant(folio))
		return;
	u64 key = (u64)folio;
	struct folio_metadata *m = bpf_map_lookup_elem(&folio_metadata_map, &key);
	if (!m)
		return;
	if (m->is_scan) {
		if (is_scanning_tid())
			return;
		/* GET thread touched a scan-inserted page: adopt into main list. */
		if (bpf_cache_ext_list_del(folio) == 0) {
			m->is_scan = 0;
			__sync_fetch_and_sub(&scan_pages, 1);
			bpf_cache_ext_list_add_tail(main_list, folio);
		}
		return;
	}
	u64 now = bpf_ktime_get_ns();
	u64 iv = now - m->last_ts;
	if (m->count > 1) {
		if (m->count == 2)
			m->ewma = iv;
		else
			m->ewma = (iv + 9 * m->ewma) / 10;
	}
	m->last_ts = now;
	m->count++;

	if (m->count > PROMOTE_MIN_COUNT &&
	    m->ewma > 0 && m->ewma < PROMOTE_MAX_INTERVAL_NS) {
		bpf_cache_ext_list_move(main_list, folio, true);
		__sync_fetch_and_add(&g_promotions, 1);
	} else {
		__sync_fetch_and_add(&g_demotions, 1);
	}
}

void BPF_STRUCT_OPS(evo_policy_folio_evicted, struct folio *folio) {
	u64 key = (u64)folio;
	struct folio_metadata *m = bpf_map_lookup_elem(&folio_metadata_map, &key);
	if (m && m->is_scan)
		__sync_fetch_and_sub(&scan_pages, 1);
	bpf_map_delete_elem(&folio_metadata_map, &key);
	bpf_cache_ext_list_del(folio);
}

void BPF_STRUCT_OPS(evo_policy_folio_added, struct folio *folio) {
	if (!is_folio_relevant(folio))
		return;
	u64 key = (u64)folio;
	bool scan = is_scanning_tid();
	struct folio_metadata *old = bpf_map_lookup_elem(&folio_metadata_map, &key);
	if (old) {
		/* Re-add of a folio we already track: keep list membership consistent. */
		if (old->is_scan) {
			if (bpf_cache_ext_list_add_tail(scan_list, folio))
				bpf_cache_ext_list_move(scan_list, folio, true);
		} else {
			if (bpf_cache_ext_list_add(main_list, folio))
				bpf_cache_ext_list_move(main_list, folio, false);
		}
		return;
	}
	struct folio_metadata m = {
		.last_ts = bpf_ktime_get_ns(),
		.count = 1,
		.is_scan = scan,
	};
	if (bpf_map_update_elem(&folio_metadata_map, &key, &m, BPF_ANY))
		return;
	if (scan) {
		if (bpf_cache_ext_list_add_tail(scan_list, folio) == 0)
			__sync_fetch_and_add(&scan_pages, 1);
	} else {
		bpf_cache_ext_list_add(main_list, folio);
	}
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
// EVOLVE-BLOCK-START
#include <argp.h>
#include <bpf/bpf.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include "dir_watcher.h"
#include "evo_policy.skel.h"

struct cmdline_args {
	char *watch_dir;
	uint64_t cgroup_size;
	char *cgroup_path;
};

static struct argp_option options[] = {
	{ "watch_dir", 'w', "DIR", 0, "Directory to watch" },
	{ "cgroup_size", 's', "SIZE", 0, "Size of the cgroup in bytes" },
	{ "cgroup_path", 'c', "PATH", 0, "Path to cgroup" },
	{ 0 },
};

static volatile sig_atomic_t exiting;

static void sig_handler(int signo) { exiting = 1; }

static error_t parse_opt(int key, char *arg, struct argp_state *state)
{
	struct cmdline_args *args = state->input;
	switch (key) {
	case 'w': args->watch_dir = arg; break;
	case 's':
		errno = 0;
		args->cgroup_size = strtoull(arg, NULL, 10);
		if (errno) args->cgroup_size = 0;
		break;
	case 'c': args->cgroup_path = arg; break;
	default: return ARGP_ERR_UNKNOWN;
	}
	return 0;
}

static int parse_args(int argc, char **argv, struct cmdline_args *args) {
	struct argp argp = { options, parse_opt, 0, 0 };
	argp_parse(&argp, argc, argv, 0, 0, args);

	if (!args->watch_dir) {
		fprintf(stderr, "Missing required argument: watch_dir\n");
		return 1;
	}
	if (args->cgroup_size == 0) {
		fprintf(stderr, "Invalid cgroup size\n");
		return 1;
	}
	if (!args->cgroup_path) {
		fprintf(stderr, "Missing required argument: cgroup_path\n");
		return 1;
	}
	return 0;
}

static int validate_watch_dir(const char *watch_dir, char *watch_dir_full_path) {
	if (access(watch_dir, F_OK) == -1) {
		fprintf(stderr, "Directory does not exist: %s\n", watch_dir);
		return 1;
	}
	if (realpath(watch_dir, watch_dir_full_path) == NULL) {
		perror("realpath");
		return 1;
	}
	if (strlen(watch_dir_full_path) > 128) {
		fprintf(stderr, "watch_dir path too long\n");
		return 1;
	}
	return 0;
}

int main(int argc, char **argv) {
	struct cmdline_args args = { 0 };
	struct evo_policy_bpf *skel = NULL;
	struct bpf_link *link = NULL;
	struct sigaction sa;
	char watch_dir_path[PATH_MAX];
	int cgroup_fd = -1;
	int ret = 1;

	libbpf_set_strict_mode(LIBBPF_STRICT_ALL);

	if (parse_args(argc, argv, &args))
		return 1;

	memset(&sa, 0, sizeof(sa));
	sigemptyset(&sa.sa_mask);
	sa.sa_handler = sig_handler;

	if (sigaction(SIGINT, &sa, NULL) || sigaction(SIGTERM, &sa, NULL)) {
		perror("Failed to set up signal handling");
		return 1;
	}

	if (validate_watch_dir(args.watch_dir, watch_dir_path))
		return 1;

	cgroup_fd = open(args.cgroup_path, O_RDONLY);
	if (cgroup_fd < 0) {
		perror("Failed to open cgroup path");
		return 1;
	}

	skel = evo_policy_bpf__open();
	if (!skel) {
		perror("Failed to open BPF skeleton");
		goto cleanup;
	}

	watch_dir_path_len_map(skel) = strlen(watch_dir_path);
	strcpy(watch_dir_path_map(skel), watch_dir_path);

	{
		int scan_pids_fd = bpf_obj_get("/sys/fs/bpf/cache_ext/scan_pids");
		if (scan_pids_fd >= 0) {
			if (bpf_map__reuse_fd(skel->maps.scan_pids, scan_pids_fd))
				fprintf(stderr, "Failed to reuse scan_pids map fd\n");
			else
				fprintf(stderr, "attached to harness scan_pids map\n");
			close(scan_pids_fd);
		} else {
			fprintf(stderr, "no scan_pids pin found\n");
		}
	}

	if (evo_policy_bpf__load(skel)) {
		perror("Failed to load BPF skeleton");
		goto cleanup;
	}

	if (initialize_watch_dir_map(watch_dir_path, bpf_map__fd(inode_watchlist_map(skel)), true)) {
		perror("Failed to initialize watch_dir map");
		goto cleanup;
	}

	link = bpf_map__attach_cache_ext_ops(skel->maps.evo_policy_ops, cgroup_fd);
	if (!link) {
		perror("Failed to attach cache_ext_ops to cgroup");
		goto cleanup;
	}

	printf("evo_policy (scan-resistant probationary LRU) running. Press Ctrl+C to exit...\n");
	while (!exiting)
		sleep(1);

	printf("promotions=%llu demotions=%llu\n", (unsigned long long)skel->bss->g_promotions, (unsigned long long)skel->bss->g_demotions);
	ret = 0;

cleanup:
	close(cgroup_fd);
	bpf_link__destroy(link);
	evo_policy_bpf__destroy(skel);
	return ret;
}
// EVOLVE-BLOCK-END