#!/usr/bin/env python3
"""Always-on memory sampler, written to survive the machine dying mid-write.

WHY THIS EXISTS

On 2026-08-31 and 2026-09-01 this host stopped dead during a
`docker compose build`. `journalctl -b -1` and `-b -2` both END MID-SENTENCE --
no shutdown target, no kernel panic, and not one oom-kill line -- because
journald syncs persistent storage every 5 minutes by default. The last minutes
before each lock-up simply do not exist anywhere. This daemon exists to make
them exist.

DESIGN RULES, all of them load-bearing:

  * NO fork(), NO subprocess, NO docker socket. During a reclaim livelock,
    spawning a process is the operation that fails and talking to dockerd is the
    operation that blocks. Everything here is /proc, /sys and statvfs.
  * fsync() after EVERY line. A line that is only in the page cache does not
    survive a hard reset, and a hard reset is precisely the failure being logged.
  * mlockall() plus oom_score_adj=-900, so the sampler is neither swapped out
    nor killed while it is recording the thing that is killing everything else.
  * Adaptive interval: 5s normally, 1s once memory, CPU pressure or steal says
    trouble. The run-up takes minutes; the last few seconds are what matter.

READING THE OUTPUT -- the whole point is that the last few samples name the
cause. Four distinguishable endings:

  * psi_mem_full climbing (10 -> 40 -> 90), memavail collapsing, majflt_s in the
    thousands  =>  swapless reclaim livelock inside the guest. Swap + earlyoom
    are the right guards.
  * steal_pct climbing and/or psi_cpu high while memory is FINE
    =>  the host is starving us of CPU. On this VM that is the leading theory:
    the kernel reports `kvm-guest: PV spinlocks disabled, no host support`, so a
    vCPU preempted while holding a kernel spinlock leaves the other three
    spinning on it. Under all-core load (a build) that lock-holder preemption
    stalls the entire machine, logs nothing, and touches no memory -- which is
    exactly the shape of the 2026-08-31 and 2026-09-01 lock-ups, and why the
    frontend build measured on 2026-09-01 showed NO memory pressure at all.
    This one is a GWDG conversation, not a repo fix.
  * memtotal falling between consecutive samples  =>  virtio-balloon reclaim; the
    host took RAM away (inflation calls adjust_managed_page_count()).
  * everything flat and healthy in the final line, then the log just stops
    =>  the VM was stopped or destroyed from outside. Also a GWDG conversation.

Other platform facts from the serial console, all pointing the same way: AMD Zen1
EPYC with FPDSS/DIV0 errata, `noapic` on the kernel cmdline (IO-APIC probe
skipped, no interrupt remapping), and `tsc: Marking TSC unstable`.
"""

import ctypes
import os
import signal
import sys
import time

LOG_PATH = os.environ.get("MEMWATCH_LOG", "/var/log/rate-site/memwatch.log")
SLOW_INTERVAL = float(os.environ.get("MEMWATCH_SLOW", "5"))
FAST_INTERVAL = float(os.environ.get("MEMWATCH_FAST", "1"))
# Enter fast mode below this many MiB available, or above this PSI full avg10.
FAST_MEM_MIB = int(os.environ.get("MEMWATCH_FAST_MEM_MIB", "900"))
FAST_PSI = float(os.environ.get("MEMWATCH_FAST_PSI", "5.0"))
FAST_CPU_PSI = float(os.environ.get("MEMWATCH_FAST_CPU_PSI", "20.0"))
FAST_STEAL_PCT = float(os.environ.get("MEMWATCH_FAST_STEAL_PCT", "5.0"))
DOCKER_SCOPES = "/sys/fs/cgroup/system.slice"
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")

_reopen = False


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def meminfo():
    out = {}
    for line in _read("/proc/meminfo").splitlines():
        key, _, val = line.partition(":")
        try:
            out[key] = int(val.split()[0]) // 1024          # MiB
        except (IndexError, ValueError):
            pass
    return out


def psi(resource):
    """(some_avg10, full_avg10) from /proc/pressure/<resource>.

    memory and cpu are THE two discriminators -- see the module docstring.
    """
    some = full = 0.0
    for line in _read("/proc/pressure/%s" % resource).splitlines():
        try:
            if line.startswith("some"):
                some = float(line.split("avg10=")[1].split()[0])
            elif line.startswith("full"):
                full = float(line.split("avg10=")[1].split()[0])
        except (IndexError, ValueError):
            pass
    return some, full


def cpu_times():
    """(steal, total) jiffies from /proc/stat.

    Steal is time the hypervisor ran something else while this vCPU was
    runnable. It is the ONLY in-guest evidence of the host starving us, and on
    this VM it matters more than usual: the kernel reports
    `kvm-guest: PV spinlocks disabled, no host support`, so a vCPU preempted
    while holding a kernel spinlock leaves the other three spinning on it --
    lock-holder preemption, which stalls the whole machine, logs nothing, and
    involves no memory pressure at all.
    """
    for line in _read("/proc/stat").splitlines():
        if line.startswith("cpu "):
            f = [int(x) for x in line.split()[1:]]
            # user nice system idle iowait irq softirq steal guest guest_nice
            return (f[7] if len(f) > 7 else 0), sum(f)
    return 0, 0


