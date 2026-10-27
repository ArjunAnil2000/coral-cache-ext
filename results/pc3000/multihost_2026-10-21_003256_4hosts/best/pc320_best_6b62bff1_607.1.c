// ============================================================================
// SECTION: BPF KERNEL CODE
// ============================================================================
// EVOLVE-BLOCK-START
// [jack-sparrow: nemo 51067b5b with CLOCK pass thresholds (1,3,8) -> (2,4,16)]
// [captain-nemo: davy-jones f578a1ba with GRACE_NS 1s -> 200ms, REGION_SHIFT 4 -> 3]
// History-LFU (davy-jones): one list, CLOCK-style threshold passes (iterate API) evicting
// low-frequency folios.
// Frequency lives in a fixed-size counter array keyed by hash(inode, page index), so it
// SURVIVES eviction. Accesses to the same page within 2ms count once (the scan thread
// reads many keys per page in a burst, which otherwise pins scan pages): a hot page that is evicted and re-read keeps its count, unlike a
// per-folio map. No per-folio metadata map at all. Counters are halved every AGE_PERIOD
// accesses (lazy, via an epoch stamp per slot) so the history slowly forgets.
#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>

#include "cache_ext_lib.bpf.h"
#include "dir_watcher.bpf.h"

char _license[] SEC("license") = "GPL";

#define SKETCH_BITS 19
#define REGION_SHIFT 3		/* 8 pages = 32KB regions */
#define SKETCH_SIZE (1 << SKETCH_BITS)
#define SKETCH_MASK (SKETCH_SIZE - 1)
#define AGE_SHIFT 18		/* epoch advances every 2^18 accesses */
#define SAMPLE_SIZE 16
#define FREQ_MAX 0xffff
#define SCORE_MAX (0x7fffffffffffffffLL)

#define DEDUPE_NS (2ULL * 1000 * 1000)	/* bursts within 2ms count once */

struct dj_freq_slot {
	u32 count;
	u32 epoch;
	u64 last_ns;
	u64 added_ns;
};

#define GRACE_NS (200ULL * 1000 * 1000)	/* new folios are not victims for 200ms */

struct {
	__uint(type, BPF_MAP_TYPE_ARRAY);
	__type(key, u32);
	__type(value, struct dj_freq_slot);
	__uint(max_entries, SKETCH_SIZE);
} sketch SEC(".maps");

static u64 main_list;
static u64 nr_accesses = 0;

static inline bool is_folio_relevant(struct folio *folio) {
	if (!folio || !folio->mapping || !folio->mapping->host)
		return false;

	return inode_in_watchlist(folio->mapping->host->i_ino);
}

static inline u32 folio_slot(struct folio *folio)
{
	u64 ino = folio->mapping->host->i_ino;
	// Region granularity: all pages of a 2^REGION_SHIFT-page file region share one counter,
	// so a readahead batch is kept or evicted as a unit and refaults come back as one IO.
	u64 region = (u64)folio->index >> REGION_SHIFT;
	u64 h = (ino * 0x9E3779B97F4A7C15ULL) ^ (region * 0xC2B2AE3D27D4EB4FULL);
	h ^= h >> 29;
	return (u32)(h & SKETCH_MASK);
}

static inline struct dj_freq_slot *get_slot(struct folio *folio, u32 epoch)
{
	u32 key = folio_slot(folio);
	struct dj_freq_slot *s = bpf_map_lookup_elem(&sketch, &key);
	if (!s)
		return NULL;
	u32 old = s->epoch;
	if (old != epoch) {
		u32 d = epoch - old;
		s->count = d >= 16 ? 0 : (s->count >> d);
		s->epoch = epoch;
	}
	return s;
}

s32 BPF_STRUCT_OPS_SLEEPABLE(evo_policy_init, struct mem_cgroup *memcg)
{
	main_list = bpf_cache_ext_ds_registry_new_list(memcg);
	if (main_list == 0) {
		bpf_printk("cache_ext: init: Failed to create main_list\n");
		return -1;
	}
	return 0;
}

static inline s64 folio_count(struct folio *f)
{
	if (!f->mapping || !f->mapping->host)
		return 0;
	struct dj_freq_slot *s = get_slot(f, (u32)(nr_accesses >> AGE_SHIFT));
	if (!s)
		return 0;
	if (bpf_ktime_get_ns() - s->added_ns < GRACE_NS)
		return 1LL << 40;
	return s->count;
}

// CLOCK-style pass over the list: evict folios whose (persistent) count <= thr, move the
// rest to the tail. Uses list_iterate instead of list_sample (every sample-based policy
// on the team scores 500-550, every iterate-based one >= 600).
#define LFU_ITER_FN(thr)								\
static int lfu_iter_fn_##thr(int idx, struct cache_ext_list_node *a)			\
{											\
	struct folio *f = a->folio;							\
	if (!folio_test_uptodate(f) || !folio_test_lru(f))				\
		return CACHE_EXT_CONTINUE_ITER;						\
	if (folio_test_dirty(f) || folio_test_writeback(f))				\
		return CACHE_EXT_CONTINUE_ITER;						\
	if (folio_count(f) <= thr)							\
		return CACHE_EXT_EVICT_NODE;						\
	return CACHE_EXT_CONTINUE_ITER;							\
}

LFU_ITER_FN(2)
LFU_ITER_FN(4)
LFU_ITER_FN(16)

