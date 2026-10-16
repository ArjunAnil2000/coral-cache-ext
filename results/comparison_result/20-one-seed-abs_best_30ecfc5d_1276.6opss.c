// ============================================================================
// SECTION: BPF KERNEL CODE
// ============================================================================
// EVOLVE-BLOCK-START
// S3-FIFO: a small FIFO (~10% of the cache) admits new folios; a folio re-accessed while in
// the small queue is promoted to the main queue, otherwise evicted. The main queue is
// CLOCK-like with a frequency counter capped at 3. A ghost map remembers recently evicted
// folios so a quick re-reference is admitted straight into main.
#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>

#include "cache_ext_lib.bpf.h"
#include "dir_watcher.bpf.h"

char _license[] SEC("license") = "GPL";

#define ENOENT		2  /* include/uapi/asm-generic/errno-base.h */
#define INT64_MAX	(9223372036854775807LL)

// Set from userspace. In terms of number of pages.
// TODO: change

//#define CACHE_SIZE (((1ull << 30) * 2) / 4096)
#define CACHE_SIZE (((1ull << 20) * 200) / 4096)
const volatile size_t cache_size = 0;

struct folio_metadata {
	s64 freq;
	bool in_main;
	bool scan;
};

/* Per-thread sequential-insertion tracker used to detect the scan thread. */
struct seq_key {
	u64 ino;
	u32 tid;
	u32 pad;
};

struct seq_state {
	u64 last_idx;
	u32 run;
};

struct {
	__uint(type, BPF_MAP_TYPE_LRU_HASH);
	__type(key, struct seq_key);
	__type(value, struct seq_state);
	__uint(max_entries, 16384);
} seq_map SEC(".maps");

/* A folio whose insertion extends a per-thread sequential run of >= SEQ_RUN is a scan folio. */
#define SEQ_RUN 3
#define SEQ_GAP 64
/* Keep at least this many scan folios resident so un-consumed readahead isn't thrown away. */
#define SCAN_MIN 512

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
	__type(value, u32);
	//__uint(max_entries, CACHE_SIZE); // TODO: change
	__uint(map_flags, BPF_F_NO_COMMON_LRU);  // Per-CPU LRU eviction logic
} ghost_map SEC(".maps");

static u64 main_list;
static u64 small_list;
static u64 scan_list;
static s64 scan_list_size = 0;

/*
 * This is an approximate value based on what we choose to evict, not what is
 * actually evicted.
 */
static s64 small_list_size = 0;
static s64 main_list_size = 0;

static inline bool is_folio_relevant(struct folio *folio) {
	if (!folio || !folio->mapping || !folio->mapping->host)
		return false;

	return inode_in_watchlist(folio->mapping->host->i_ino);
}

static inline struct folio_metadata *get_folio_metadata(struct folio *folio) {
	u64 key = (u64)folio;
	return bpf_map_lookup_elem(&folio_metadata_map, &key);
}

/*
 * Check if a folio is in the ghost map and delete the ghost entry.
 * We only check if an element is in the ghost map on inserting into the cache.
 * Relies on bpf_map_delete_elem() returning -ENOENT if the element is not found.
 */
static inline u32 folio_in_ghost(struct folio *folio) {
	struct ghost_entry key = {
		.address_space = (u64)folio->mapping->host,
		.offset = folio->index,
	};
	u32 *cnt = bpf_map_lookup_elem(&ghost_map, &key);
	if (!cnt)
		return 0;
	u32 c = *cnt;
	bpf_map_delete_elem(&ghost_map, &key);
	return c ? c : 1;
}

s32 BPF_STRUCT_OPS_SLEEPABLE(evo_policy_init, struct mem_cgroup *memcg)
{
	main_list = bpf_cache_ext_ds_registry_new_list(memcg);
	if (main_list == 0) {
		bpf_printk("cache_ext: init: Failed to create main_list\n");
		return -1;
	}
	bpf_printk("cache_ext: Created main_list: %llu\n", main_list);

	small_list = bpf_cache_ext_ds_registry_new_list(memcg);
	if (small_list == 0) {
		bpf_printk("cache_ext: init: Failed to create small_list\n");
		return -1;
	}
	bpf_printk("cache_ext: Created small_list: %llu\n", small_list);

	scan_list = bpf_cache_ext_ds_registry_new_list(memcg);
	if (scan_list == 0) {
		bpf_printk("cache_ext: init: Failed to create scan_list\n");
		return -1;
	}

	return 0;
}