def pgmajfault():
    for line in _read("/proc/vmstat").splitlines():
        if line.startswith("pgmajfault "):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return 0
    return 0


def top_rss(n=3):
    """Top-n processes by RSS, read straight from /proc. No ps, no fork."""
    procs = []
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return []
    for pid in pids:
        try:
            with open("/proc/%s/statm" % pid, "rb") as f:
                rss_pages = int(f.read().split()[1])
            with open("/proc/%s/comm" % pid, "rb") as f:
                comm = f.read().decode("utf-8", "replace").strip()
        except (OSError, IndexError, ValueError):
            continue                                        # exited mid-read
        procs.append((rss_pages * PAGE_SIZE // (1024 * 1024), comm, pid))
    procs.sort(reverse=True)
    return procs[:n]


def docker_count():
    """Container count without touching the docker socket. Docker here uses the
    systemd cgroup driver on cgroup v2, so each running container is a
    docker-<id>.scope under system.slice."""
    try:
        return sum(1 for e in os.listdir(DOCKER_SCOPES)
                   if e.startswith("docker-") and e.endswith(".scope"))
    except OSError:
        return -1


def lock_memory():
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        MCL_CURRENT, MCL_FUTURE = 1, 2
        libc.mlockall(MCL_CURRENT | MCL_FUTURE)
    except Exception:
        pass                                                # best effort


def protect():
    try:
        with open("/proc/self/oom_score_adj", "w") as f:
            f.write("-900")
    except OSError:
        pass


def open_log():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    return os.open(LOG_PATH, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)


def emit(fd, line):
    """One write(), one fsync(). Never buffered, never lost."""
    os.write(fd, line.encode("utf-8"))
    os.fsync(fd)


def on_hup(signum, frame):
    global _reopen
    _reopen = True                                          # logrotate postrotate


def main():
    global _reopen
    protect()
    lock_memory()
    signal.signal(signal.SIGHUP, on_hup)
    fd = open_log()

    emit(fd, "# boot %s boot_id=%s kernel=%s\n" % (
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        _read("/proc/sys/kernel/random/boot_id").strip(),
        _read("/proc/sys/kernel/osrelease").strip()))

    prev_faults, prev_t = pgmajfault(), time.time()
    prev_steal, prev_total = cpu_times()
    while True:
        if _reopen:
            os.close(fd)
            fd = open_log()
            _reopen = False

        mi = meminfo()
        some, full = psi("memory")
        cpu_some, _ = psi("cpu")
        io_some, _ = psi("io")
        now, faults = time.time(), pgmajfault()
        mf_rate = int((faults - prev_faults) / max(now - prev_t, 0.001))
        prev_faults, prev_t = faults, now

        steal, total = cpu_times()
        d_total = total - prev_total
        steal_pct = (100.0 * (steal - prev_steal) / d_total) if d_total > 0 else 0.0
        prev_steal, prev_total = steal, total

        st = os.statvfs("/")
        disk_free = st.f_bavail * st.f_frsize // (1024 * 1024 * 1024)
        load = _read("/proc/loadavg").split()
        top = ",".join("%s:%d" % (c, m) for m, c, _ in top_rss(3))

        emit(fd,
             "%s memtotal=%d memavail=%d memfree=%d cached=%d swaptotal=%d "
             "swapfree=%d psi_mem_some=%.1f psi_mem_full=%.1f psi_cpu=%.1f "
             "psi_io=%.1f steal_pct=%.1f majflt_s=%d "
             "load=%s/%s/%s procs=%s diskfree_g=%d containers=%d top=%s\n" % (
                 time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 mi.get("MemTotal", 0), mi.get("MemAvailable", 0),
                 mi.get("MemFree", 0), mi.get("Cached", 0),
                 mi.get("SwapTotal", 0), mi.get("SwapFree", 0),
                 some, full, cpu_some, io_some, steal_pct, mf_rate,
                 load[0] if load else "?", load[1] if len(load) > 1 else "?",
                 load[2] if len(load) > 2 else "?",
                 load[3] if len(load) > 3 else "?",
                 disk_free, docker_count(), top or "-"))

        # CPU pressure and steal are fast-mode triggers too, not just memory:
        # the leading theory for this host's lock-ups is CPU starvation, and
        # sampling it at 5s would blur the only evidence that matters.
        fast = (mi.get("MemAvailable", 0) < FAST_MEM_MIB
                or full > FAST_PSI
                or cpu_some > FAST_CPU_PSI
                or steal_pct > FAST_STEAL_PCT)
        time.sleep(FAST_INTERVAL if fast else SLOW_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
