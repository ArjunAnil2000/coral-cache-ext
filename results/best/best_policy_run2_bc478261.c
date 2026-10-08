// ============================================================================
// SECTION: BPF KERNEL CODE
// ============================================================================
// EVOLVE-BLOCK-START
// S3-FIFO: small FIFO admission queue + main queue (CLOCK-ish, freq capped 3)
// + ghost map for re-admission straight into main.
#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>

#include "cache_ext_lib.bpf.h"
#include "dir_watcher.bpf.h"

char _license[] SEC("license") = "GPL";

#define ENOENT 2
#define BIG_SCORE 0x7fffffffffffffffLL

const volatile size_t cache_size = 0;

#define L_SMALL 0
#define L_MAIN 1
#define L_SCAN 2

struct folio_metadata {
	s64 freq;
	u8 list;
};

struct {
	__uint(type, BPF_MAP_TYPE_HASH);
	__type(key, int);
	__type(value, bool);
	__uint(max_entries, 100);
} scan_pids SEC(".maps");

static inline bool is_scanning_pid(void)
{
	int pid = (int)(bpf_get_current_pid_tgid() & 0xFFFFFFFF);
	return bpf_map_lookup_elem(&scan_pids, &pid) != NULL;
}

struct ghost_entry {
	u64 address_space;
	u64 offset;
};

struct {
	__uint(type, BPF_MAP_TYPE_HASH);
	__type(key, u64);
	__type(value, struct folio_metadata);
	__uint(max_entries, 4000000);
} folio_metadata_map SEC(".maps");

struct {
	__uint(type, BPF_MAP_TYPE_LRU_HASH);
	__type(key, struct ghost_entry);
	__type(value, u8);
	__uint(max_entries, 65536);
	__uint(map_flags, BPF_F_NO_COMMON_LRU);
} ghost_map SEC(".maps");

static u64 main_list;
static u64 small_list;
static u64 scan_list;
static s64 scan_list_size = 0;
static s64 small_list_size = 0;
static s64 main_list_size = 0;

static inline bool is_folio_relevant(struct folio *folio)
{
	if (!folio || !folio->mapping || !folio->mapping->host)
		return false;
	return inode_in_watchlist(folio->mapping->host->i_ino);
}

static inline struct folio_metadata *get_folio_metadata(struct folio *folio)
{
	u64 key = (u64)folio;
	return bpf_map_lookup_elem(&folio_metadata_map, &key);
}

static inline bool folio_in_ghost(struct folio *folio)
{
	struct ghost_entry key = {
		.address_space = (u64)folio->mapping->host,
		.offset = folio->index,
	};
	return bpf_map_delete_elem(&ghost_map, &key) != -ENOENT;
}

s32 BPF_STRUCT_OPS_SLEEPABLE(evo_policy_init, struct mem_cgroup *memcg)
{
	main_list = bpf_cache_ext_ds_registry_new_list(memcg);
	if (main_list == 0)
		return -1;
	small_list = bpf_cache_ext_ds_registry_new_list(memcg);
	if (small_list == 0)
		return -1;
	scan_list = bpf_cache_ext_ds_registry_new_list(memcg);
	if (scan_list == 0)
		return -1;
	return 0;
}

static int score_small_fn(int idx, struct cache_ext_list_node *a)
{
	if (!folio_test_uptodate(a->folio) || !folio_test_lru(a->folio))
		return CACHE_EXT_CONTINUE_ITER;
	if (folio_test_dirty(a->folio) || folio_test_writeback(a->folio))
		return CACHE_EXT_CONTINUE_ITER;

	struct folio_metadata *data = get_folio_metadata(a->folio);
	if (!data)
		return CACHE_EXT_CONTINUE_ITER;

	if (data->freq > 1) {
		data->list = L_MAIN;
		return CACHE_EXT_CONTINUE_ITER;
	}
	return CACHE_EXT_EVICT_NODE;
}

#define MAIN_ITER_FN(id)                                                          \
	static int score_main_iter_fn_##id(int idx, struct cache_ext_list_node *a) \
	{                                                                         \
		if (!folio_test_uptodate(a->folio) || !folio_test_lru(a->folio))  \
			return CACHE_EXT_CONTINUE_ITER;                           \
		if (folio_test_dirty(a->folio) || folio_test_writeback(a->folio)) \
			return CACHE_EXT_CONTINUE_ITER;                           \
		struct folio_metadata *data = get_folio_metadata(a->folio);       \
		if (!data)                                                        \
			return CACHE_EXT_CONTINUE_ITER;                           \
		s64 freq = __sync_sub_and_fetch(&data->freq, 1);                  \
		if (freq < id)                                                    \
			return CACHE_EXT_EVICT_NODE;                              \
		return CACHE_EXT_CONTINUE_ITER;                                   \
	}

MAIN_ITER_FN(0)
MAIN_ITER_FN(1)
MAIN_ITER_FN(2)
MAIN_ITER_FN(3)