static s64 bpf_s3fifo_score_main_fn(struct cache_ext_list_node *a) {
	if (!folio_test_uptodate(a->folio) || !folio_test_lru(a->folio))
		return INT64_MAX;

	if (folio_test_dirty(a->folio) || folio_test_writeback(a->folio))
		return INT64_MAX;

	struct folio_metadata *data = get_folio_metadata(a->folio);
	if (!data) {
		bpf_printk("cache_ext: score_fn: Failed to get metadata\n");
		return INT64_MAX;
	}

	/* LFU with history: evict the sampled folio with the lowest long-term count. */
	return data->freq;
}

static int bpf_s3fifo_score_small_fn(int idx, struct cache_ext_list_node *a)
{
	if (!folio_test_uptodate(a->folio) || !folio_test_lru(a->folio))
		return CACHE_EXT_CONTINUE_ITER;

	if (folio_test_dirty(a->folio) || folio_test_writeback(a->folio))
		return CACHE_EXT_CONTINUE_ITER;

	struct folio_metadata *data = get_folio_metadata(a->folio);
	if (!data) {
		bpf_printk("cache_ext: score_fn: Failed to get metadata\n");
		return CACHE_EXT_CONTINUE_ITER;
	}

	// Move to main list if freq > 1
	if (data->freq > 1) {
		data->in_main = true;
		return CACHE_EXT_CONTINUE_ITER;
	}

	// Else, evict
	return CACHE_EXT_EVICT_NODE;
}

static void evict_main(struct cache_ext_eviction_ctx *eviction_ctx, struct mem_cgroup *memcg)
{
	/*
	 * Iterate from head. If freq > 0, move to tail, freq--.
	 * Otherwise, evict. (When evicting, move to tail in the meantime).
	 */

	struct sampling_options opts = {
		.sample_size = 32,
	};

	if (bpf_cache_ext_list_sample(memcg, main_list, bpf_s3fifo_score_main_fn, &opts,
				      eviction_ctx)) {
		bpf_printk("cache_ext: evict: Failed to sample main_list\n");
		return;
	}

	// if (__sync_sub_and_fetch(&main_list_size, eviction_ctx->nr_folios_to_evict) < 0)
	// 	main_list_size = 0;
}

#define MAIN_ITER_FN(id) 								\
static int bpf_s3fifo_score_main_iter_fn_##id(int idx, struct cache_ext_list_node *a) 	\
{ 											\
	if (!folio_test_uptodate(a->folio) || !folio_test_lru(a->folio)) 		\
		return CACHE_EXT_CONTINUE_ITER; 					\
 											\
	if (folio_test_dirty(a->folio) || folio_test_writeback(a->folio)) 		\
		return CACHE_EXT_CONTINUE_ITER; 					\
 											\
	struct folio_metadata *data = get_folio_metadata(a->folio); 			\
	if (!data) { 									\
		bpf_printk("cache_ext: score_fn: Failed to get metadata\n"); 		\
		return CACHE_EXT_CONTINUE_ITER; 					\
	} 										\
 											\
	s64 freq = __sync_sub_and_fetch(&data->freq, 1); 				\
	if (freq < id) { 								\
		/*data->freq = 0;*/ 							\
		return CACHE_EXT_EVICT_NODE; 						\
	} 										\
 											\
	return CACHE_EXT_CONTINUE_ITER; 						\
}

MAIN_ITER_FN(0)
MAIN_ITER_FN(1)
MAIN_ITER_FN(2)
MAIN_ITER_FN(3)

