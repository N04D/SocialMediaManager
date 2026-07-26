"""Low-level Linux sandbox helpers.

The helpers use documented kernel ABIs through libc/libseccomp. They are kept
small so the production path can fail closed when a kernel feature cannot be
applied or verified.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
import platform
import stat
from pathlib import Path
from typing import Any

LINUX_LAUNCHER_VERSION = "0.1.0"
LINUX_LAUNCHER_CONTRACT_VERSION = "1.0"

PR_SET_NO_NEW_PRIVS = 38
PR_CAP_AMBIENT = 47
PR_CAP_AMBIENT_CLEAR_ALL = 4
PR_SET_SECUREBITS = 28
SECBIT_NOROOT = 1
SECBIT_NOROOT_LOCKED = 2
SECBIT_NO_SETUID_FIXUP = 4
SECBIT_NO_SETUID_FIXUP_LOCKED = 8
SECBIT_KEEP_CAPS_LOCKED = 32
SECBIT_NO_CAP_AMBIENT_RAISE = 64
SECBIT_NO_CAP_AMBIENT_RAISE_LOCKED = 128

MS_REC = 16384
MS_PRIVATE = 1 << 18
MS_NOSUID = 2
MS_NODEV = 4
MS_NOEXEC = 8

LANDLOCK_CREATE_RULESET_VERSION = 1
LANDLOCK_RULE_PATH_BENEATH = 1
LANDLOCK_ACCESS_FS_EXECUTE = 1 << 0
LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
LANDLOCK_ACCESS_FS_READ_FILE = 1 << 2
LANDLOCK_ACCESS_FS_READ_DIR = 1 << 3
LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12
LANDLOCK_ACCESS_FS_REFER = 1 << 13
LANDLOCK_ACCESS_FS_TRUNCATE = 1 << 14

LANDLOCK_BASE_ACCESS = (
    LANDLOCK_ACCESS_FS_EXECUTE
    | LANDLOCK_ACCESS_FS_WRITE_FILE
    | LANDLOCK_ACCESS_FS_READ_FILE
    | LANDLOCK_ACCESS_FS_READ_DIR
    | LANDLOCK_ACCESS_FS_REMOVE_DIR
    | LANDLOCK_ACCESS_FS_REMOVE_FILE
    | LANDLOCK_ACCESS_FS_MAKE_CHAR
    | LANDLOCK_ACCESS_FS_MAKE_DIR
    | LANDLOCK_ACCESS_FS_MAKE_REG
    | LANDLOCK_ACCESS_FS_MAKE_SOCK
    | LANDLOCK_ACCESS_FS_MAKE_FIFO
    | LANDLOCK_ACCESS_FS_MAKE_BLOCK
    | LANDLOCK_ACCESS_FS_MAKE_SYM
)
LANDLOCK_ABI2_ACCESS = LANDLOCK_BASE_ACCESS | LANDLOCK_ACCESS_FS_REFER
LANDLOCK_ABI3_ACCESS = LANDLOCK_ABI2_ACCESS | LANDLOCK_ACCESS_FS_TRUNCATE

SYSCALL_NUMBERS = {
    "x86_64": {
        "landlock_create_ruleset": 444,
        "landlock_add_rule": 445,
        "landlock_restrict_self": 446,
    },
    "aarch64": {
        "landlock_create_ruleset": 444,
        "landlock_add_rule": 445,
        "landlock_restrict_self": 446,
    },
}

DENIED_SYSCALLS = [
    "ptrace",
    "process_vm_readv",
    "process_vm_writev",
    "mount",
    "umount2",
    "pivot_root",
    "chroot",
    "setns",
    "unshare",
    "bpf",
    "perf_event_open",
    "keyctl",
    "add_key",
    "request_key",
    "reboot",
    "kexec_load",
    "kexec_file_load",
    "swapon",
    "swapoff",
    "sethostname",
    "setdomainname",
    "iopl",
    "ioperm",
    "open_by_handle_at",
    "init_module",
    "finit_module",
    "delete_module",
    "fork",
    "vfork",
    "execve",
    "execveat",
]


class SandboxNativeError(RuntimeError):
    """Raised when a required native control cannot be applied."""


def libc() -> ctypes.CDLL:
    return ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)


def syscall(name: str, *args: Any) -> int:
    arch = platform.machine()
    number = SYSCALL_NUMBERS.get(arch, {}).get(name)
    if number is None:
        raise SandboxNativeError(f"unsupported syscall architecture: {arch}")
    result = libc().syscall(ctypes.c_long(number), *args)
    if result < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    return int(result)


def prctl(option: int, arg2: int = 0, arg3: int = 0, arg4: int = 0, arg5: int = 0) -> int:
    result = libc().prctl(option, arg2, arg3, arg4, arg5)
    if result != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    return int(result)


def set_no_new_privs() -> None:
    prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)


def drop_ambient_capabilities() -> None:
    try:
        prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_CLEAR_ALL, 0, 0, 0)
    except OSError as exc:
        if exc.errno not in {errno.EINVAL, errno.EPERM}:
            raise
    securebits = (
        SECBIT_NOROOT
        | SECBIT_NOROOT_LOCKED
        | SECBIT_NO_SETUID_FIXUP
        | SECBIT_NO_SETUID_FIXUP_LOCKED
        | SECBIT_KEEP_CAPS_LOCKED
        | SECBIT_NO_CAP_AMBIENT_RAISE
        | SECBIT_NO_CAP_AMBIENT_RAISE_LOCKED
    )
    try:
        prctl(PR_SET_SECUREBITS, securebits, 0, 0, 0)
    except OSError as exc:
        if exc.errno not in {errno.EINVAL, errno.EPERM}:
            raise


def landlock_abi() -> int:
    try:
        return syscall("landlock_create_ruleset", 0, 0, LANDLOCK_CREATE_RULESET_VERSION)
    except OSError as exc:
        if exc.errno in {errno.ENOSYS, errno.EOPNOTSUPP, errno.EINVAL}:
            return 0
        return 0
    except SandboxNativeError:
        return 0


class LandlockRulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class LandlockPathBeneathAttr(ctypes.Structure):
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def landlock_supported_access(abi: int) -> int:
    if abi >= 3:
        return LANDLOCK_ABI3_ACCESS
    if abi == 2:
        return LANDLOCK_ABI2_ACCESS
    if abi == 1:
        return LANDLOCK_BASE_ACCESS
    return 0


def apply_landlock(*, readonly_paths: list[Path], readwrite_paths: list[Path]) -> dict[str, Any]:
    abi = landlock_abi()
    handled = landlock_supported_access(abi)
    if abi <= 0 or handled == 0:
        raise SandboxNativeError("Landlock is unavailable.")
    ruleset_attr = LandlockRulesetAttr(handled)
    ruleset_fd = syscall("landlock_create_ruleset", ctypes.byref(ruleset_attr), ctypes.sizeof(ruleset_attr), 0)
    opened_fds: list[int] = [ruleset_fd]
    readonly = LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR | LANDLOCK_ACCESS_FS_EXECUTE
    readwrite = readonly | LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_MAKE_REG | LANDLOCK_ACCESS_FS_TRUNCATE
    readwrite &= handled
    readonly &= handled
    try:
        for path, access in [(p, readonly) for p in readonly_paths] + [(p, readwrite) for p in readwrite_paths]:
            if not path.exists():
                continue
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            opened_fds.append(fd)
            beneath = LandlockPathBeneathAttr(access, fd)
            syscall("landlock_add_rule", ruleset_fd, LANDLOCK_RULE_PATH_BENEATH, ctypes.byref(beneath), 0)
        set_no_new_privs()
        syscall("landlock_restrict_self", ruleset_fd, 0)
    finally:
        for fd in opened_fds:
            try:
                os.close(fd)
            except OSError:
                pass
    return {
        "landlock_supported": True,
        "landlock_abi": abi,
        "landlock_requested_access": handled,
        "landlock_enforced_access": handled,
        "landlock_missing_access": 0,
    }


def seccomp_library() -> ctypes.CDLL | None:
    path = ctypes.util.find_library("seccomp")
    if not path:
        return None
    return ctypes.CDLL(path, use_errno=True)


def seccomp_available() -> bool:
    lib = seccomp_library()
    return lib is not None and hasattr(lib, "seccomp_init")


def apply_seccomp_denylist(denied_syscalls: list[str] | None = None) -> dict[str, Any]:
    lib = seccomp_library()
    if lib is None:
        raise SandboxNativeError("libseccomp is unavailable.")
    denied = denied_syscalls or DENIED_SYSCALLS
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_load.restype = ctypes.c_int
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    # SCMP_ACT_ALLOW and SCMP_ACT_ERRNO(EPERM).
    ctx = lib.seccomp_init(0x7FFF0000)
    if not ctx:
        raise SandboxNativeError("seccomp_init failed.")
    resolved: list[str] = []
    try:
        for name in denied:
            number = lib.seccomp_syscall_resolve_name(name.encode())
            if number < 0:
                continue
            rc = lib.seccomp_rule_add(ctx, 0x00050000 | errno.EPERM, number, 0)
            if rc != 0:
                raise SandboxNativeError(f"seccomp rule failed: {name}")
            resolved.append(name)
        set_no_new_privs()
        if lib.seccomp_load(ctx) != 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
    finally:
        lib.seccomp_release(ctx)
    return {
        "seccomp_backend": "libseccomp",
        "seccomp_profile": "channel_api_first.v1",
        "seccomp_denied_syscalls": resolved,
    }


def mount(source: str | None, target: Path, fstype: str | None, flags: int, data: str | None = None) -> None:
    result = libc().mount(
        source.encode() if source else None,
        str(target).encode(),
        fstype.encode() if fstype else None,
        ctypes.c_ulong(flags),
        data.encode() if data else None,
    )
    if result != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))


def make_mounts_private() -> None:
    mount(None, Path("/"), None, MS_REC | MS_PRIVATE)


def mount_proc() -> None:
    mount("proc", Path("/proc"), "proc", MS_NOSUID | MS_NODEV | MS_NOEXEC)


def mount_minimal_dev() -> None:
    mount("tmpfs", Path("/dev"), "tmpfs", MS_NOSUID | MS_NOEXEC, "mode=755,size=1m")
    devices = {
        "null": (0o666, os.makedev(1, 3)),
        "zero": (0o666, os.makedev(1, 5)),
        "random": (0o444, os.makedev(1, 8)),
        "urandom": (0o444, os.makedev(1, 9)),
    }
    for name, (mode, dev) in devices.items():
        try:
            os.mknod(f"/dev/{name}", 0o20000 | mode, dev)
        except FileExistsError:
            pass


def no_new_privs_status() -> bool:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("NoNewPrivs:"):
                return line.split(":", maxsplit=1)[1].strip() == "1"
    except OSError:
        return False
    return False


def launcher_record() -> dict[str, Any]:
    path = Path(__file__).with_name("launcher.py")
    info = path.stat()
    writable_by_other = bool(info.st_mode & stat.S_IWOTH)
    return {
        "launcher_version": LINUX_LAUNCHER_VERSION,
        "launcher_contract_version": LINUX_LAUNCHER_CONTRACT_VERSION,
        "launcher_checksum": __import__("hashlib").sha256(path.read_bytes()).hexdigest(),
        "supported_architectures": sorted(SYSCALL_NUMBERS),
        "architecture": platform.machine(),
        "permissions_safe": not writable_by_other,
        "path": "launcher.py",
    }


__all__ = [
    "DENIED_SYSCALLS",
    "LANDLOCK_ABI3_ACCESS",
    "LINUX_LAUNCHER_CONTRACT_VERSION",
    "LINUX_LAUNCHER_VERSION",
    "MS_NODEV",
    "MS_NOEXEC",
    "MS_NOSUID",
    "SandboxNativeError",
    "apply_landlock",
    "apply_seccomp_denylist",
    "drop_ambient_capabilities",
    "landlock_abi",
    "landlock_supported_access",
    "launcher_record",
    "make_mounts_private",
    "mount_minimal_dev",
    "mount_proc",
    "no_new_privs_status",
    "seccomp_available",
    "set_no_new_privs",
]