static void evict_main_iter(struct cache_ext_eviction_ctx *ctx, struct mem_cgroup *memcg)
{
	struct cache_ext_iterate_opts opts = {
		.continue_list = CACHE_EXT_ITERATE_SELF,
		.continue_mode = CACHE_EXT_ITERATE_TAIL,
		.evict_list = CACHE_EXT_ITERATE_SELF,
		.evict_mode = CACHE_EXT_ITERATE_TAIL,
	};

	if (bpf_cache_ext_list_iterate_extended(memcg, main_list, score_main_iter_fn_0, &opts, ctx) < 0)
		return;
	if (ctx->nr_folios_to_evict >= ctx->request_nr_folios_to_evict)
		return;
	if (bpf_cache_ext_list_iterate_extended(memcg, main_list, score_main_iter_fn_1, &opts, ctx) < 0)
		return;
	if (ctx->nr_folios_to_evict >= ctx->request_nr_folios_to_evict)
		return;
	if (bpf_cache_ext_list_iterate_extended(memcg, main_list, score_main_iter_fn_2, &opts, ctx) < 0)
		return;
	if (ctx->nr_folios_to_evict >= ctx->request_nr_folios_to_evict)
		return;
	bpf_cache_ext_list_iterate_extended(memcg, main_list, score_main_iter_fn_3, &opts, ctx);
}

static int score_scan_fn(int idx, struct cache_ext_list_node *a)
{
	if (!folio_test_uptodate(a->folio) || !folio_test_lru(a->folio))
		return CACHE_EXT_CONTINUE_ITER;
	if (folio_test_dirty(a->folio) || folio_test_writeback(a->folio))
		return CACHE_EXT_CONTINUE_ITER;
	struct folio_metadata *data = get_folio_metadata(a->folio);
	if (!data)
		return CACHE_EXT_CONTINUE_ITER;
	if (data->freq > 0) {
		data->list = L_MAIN;
		return CACHE_EXT_CONTINUE_ITER;
	}
	return CACHE_EXT_EVICT_NODE;
}

static void evict_scan(struct cache_ext_eviction_ctx *ctx, struct mem_cgroup *memcg)
{
	struct cache_ext_iterate_opts opts = {
		.continue_list = main_list,
		.continue_mode = CACHE_EXT_ITERATE_TAIL,
		.evict_list = CACHE_EXT_ITERATE_SELF,
		.evict_mode = CACHE_EXT_ITERATE_TAIL,
	};
	if (bpf_cache_ext_list_iterate_extended(memcg, scan_list, score_scan_fn, &opts, ctx) < 0)
		return;
	if (__sync_fetch_and_sub(&scan_list_size, opts.nr_folios_continue) < 0)
		scan_list_size = 0;
	__sync_fetch_and_add(&main_list_size, opts.nr_folios_continue);
}

static void evict_small(struct cache_ext_eviction_ctx *ctx, struct mem_cgroup *memcg)
{
	struct cache_ext_iterate_opts opts = {
		.continue_list = main_list,
		.continue_mode = CACHE_EXT_ITERATE_TAIL,
		.evict_list = CACHE_EXT_ITERATE_SELF,
		.evict_mode = CACHE_EXT_ITERATE_TAIL,
	};

	if (bpf_cache_ext_list_iterate_extended(memcg, small_list, score_small_fn, &opts, ctx) < 0)
		return;

	if (__sync_fetch_and_sub(&small_list_size, opts.nr_folios_continue) < 0)
		small_list_size = 0;
	if (__sync_fetch_and_add(&main_list_size, opts.nr_folios_continue) < 0)
		main_list_size = opts.nr_folios_continue;
}

void BPF_STRUCT_OPS(evo_policy_evict_folios, struct cache_ext_eviction_ctx *eviction_ctx,
		    struct mem_cgroup *memcg)
{
	if (scan_list_size > 256) {
		evict_scan(eviction_ctx, memcg);
		if (eviction_ctx->nr_folios_to_evict >= eviction_ctx->request_nr_folios_to_evict)
			return;
	}
	if (small_list_size >= cache_size / 10 || main_list_size <= 2 * small_list_size)
		evict_small(eviction_ctx, memcg);
	else
		evict_main_iter(eviction_ctx, memcg);
}

void BPF_STRUCT_OPS(evo_policy_folio_accessed, struct folio *folio)
{
	if (!is_folio_relevant(folio))
		return;
	struct folio_metadata *data = get_folio_metadata(folio);
	if (!data)
		return;
	if (data->list == L_SCAN && is_scanning_pid())
		return;
	if (__sync_add_and_fetch(&data->freq, 1) > 3)
		data->freq = 3;
}