static void evict_main_iter(struct cache_ext_eviction_ctx *eviction_ctx, struct mem_cgroup *memcg)
{
	/*
	 * Iterate from head. If freq > 0, move to tail, freq--.
	 * Otherwise, evict. (When evicting, move to tail in the meantime).
	 */

	struct cache_ext_iterate_opts opts = {
		.continue_list = CACHE_EXT_ITERATE_SELF,
		.continue_mode = CACHE_EXT_ITERATE_TAIL,
		.evict_list = CACHE_EXT_ITERATE_SELF,
		.evict_mode = CACHE_EXT_ITERATE_TAIL,
	};

	if (bpf_cache_ext_list_iterate_extended(memcg, main_list, bpf_s3fifo_score_main_iter_fn_0, &opts,
						eviction_ctx) < 0) {
		bpf_printk("cache_ext: evict: Failed to iterate main_list\n");
		return;
	}

	if (eviction_ctx->nr_folios_to_evict < eviction_ctx->request_nr_folios_to_evict) {
		if (bpf_cache_ext_list_iterate_extended(memcg, main_list, bpf_s3fifo_score_main_iter_fn_1, &opts,
							eviction_ctx) < 0) {
			bpf_printk("cache_ext: evict: Failed to iterate main_list\n");
			return;
		}
	} else {
		return;
	}

	if (eviction_ctx->nr_folios_to_evict < eviction_ctx->request_nr_folios_to_evict) {
		if (bpf_cache_ext_list_iterate_extended(memcg, main_list, bpf_s3fifo_score_main_iter_fn_2, &opts,
							eviction_ctx) < 0) {
			bpf_printk("cache_ext: evict: Failed to iterate main_list\n");
			return;
		}
	} else {
		return;
	}

	if (eviction_ctx->nr_folios_to_evict < eviction_ctx->request_nr_folios_to_evict) {
		if (bpf_cache_ext_list_iterate_extended(memcg, main_list, bpf_s3fifo_score_main_iter_fn_3, &opts,
							eviction_ctx) < 0) {
			bpf_printk("cache_ext: evict: Failed to iterate main_list\n");
			return;
		}
	}
}

static void evict_small(struct cache_ext_eviction_ctx *eviction_ctx, struct mem_cgroup *memcg)
{
	/*
	 * Iterate from head. If freq > 1, move to main list, otherwise evict.
	 * (When evicting, move to tail in the meantime).
	 *
	 * Use the iterate interface.
	 */

	struct cache_ext_iterate_opts opts = {
		.continue_list = main_list,
		.continue_mode = CACHE_EXT_ITERATE_TAIL,
		.evict_list = CACHE_EXT_ITERATE_SELF,
		.evict_mode = CACHE_EXT_ITERATE_TAIL,
	};

	if (bpf_cache_ext_list_iterate_extended(memcg, small_list, bpf_s3fifo_score_small_fn, &opts,
						eviction_ctx) < 0) {
		bpf_printk("cache_ext: evict: Failed to iterate small_list\n");
		return;
	}

	if (__sync_fetch_and_sub(&small_list_size, opts.nr_folios_continue) < 0)
		small_list_size = 0;

	if (__sync_fetch_and_add(&main_list_size, opts.nr_folios_continue) < 0)
		main_list_size = opts.nr_folios_continue;
}

static int bpf_scan_evict_fn(int idx, struct cache_ext_list_node *a)
{
	if (!folio_test_uptodate(a->folio) || !folio_test_lru(a->folio))
		return CACHE_EXT_CONTINUE_ITER;
	if (folio_test_dirty(a->folio) || folio_test_writeback(a->folio))
		return CACHE_EXT_CONTINUE_ITER;
	return CACHE_EXT_EVICT_NODE;
}

static void evict_scan(struct cache_ext_eviction_ctx *eviction_ctx, struct mem_cgroup *memcg)
{
	struct cache_ext_iterate_opts opts = {
		.continue_list = CACHE_EXT_ITERATE_SELF,
		.continue_mode = CACHE_EXT_ITERATE_TAIL,
		.evict_list = CACHE_EXT_ITERATE_SELF,
		.evict_mode = CACHE_EXT_ITERATE_TAIL,
	};

	if (bpf_cache_ext_list_iterate_extended(memcg, scan_list, bpf_scan_evict_fn, &opts,
						eviction_ctx) < 0)
		bpf_printk("cache_ext: evict: Failed to iterate scan_list\n");
}

void BPF_STRUCT_OPS(evo_policy_evict_folios, struct cache_ext_eviction_ctx *eviction_ctx,
		    struct mem_cgroup *memcg)
{
	if (scan_list_size > SCAN_MIN) {
		evict_scan(eviction_ctx, memcg);
		if (eviction_ctx->nr_folios_to_evict >= eviction_ctx->request_nr_folios_to_evict)
			return;
	}

	// bpf_printk("cache_ext: evict_folios: main_list_size: %lld, small_list_size: %lld, cache_size: %lld\n",
	// 	   main_list_size, small_list_size, cache_size);
	if (small_list_size >= cache_size / 15 || main_list_size <= 2 * small_list_size)
		evict_small(eviction_ctx, memcg);
	else
		evict_main(eviction_ctx, memcg);
}

