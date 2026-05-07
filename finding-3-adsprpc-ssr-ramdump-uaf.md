# Finding 3: Use-after-free in `fastrpc_ramdump_collection` — write primitive into freed kernel slab

## Summary

In Qualcomm's `adsprpc.c` (FastRPC) driver, `fastrpc_ramdump_collection()` signals
completion to a waiting destroy path *before* finishing its own access to the
buffer. The destroy thread, woken by `complete()`, can race ahead and free the
buffer (`fastrpc_buf_free(fl->init_mem, 0)` → `kfree(buf)`) before the SSR loop
executes its next statement, `hlist_del_init(&buf->hn_init)` — a write to two
fields (`next`, `prev`) of the freed slab object.

This produces a kernel use-after-free on a slab object, with two attacker-influenceable
writes (the `hlist_del_init` invocation produces specific values written to
`buf->hn_init.next` and `buf->hn_init.prev`). The two writes are not directly
attacker-controlled (they're list-pointer fixups) but the freed slot can be
reused for an attacker-sprayed allocation between the kfree and the writes,
which then has its `[hn_init.next, hn_init.prev]` fields corrupted to
specifically the addresses `&list_head_node` (well-known, the `chan->initmems`
list head).

## Affected source

- Repository: `https://github.com/MotorolaMobilityLLC/kernel-msm`
- Branch: `android-14-release-u1ufns34.41-98-3-11`
- File: `drivers/char/adsprpc.c`
- SSR side: `fastrpc_ramdump_collection()` lines ~2310-2360
- Destroy side: `fastrpc_file_free()` (or equivalent) lines ~5396-5435
- Buffer free with `kfree`: `fastrpc_buf_free()` line ~1090

## The race in detail

### SSR side (`fastrpc_ramdump_collection`, loop 2)

```c
hlist_for_each_entry_safe(buf, n, &chan->initmems, hn_init) {
    memset(&ramdump_entry, 0, sizeof(ramdump_entry));
    ramdump_entry.address = buf->phys;
    ramdump_entry.v_address = (void __iomem *)buf->virt;
    ramdump_entry.size = buf->size;
    if (buf->fl) {
        scnprintf(ramdump_name, ARRAY_SIZE(ramdump_name),
            "%s_%x_", gcinfo[cid].subsys, buf->fl->tgid);
        ramdump_entry.name = ramdump_name;
    }
    ret = fastrpc_elf_ramdump(chan->rh_dump_dev, &ramdump_entry);
    if (ret < 0)
        ADSPRPC_ERR(...);
    if (buf->fl)
        complete(&buf->fl->work);              /* <-- (1) wakes destroy */
    hlist_del_init(&buf->hn_init);             /* <-- (2) writes to buf */
}
```

### Destroy side (`fastrpc_file_free`, after `wait_for_completion`)

```c
wait_for_completion(&fl->work);                /* unblocked by SSR's complete() */
skip_dump_wait:
    spin_lock(&fl->apps->hlock);
    hlist_del_init(&fl->hn);
    fl->is_ramdump_pend = false;
    fl->dsp_process_state = PROCESS_CREATE_DEFAULT;
    spin_unlock(&fl->apps->hlock);
    kfree(fl->debug_buf);
    kfree(fl->gidlist.gids);
    if (!fl->sctx) {
        kfree(fl->dev_pm_qos_req);
        kfree(fl);
        return 0;
    }
    spin_lock_irqsave(&fl->aqlock, flags);
    atomic_add(1, &fl->async_queue_job_count);
    wake_up_interruptible(&fl->async_wait_queue);
    spin_unlock_irqrestore(&fl->aqlock, flags);
    if (!IS_ERR_OR_NULL(fl->init_mem)) {
        fastrpc_buf_free(fl->init_mem, 0);     /* <-- frees `buf` (kfree at end) */
        fl->init_mem = NULL;
    }
    ...
```

### Race window

Between SSR statement (1) and (2):

1. SSR runs (1): `complete(&buf->fl->work)`. The destroy thread becomes runnable.
2. Kernel preemption / scheduling: destroy starts executing on another CPU,
   or preempts SSR on the same CPU.
3. Destroy executes the entire post-wait flow including:
   - hlist_del_init(&fl->hn) under apps->hlock
   - kfree(fl->debug_buf), kfree(fl->gidlist.gids)
   - the !sctx kfree(fl) branch (if reached) OR the dummy-wakeup + the conditional
     `fastrpc_buf_free(fl->init_mem, 0);`
4. `fastrpc_buf_free(buf, 0)` falls through to `kfree(buf)` (line ~1090, `bail:` label).
   At this point `buf` is freed. Its slab slot may be allocated to another
   object before SSR resumes.
5. SSR resumes and runs (2): `hlist_del_init(&buf->hn_init)`.
   `hlist_del_init` writes to `buf->hn_init.pprev` and `buf->hn_init.next`,
   specifically:
     - `buf->hn_init.next = NULL`
     - `*buf->hn_init.pprev = NULL`  (the back-pointer fixup)
     - `buf->hn_init.pprev = &buf->hn_init`
   These writes go to whatever object now occupies that slab slot.

## Why the existing synchronization is incomplete

The maintainers added `is_ramdump_pend` + `complete(&fl->work)` synchronization
specifically to prevent UAF on `fl->init_mem` during ramdump. The intent is "destroy
waits for ramdump-of-this-fl to finish before freeing init_mem." The implementation
*almost* gets this right — but `complete()` is called **before** the SSR loop
finishes accessing `buf`. The remaining `hlist_del_init(&buf->hn_init)` is the
one statement that runs after the synchronization barrier from destroy's
perspective.

The fix is straightforward:

```c
if (buf->fl) {
    /* hlist_del_init MUST come before completing the destroy waiter
     * because once we complete, the buf may be freed underneath us.
     */
    hlist_del_init(&buf->hn_init);
    complete(&buf->fl->work);
} else {
    hlist_del_init(&buf->hn_init);
}
```

## Reachability from `untrusted_app`

For this race to fire, an attacker needs:

1. **`/dev/adsprpc-smd` open** — verified reachable from `untrusted_app` SELinux
   domain on stock-firmware Moto G 5G 2024 (build U1UFNS34.41-98-3-19,
   patch level 2025-06-01).
2. **A `fastrpc_file` (`fl`) in a state where `fl->init_mem != NULL` and
   `fl->dsp_proc_init == 1`** — this requires successful `FASTRPC_IOCTL_INIT`
   with mode `FASTRPC_INIT_CREATE` (dynamic process creation). On the moto g
   5G 2024 the audio PD is reachable from `untrusted_app`; whether dynamic-PD
   creation specifically is permitted by SELinux on stock builds needs an
   on-device test (the `untrusted app trying to attach to audio PD` denial in
   `init_create_static_process` is type-specific to STATIC; DYNAMIC may pass).
3. **An SSR (audio PD subsystem restart) trigger** — SSR fires when the audio
   DSP firmware crashes. Past Qualcomm CVEs (e.g., CVE-2023-21630, CVE-2024-21450
   family) demonstrate that malformed FastRPC invocations can crash the DSP,
   so triggering SSR from `untrusted_app` is plausible but not free — needs a
   DSP-fault-inducing call sequence. Independent of attacker control, normal
   transient SSR events (firmware faults during stress) make the bug fire on
   real devices in benign-looking circumstances; an exploit just needs reliable
   triggering.
4. **A close()** of the FastRPC fd while an SSR is in progress — trivially
   triggerable (just close after starting an init that crashes the DSP).
5. **A heap spray** to repopulate the freed slot before the `hlist_del_init`
   resumes. Standard Android kernel slab-spray techniques apply; the freed
   object size is `sizeof(struct fastrpc_buf)` so the matching kmalloc-size
   bucket can be sprayed via any object of that size class.

Steps 1, 2, 4 are user-driven. Step 3 is the gating one and benefits from
either independent DSP-fault primitive or just an existing transient SSR. The
race window between `complete()` and `hlist_del_init` is small but reliably
hittable with kernel preemption on a multicore device.

## Exploitation primitive

After a successful race:

- The freed `buf` slab slot is reused by attacker-sprayed allocation X.
- SSR's `hlist_del_init(&buf->hn_init)` runs. Equivalent C:
  ```c
  next = buf->hn_init.next;       /* read-from-slab */
  pprev = buf->hn_init.pprev;     /* read-from-slab */
  if (next) next->pprev = pprev;  /* write at addr derived from sprayed data */
  *pprev = next;                  /* write at addr derived from sprayed data */
  buf->hn_init.next = NULL;       /* zero into sprayed slot */
  buf->hn_init.pprev = LIST_POISON2;
  ```

The `*pprev = next` write is **arbitrary kernel-address write of a
controlled value**, with both the address (`pprev` = controlled by s