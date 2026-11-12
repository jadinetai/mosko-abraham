"""Diagnostic: does a QMP system_reset restart the UEFI firmware on this accelerator?

  python tools/diag_reset.py --run-id DIAG-RESET-0001 --accel whpx --qemu-dir <dir>
         [--abraham <BOOTX64.EFI> --kernel <elf> --expect-kernel-sha256 <sha>]

Without --abraham: firmware and an empty boot disk only, no kernel; counts BdsDxe "loading Boot"
lines before and after the reset. With --abraham: Limine and the named kernel are staged and boot 2
means Abraham's second OPERATIONAL. Evidence under evidence/diagnostics/<run-id>, sealed.

0.31b (Echo F-029-02): the result label now says what was actually staged. Before, every run was
labelled "firmware only, no Abraham code", including --abraham runs such as DIAG-RESET-0110 (that
sealed result is not changed; TR-0034 records the correction). --abraham now requires --kernel and
--expect-kernel-sha256 (the 0.31 harness has no default kernel).
"""

FIRMWARE_ONLY = "DIAGNOSTIC (firmware only, no Abraham code)"


def run_label(staged_kernel_sha256):
    """The result label for what was staged: None = no kernel on the boot disk."""
    if staged_kernel_sha256 is None:
        return FIRMWARE_ONLY
    return f"DIAGNOSTIC (Abraham staged: Limine + kernel {staged_kernel_sha256})"

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import abr_boot_001 as h  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--accel", choices=("whpx", "tcg"), default="whpx")
    parser.add_argument("--cpu")
    parser.add_argument("--qemu-dir", required=True, help="absolute folder of the pinned QEMU")
    parser.add_argument("--debugcon", action="store_true",
                        help="capture the firmware's debug log (I/O port 0x402) into the run folder")
    parser.add_argument("--wait", type=int, default=60, help="seconds to wait for each firmware boot")
    parser.add_argument("--abraham", metavar="BOOTX64.EFI",
                        help="stage Limine + the built kernel and sample CPU registers after the reset")
    parser.add_argument("--limine-serial-off", action="store_true", help="stage limine.conf with serial: no")
    parser.add_argument("--reset-at", type=float, help="send system_reset this many seconds after launch")
    parser.add_argument("--limine-timeout", type=int, help="stage limine.conf with this menu timeout")
    parser.add_argument("--serial-stdio", action="store_true", help="COM1 to QEMU stdout instead of file:")
    parser.add_argument("--explicit-chardev", action="store_true",
                        help="wire COM1 as -chardev file + -device isa-serial instead of -serial file:")
    parser.add_argument("--kernel", help="with --abraham: the kernel ELF to stage")
    parser.add_argument("--expect-kernel-sha256", help="with --abraham: the SHA-256 the kernel must have")
    args = parser.parse_args()
    h.use_qemu(args.qemu_dir)
    staged_sha = None
    if args.abraham:
        if not args.kernel or not args.expect_kernel_sha256:
            raise SystemExit("BLOCKED: --abraham needs --kernel and --expect-kernel-sha256")
        h.KERNEL_ELF = Path(args.kernel).resolve()
        staged_sha = h.sha256(h.KERNEL_ELF)
        if staged_sha != args.expect_kernel_sha256.lower():
            print(f"REFUSED: kernel {h.KERNEL_ELF} has SHA-256 {staged_sha}, expected {args.expect_kernel_sha256}; nothing was run")
            raise SystemExit(2)
    run_dir = h.EVIDENCE / "diagnostics" / args.run_id
    if run_dir.exists():
        raise SystemExit(f"REFUSED: {run_dir} exists")
    (run_dir / "esp" / "EFI" / "BOOT").mkdir(parents=True)
    if args.abraham:
        # Stage the real boot disk exactly as abr_boot_001.py does (loader, hashed config, kernel).
        (run_dir / "esp" / "boot" / "limine").mkdir(parents=True)
        shutil.copyfile(args.abraham, run_dir / "esp" / "EFI" / "BOOT" / "BOOTX64.EFI")
        kernel = h.KERNEL_ELF.read_bytes()
        (run_dir / "esp" / "boot" / "abraham-kernel").write_bytes(kernel)
        conf = h.LIMINE_CONF.read_text(encoding="ascii").replace("{KERNEL_BLAKE2B}", h.hashlib.blake2b(kernel).hexdigest())
        if args.limine_timeout is not None:
            conf = conf.replace("timeout: 0", f"timeout: {args.limine_timeout}")  # diagnostic: menu wait
        if args.limine_serial_off:
            conf = conf.replace("serial: yes", "serial: no")  # diagnostic only: Limine never touches COM1
        (run_dir / "esp" / "boot" / "limine" / "limine.conf").write_text(conf, encoding="ascii", newline="\n")
    shutil.copyfile(h.FW_VARS, run_dir / "vars.fd")
    serial = run_dir / "serial.log"
    port = h.free_port()
    cpu = args.cpu or ("host" if args.accel == "whpx" else "max")
    command = h.qemu_command(args.accel, cpu, run_dir, run_dir / "esp", port, serial)
    if args.explicit_chardev:
        i = command.index("-serial")
        command[i:i + 2] = ["-chardev", f"file,id=com1,path={serial}", "-device", "isa-serial,chardev=com1"]
    if args.serial_stdio:
        i = command.index("-serial")
        command[i + 1] = "stdio"  # QEMU writes COM1 to its stdout, captured into serial.log
    if args.debugcon:
        command += ["-debugcon", f"file:{run_dir / 'debugcon.log'}", "-global", "isa-debugcon.iobase=0x402"]
    t0 = time.monotonic()

    def boots():
        # One boot-manager attempt on the boot disk per firmware boot. With an empty disk the
        # line is "failed to load Boot0001"; with a loader it is "loading Boot0001".
        # Fix (TR-0024): count occurrences anywhere in the text. After the UEFI shell's
        # "Shell> " prompt (no newline) the next boot's firmware line shares that line, which
        # the earlier line-start match missed.
        text = "\n".join(h.serial_lines(serial))
        return text.count('BdsDxe: failed to load Boot0001') + text.count('BdsDxe: loading Boot0001')

    def abraham_boots():
        return sum(1 for l in h.serial_lines(serial) if l == h.OPERATIONAL)

    with open(run_dir / "qemu-stderr.txt", "wb") as err:
        stdout_target = open(serial, "wb") if args.serial_stdio else h.subprocess.DEVNULL
        process = h.subprocess.Popen(command, stdout=stdout_target, stderr=err)
        qmp = h.Qmp(port, run_dir / "qmp.jsonl", t0)
        registers = {}
        if args.reset_at is not None:
            time.sleep(args.reset_at)  # early reset: before the loader or Abraham has run
            first = None
        elif args.abraham:
            first = h.wait_for(lambda: h.OPERATIONAL in h.serial_lines(serial), args.wait)
            time.sleep(3)
            registers["before_reset"] = qmp.command("human-monitor-command", **{"command-line": "info registers"}).get("return")
        else:
            first = h.wait_for(lambda: boots() >= 1, args.wait)
            time.sleep(2)
        qmp.command("system_reset")
        # Fix (TR-0024): with Abraham staged, "boot 2 happened" means Abraham's second
        # OPERATIONAL, not the firmware's boot-manager line (which comes seconds before the
        # loader has even loaded the kernel).
        second = h.wait_for((lambda: abraham_boots() >= 2) if args.abraham and args.reset_at is None
                            else (lambda: boots() >= 2), args.wait)
        if args.abraham:
            time.sleep(2)
            registers["after_reset"] = qmp.command("human-monitor-command", **{"command-line": "info registers"}).get("return")
            for port in ("0x3fd", "0x3fc", "0x3fb", "0x3f9"):  # COM1 LSR, MCR, LCR, IER
                registers[f"com1_{port}"] = qmp.command("human-monitor-command", **{"command-line": f"i /b {port}"}).get("return")
            (run_dir / "registers.json").write_text(json.dumps(registers, indent=1) + "\n")
        status = qmp.command("query-status").get("return")
        qmp.command("quit")
        exit_code = process.wait(timeout=20)
    result = {"run_id": args.run_id, "accel": args.accel, "cpu": cpu, "qemu_command": command,
              "firmware_boot_before_reset": bool(first), "firmware_boot_after_reset": bool(second),
              "boot_manager_starts_seen": boots(), "abraham_operational_count": abraham_boots(), "status_after": status, "qemu_exit": exit_code,
              "qmp_events": qmp.events, "label": run_label(staged_sha), "abraham_staged": staged_sha is not None,
              "staged_kernel_sha256": staged_sha}
    (run_dir / "result.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    h.seal(run_dir)
    print(json.dumps({k: v for k, v in result.items() if k not in ("qemu_command", "qmp_events")}, indent=1))


if __name__ == "__main__":
    main()