void BPF_STRUCT_OPS(evo_policy_folio_accessed, struct folio *folio) {
	if (!is_folio_relevant(folio))
		return;

	struct folio_metadata *data = get_folio_metadata(folio);
	if (!data) {
		bpf_printk("cache_ext: accessed: Failed to get metadata\n");
		return;
	}

	if (data->freq < 1000000)
		__sync_fetch_and_add(&data->freq, 1);
}

void BPF_STRUCT_OPS(evo_policy_folio_evicted, struct folio *folio) {
	u64 key = (u64)folio;
	u32 ghost_val = 1;

	// if (bpf_cache_ext_list_del(folio)) {
	// 	bpf_printk("cache_ext: Failed to delete folio from sampling_list\n");
	// 	return;
	// }

	struct ghost_entry ghost_key = {
		.address_space = (u64)folio->mapping->host,
		.offset = folio->index,
	};

	struct folio_metadata *data = get_folio_metadata(folio);
	if (!data) {
		//bpf_printk("cache_ext: evicted: Failed to get metadata\n");
		return;
	}

	if (data->scan) {
		__sync_fetch_and_sub(&scan_list_size, 1);
		bpf_map_delete_elem(&folio_metadata_map, &key);
		return;
	}

	if (data->freq > 1)
		ghost_val = data->freq > 1000000 ? 1000000 : (u32)data->freq;
	if (bpf_map_update_elem(&ghost_map, &ghost_key, &ghost_val, BPF_ANY))
		bpf_printk("cache_ext: evicted: Failed to add to ghost_map\n");

	if (data->in_main)
		__sync_fetch_and_sub(&main_list_size, 1);
	else
		__sync_fetch_and_sub(&small_list_size, 1);

	bpf_map_delete_elem(&folio_metadata_map, &key);

	// if (bpf_map_delete_elem(&folio_metadata_map, &key))
	// 	bpf_printk("cache_ext: evicted: Failed to delete metadata\n");
}

/*
 * If folio is in the ghost map, add to tail of main list, otherwise add to tail
 * of small list.
 */