static int any_iter_fn(int idx, struct cache_ext_list_node *a)
{
	struct folio *f = a->folio;
	if (!folio_test_uptodate(f) || !folio_test_lru(f))
		return CACHE_EXT_CONTINUE_ITER;
	if (folio_test_dirty(f) || folio_test_writeback(f))
		return CACHE_EXT_CONTINUE_ITER;
	return CACHE_EXT_EVICT_NODE;
}

void BPF_STRUCT_OPS(evo_policy_evict_folios, struct cache_ext_eviction_ctx *eviction_ctx,
		    struct mem_cgroup *memcg)
{
	struct cache_ext_iterate_opts opts = {
		.continue_list = CACHE_EXT_ITERATE_SELF,
		.continue_mode = CACHE_EXT_ITERATE_TAIL,
		.evict_list = CACHE_EXT_ITERATE_SELF,
		.evict_mode = CACHE_EXT_ITERATE_TAIL,
	};
	if (bpf_cache_ext_list_iterate_extended(memcg, main_list, lfu_iter_fn_2, &opts, eviction_ctx) < 0)
		return;
	if (eviction_ctx->nr_folios_to_evict >= eviction_ctx->request_nr_folios_to_evict)
		return;
	if (bpf_cache_ext_list_iterate_extended(memcg, main_list, lfu_iter_fn_4, &opts, eviction_ctx) < 0)
		return;
	if (eviction_ctx->nr_folios_to_evict >= eviction_ctx->request_nr_folios_to_evict)
		return;
	if (bpf_cache_ext_list_iterate_extended(memcg, main_list, lfu_iter_fn_16, &opts, eviction_ctx) < 0)
		return;
	if (eviction_ctx->nr_folios_to_evict >= eviction_ctx->request_nr_folios_to_evict)
		return;
	bpf_cache_ext_list_iterate_extended(memcg, main_list, any_iter_fn, &opts, eviction_ctx);
}

void BPF_STRUCT_OPS(evo_policy_folio_accessed, struct folio *folio)
{
	if (!is_folio_relevant(folio))
		return;
	u64 n = __sync_fetch_and_add(&nr_accesses, 1);
	struct dj_freq_slot *s = get_slot(folio, (u32)(n >> AGE_SHIFT));
	if (!s)
		return;
	u64 now = bpf_ktime_get_ns();
	if (now - s->last_ns < DEDUPE_NS)
		return;
	s->last_ns = now;
	if (s->count < FREQ_MAX)
		s->count += 1;
}

void BPF_STRUCT_OPS(evo_policy_folio_evicted, struct folio *folio) {
}

void BPF_STRUCT_OPS(evo_policy_folio_added, struct folio *folio) {
	if (!is_folio_relevant(folio))
		return;

	if (bpf_cache_ext_list_add_tail(main_list, folio)) {
		bpf_printk("cache_ext: added: Failed to add folio to main_list\n");
		return;
	}
	struct dj_freq_slot *s = get_slot(folio, (u32)(nr_accesses >> AGE_SHIFT));
	if (s)
		s->added_ns = bpf_ktime_get_ns();
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
// Loader for the FIFO policy: parses -w/-s/-c like every policy in this repo,
// attaches the struct_ops to the cgroup and waits for SIGINT/SIGTERM.
// EVOLVE-BLOCK-START
#include <argp.h>
#include <errno.h>
#include <string.h>
#include <stdlib.h>
#include <bpf/bpf.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <signal.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include "dir_watcher.h"
#include "evo_policy.skel.h"

char *USAGE = "Usage: ./evo_policy --watch_dir <dir> --cgroup_path <path>\n";
struct cmdline_args {
	char *watch_dir;
	char *cgroup_path;
	uint64_t cgroup_size;	/* accepted for harness compatibility */
};

static struct argp_option options[] = {
	{ "watch_dir", 'w', "DIR", 0, "Directory to watch" },
	{ "cgroup_path", 'c', "PATH", 0, "Path to cgroup (e.g., /sys/fs/cgroup/cache_ext_test)" },
	{ "cgroup_size", 's', "SIZE", 0,
	  "Size of the cgroup in bytes (accepted for harness compatibility)" },
					{ 0 },
};

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

static int parse_args(int argc, char **argv, struct cmdline_args *args) {
	struct argp argp = { options, parse_opt, 0, 0 };
	argp_parse(&argp, argc, argv, 0, 0, args);

	if (args->watch_dir == NULL) {
		fprintf(stderr, "Missing required argument: watch_dir\n");
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

	if (evo_policy_bpf__load(skel)) {
		perror("Failed to load BPF skeleton");
		goto cleanup;
	}

	if (initialize_watch_dir_map(watch_dir_path, bpf_map__fd(inode_watchlist_map(skel)), true)) {
		perror("Failed to initialize watch_dir map");
		goto cleanup;
	}

	link = bpf_map__attach_cache_ext_ops(skel->maps.evo_policy_ops, cgroup_fd);
	if (link == NULL) {
		perror("Failed to attach cache_ext_ops to cgroup");
		goto cleanup;
	}

	// This is necessary for the dir_watcher functionality
	if (evo_policy_bpf__attach(skel)) {
		perror("Failed to attach BPF skeleton");
		goto cleanup;
	}

	printf("evo_policy (FIFO) running. Press Ctrl+C to exit...\n");
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