void BPF_STRUCT_OPS(evo_policy_folio_evicted, struct folio *folio)
{
	u64 key = (u64)folio;
	struct folio_metadata *data = get_folio_metadata(folio);
	if (!data)
		return;

	u8 ghost_val = 0;
	struct ghost_entry ghost_key = {
		.address_space = (u64)folio->mapping->host,
		.offset = folio->index,
	};
	bpf_map_update_elem(&ghost_map, &ghost_key, &ghost_val, BPF_ANY);

	if (data->list == L_MAIN)
		__sync_fetch_and_sub(&main_list_size, 1);
	else if (data->list == L_SCAN)
		__sync_fetch_and_sub(&scan_list_size, 1);
	else
		__sync_fetch_and_sub(&small_list_size, 1);

	bpf_map_delete_elem(&folio_metadata_map, &key);
}

void BPF_STRUCT_OPS(evo_policy_folio_added, struct folio *folio)
{
	if (!is_folio_relevant(folio))
		return;

	u64 key = (u64)folio;
	struct folio_metadata new_meta = { .freq = 0 };
	u64 list_to_add;
	if (is_scanning_pid()) {
		list_to_add = scan_list;
		new_meta.list = L_SCAN;
	} else if (folio_in_ghost(folio)) {
		list_to_add = main_list;
		new_meta.list = L_MAIN;
	} else {
		list_to_add = small_list;
		new_meta.list = L_SMALL;
	}

	if (bpf_cache_ext_list_add_tail(list_to_add, folio))
		return;

	if (bpf_map_update_elem(&folio_metadata_map, &key, &new_meta, BPF_ANY)) {
		bpf_cache_ext_list_del(folio);
		return;
	}
	if (new_meta.list == L_MAIN)
		__sync_fetch_and_add(&main_list_size, 1);
	else if (new_meta.list == L_SCAN)
		__sync_fetch_and_add(&scan_list_size, 1);
	else
		__sync_fetch_and_add(&small_list_size, 1);
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

static const uint64_t page_size = 4096;
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

int main(int argc, char **argv) {
	struct cmdline_args args = { 0 };
	struct evo_policy_bpf *skel = NULL;
	struct bpf_link *link = NULL;
	struct sigaction sa;
	char watch_dir_path[PATH_MAX];
	int cgroup_fd = -1;
	int ret = 1;

	libbpf_set_strict_mode(LIBBPF_STRICT_ALL);

	struct argp argp = { options, parse_opt, 0, 0 };
	argp_parse(&argp, argc, argv, 0, 0, &args);
	if (!args.watch_dir || !args.cgroup_path || args.cgroup_size == 0) {
		fprintf(stderr, "Missing required arguments\n");
		return 1;
	}

	memset(&sa, 0, sizeof(sa));
	sigemptyset(&sa.sa_mask);
	sa.sa_handler = sig_handler;
	if (sigaction(SIGINT, &sa, NULL) || sigaction(SIGTERM, &sa, NULL)) {
		perror("Failed to set up signal handling");
		return 1;
	}

	if (realpath(args.watch_dir, watch_dir_path) == NULL) {
		perror("realpath");
		return 1;
	}
	if (strlen(watch_dir_path) > 128) {
		fprintf(stderr, "watch_dir path too long\n");
		return 1;
	}

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

	skel->rodata->cache_size = args.cgroup_size / page_size;
	fprintf(stderr, "Cache size: %lu pages\n", skel->rodata->cache_size);
	if (bpf_map__set_max_entries(skel->maps.ghost_map, skel->rodata->cache_size)) {
		perror("Failed to resize ghost_map");
		goto cleanup;
	}

	watch_dir_path_len_map(skel) = strlen(watch_dir_path);
	strcpy(watch_dir_path_map(skel), watch_dir_path);

	if (evo_policy_bpf__load(skel)) {
		perror("Failed to load BPF skeleton");
		goto cleanup;
	}

	if (initialize_watch_dir_map(watch_dir_path, bpf_map__fd(inode_watchlist_map(skel)), true)) {
		perror("Failed to initialize watch_dir map");
		goto cleanup;
	}

	mkdir("/sys/fs/bpf/cache_ext", 0755);
	unlink("/sys/fs/bpf/cache_ext/scan_pids");
	if (bpf_map__pin(skel->maps.scan_pids, "/sys/fs/bpf/cache_ext/scan_pids"))
		fprintf(stderr, "warning: failed to pin scan_pids\n");

	link = bpf_map__attach_cache_ext_ops(skel->maps.evo_policy_ops, cgroup_fd);
	if (link == NULL) {
		perror("Failed to attach cache_ext_ops to cgroup");
		goto cleanup;
	}

	if (evo_policy_bpf__attach(skel)) {
		perror("Failed to attach BPF skeleton");
		goto cleanup;
	}

	printf("evo_policy running. Press Ctrl+C to exit...\n");
	fflush(stdout);
	while (!exiting)
		sleep(1);
	ret = 0;

cleanup:
	if (skel)
		bpf_map__unpin(skel->maps.scan_pids, "/sys/fs/bpf/cache_ext/scan_pids");
	close(cgroup_fd);
	bpf_link__destroy(link);
	evo_policy_bpf__destroy(skel);
	return ret;
}
// EVOLVE-BLOCK-END