void BPF_STRUCT_OPS(evo_policy_folio_added, struct folio *folio) {
	if (!is_folio_relevant(folio))
		return;

	u64 key = (u64)folio;
	struct folio_metadata new_meta = {
		.freq = 0,
	};

	u64 list_to_add;
	bool is_scan = false;
	u32 ghost_cnt;
	u64 idx = folio->index;
	struct seq_key sk = {
		.ino = folio->mapping->host->i_ino,
		.tid = (u32)bpf_get_current_pid_tgid(),
	};
	struct seq_state *st = bpf_map_lookup_elem(&seq_map, &sk);
	if (st) {
		if (idx > st->last_idx && idx <= st->last_idx + SEQ_GAP) {
			if (st->run < 1000000)
				st->run++;
		} else {
			st->run = 0;
		}
		st->last_idx = idx;
		is_scan = st->run >= SEQ_RUN;
	} else {
		struct seq_state ns = { .last_idx = idx, .run = 0 };
		bpf_map_update_elem(&seq_map, &sk, &ns, BPF_ANY);
	}

	if (is_scan) {
		list_to_add = scan_list;
		new_meta.scan = true;
		__sync_fetch_and_add(&scan_list_size, 1);
	} else if ((ghost_cnt = folio_in_ghost(folio))) {
		new_meta.freq = ghost_cnt;
		list_to_add = main_list;
		new_meta.in_main = true;
		__sync_fetch_and_add(&main_list_size, 1);
	} else {
		list_to_add = small_list;
		new_meta.in_main = false;
		__sync_fetch_and_add(&small_list_size, 1);
	}

	if (bpf_cache_ext_list_add_tail(list_to_add, folio)) {
		// TODO: add back to ghost_map?
		bpf_printk("cache_ext: added: Failed to add folio to main_list\n");
		return;
	}

	if (bpf_map_update_elem(&folio_metadata_map, &key, &new_meta, BPF_ANY)) {
		// TODO: add back to ghost_map? + error check delete call?
		bpf_cache_ext_list_del(folio);
		bpf_printk("cache_ext: added: Failed to create folio metadata\n");
		return;
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
// Loader for the S3-FIFO policy: parses -w/-s/-c like every policy in this repo,
// attaches the struct_ops to the cgroup and waits for SIGINT/SIGTERM.
// EVOLVE-BLOCK-START
#include <argp.h>
#include <errno.h>
#include <stdlib.h>
#include <bpf/bpf.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include "dir_watcher.h"
#include "evo_policy.skel.h"

char *USAGE = "Usage: ./evo_policy --watch_dir <dir> --cgroup_size <size> --cgroup_path <path>\n";
struct cmdline_args {
	char *watch_dir;
        uint64_t cgroup_size;
        char *cgroup_path;
};

static struct argp_option options[] = {
	{ "watch_dir", 'w', "DIR", 0, "Directory to watch" },
        {"cgroup_size", 's', "SIZE", 0, "Size of the cgroup"},
        {"cgroup_path", 'c', "PATH", 0, "Path to cgroup (e.g., /sys/fs/cgroup/cache_ext_test)"},
	{ 0 },
};

static const uint64_t page_size = 4096;

static volatile sig_atomic_t exiting;

static void sig_handler(int signo) {
	exiting = 1;
}

static error_t parse_opt(int key, char *arg, struct argp_state *state)
{
	struct cmdline_args *args = state->input;
	switch (key) {
	case 'w':
		args->watch_dir = arg;
		break;
        case 's':
                // TODO: move this to parse_args()
                errno = 0;
                args->cgroup_size = strtoull(arg, NULL, 10);
                if (errno)
                        args->cgroup_size = 0;

                break;
        case 'c':
                args->cgroup_path = arg;
                break;
	default:
		return ARGP_ERR_UNKNOWN;
	}
	return 0;
}

static int parse_args(int argc, char **argv, struct cmdline_args *args) {
	struct argp argp = { options, parse_opt, 0, 0 };
	argp_parse(&argp, argc, argv, 0, 0, args);

	if (args->watch_dir == NULL) {
		fprintf(stderr, "Missing required argument: watch_dir\n");
		return 1;
	}

	if (args->cgroup_size == 0) {
	        fprintf(stderr, "Invalid cgroup size\n");
	        return 1;
	}

	if (args->cgroup_path == NULL) {
		fprintf(stderr, "Missing required argument: cgroup_path\n");
		return 1;
	}

	return 0;
}

/*
 * Validate watch_dir
 *
 * watch_dir_full_path must be able to hold PATH_MAX bytes.
 */
static int validate_watch_dir(const char *watch_dir, char *watch_dir_full_path) {
	// Does watch_dir exist?
	if (access(watch_dir, F_OK) == -1) {
		fprintf(stderr, "Directory does not exist: %s\n", watch_dir);
		return 1;
	}

	// Get full path of watch_dir
	if (realpath(watch_dir, watch_dir_full_path) == NULL) {
		perror("realpath");
		return 1;
	}

	// BPF policy restriction
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

	// Install signal handler
	if (sigaction(SIGINT, &sa, NULL) || sigaction(SIGTERM, &sa, NULL)) {
		perror("Failed to set up signal handling");
		return 1;
	}

	if (validate_watch_dir(args.watch_dir, watch_dir_path))
		return 1;

	// Open cgroup directory early
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

	// Set cache size in terms of number of pages. Assumes uniform page size.
	skel->rodata->cache_size = args.cgroup_size / page_size;
	fprintf(stderr, "Cgroup size: %lu bytes\n", args.cgroup_size);
	fprintf(stderr, "Cache size: %lu pages\n", skel->rodata->cache_size);

	// Resize ghost_map
	if (bpf_map__set_max_entries(skel->maps.ghost_map, skel->rodata->cache_size * 4)) {
		perror("Failed to resize ghost_map");
		ret = 1;
		goto cleanup;
	}

	// Set watch_dir
	watch_dir_path_len_map(skel) = strlen(watch_dir_path);
	strcpy(watch_dir_path_map(skel), watch_dir_path);

	if (evo_policy_bpf__load(skel)) {
		perror("Failed to load BPF skeleton");
		ret = 1;
		goto cleanup;
	}

	if (initialize_watch_dir_map(watch_dir_path, bpf_map__fd(inode_watchlist_map(skel)), true)) {
		perror("Failed to initialize watch_dir map");
		ret = 1;
		goto cleanup;
	}

	link = bpf_map__attach_cache_ext_ops(skel->maps.evo_policy_ops, cgroup_fd);
	if (link == NULL) {
		perror("Failed to attach cache_ext_ops to cgroup");
		ret = 1;
		goto cleanup;
	}

	// This is necessary for the dir_watcher functionality
	if (evo_policy_bpf__attach(skel)) {
		perror("Failed to attach BPF skeleton");
		ret = 1;
		goto cleanup;
	}

	printf("evo_policy (S3-FIFO) running. Press Ctrl+C to exit...\n");
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
