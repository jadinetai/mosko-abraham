//! Pinned identities. Every digest here was recorded by the 0.33 campaign (TR-0042) or by an accepted decision, and
//! none can be changed at run time: a different kernel, QEMU, firmware or loader is refused, never booted.
//! Paths can be overridden for tests (`--home`, `--qemu-dir`); digests cannot.

/// What a pinned kernel is expected to do, so the launcher can say whether the observed outcome is the designed one.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Build {
    /// The 0.33.0-dev production kernel: services, application registry and APPINFO; it makes no launch request.
    Production,
    /// DIAGNOSTIC diag-launchpad: as production, plus the fixed 17-request launcher-contract script.
    Launchpad,
    /// DIAGNOSTIC diag-early-fail: an injected initialization failure; it must stop before OPERATIONAL.
    EarlyFail,
}

pub struct KernelPin {
    pub key: &'static str,
    pub menu: &'static str,
    /// Relative to the Abraham home folder.
    pub rel_path: &'static str,
    pub sha256: &'static str,
    pub build: Build,
    /// The version the kernel's banner must report.
    pub version: &'static str,
    pub label: &'static str,
}

pub static KERNELS: [KernelPin; 3] = [
    KernelPin {
        key: "production",
        menu: "Abraham 0.33.0-dev, production kernel (services, application registry)",
        rel_path: r"work-0.33\build\abraham-kernel-0.33.0-dev.elf",
        sha256: "6b95b9a27a8eedd68dd5023dbf99e73716aa1be88780ddde406099679e119a21",
        build: Build::Production,
        version: "0.33.0-dev",
        label: "production",
    },
    KernelPin {
        key: "launchpad",
        menu: "DIAGNOSTIC launchpad build (the 17 launcher-contract requests)",
        rel_path: r"work-0.33\build\diag\abraham-kernel-diag-launchpad.elf",
        sha256: "89b3d6fa186753f7539aa84e6cde19532e53ac00bd752255954105fcb7755758",
        build: Build::Launchpad,
        version: "0.33.0-dev",
        label: "DIAGNOSTIC diag-launchpad",
    },
    KernelPin {
        key: "early-fail",
        menu: "DIAGNOSTIC early-fail build (a deliberately failed boot)",
        rel_path: r"work-0.33\build\diag\abraham-kernel-diag-early-fail.elf",
        sha256: "79b6cdce89863073de71301e4b304014ddf651b95f123d8c2f43cd5b6f8e6409",
        build: Build::EarlyFail,
        version: "0.33.0-dev",
        label: "DIAGNOSTIC diag-early-fail",
    },
];

/// The pinned QEMU (D-ABR-004, D-ABR-008): QEMU 11.1.0, Weil 20260811, extracted, never installed. Relative to
/// %USERPROFILE%. The Program Files copy is never used.
pub const QEMU_DIR_UNDER_PROFILE: &str = r"abraham-toolchain\qemu\11.1.0-weil-20260811";
pub const QEMU_EXE: &str = "qemu-system-x86_64.exe";
pub const QEMU_EXE_SHA256: &str = "47d57a6072e0bb3bd98f87926eb129eb1736dfe818c67b3b81ef7ce4edd0b3cd";
pub const QEMU_VERSION_LINE: &str = "QEMU emulator version 11.1.0 (v11.1.0-12130-ge470268ff4)";
pub const FW_CODE: &str = r"share\edk2-x86_64-code.fd";
pub const FW_CODE_SHA256: &str = "33090cc07675baa5190d9f1e84bf5176b33bcbfa9bacac522961150cdb6dbb2a";
pub const FW_VARS: &str = r"share\edk2-i386-vars.fd";
pub const FW_VARS_SHA256: &str = "5d2ac383371b408398accee7ec27c8c09ea5b74a0de0ceea6513388b15be5d1e";

/// Limine 12.9.6 (GPG-verified in ABR-BOOT-001), and the boot-entry template of the harness. Relative to the home.
pub const LIMINE_EFI: &str = r"work-0.33\third_party\limine-12.9.6\extracted\limine-binary\BOOTX64.EFI";
pub const LIMINE_EFI_SHA256: &str = "e486ae7abd7d5b88f98f43cfd6e8f9057ff975ecd667dfb33f1581de36e00982";
pub const LIMINE_CONF: &str = r"work-0.33\boot\limine.conf";
pub const LIMINE_CONF_SHA256: &str = "ea81dbc99c3b4621d69fc852d58a9cb35c125f0b24a4aa73bc094c2a1d05d3b9";
pub const LIMINE_CONF_PLACEHOLDER: &str = "{KERNEL_BLAKE2B}";
/// The boot entry's path line, which must carry the placeholder. The harness replaces every occurrence (the template's
/// comment names the placeholder too), and so does the launcher.
pub const LIMINE_CONF_PATH_LINE: &str = "path: boot():/boot/abraham-kernel#{KERNEL_BLAKE2B}";

pub fn kernel(key: &str) -> Option<&'static KernelPin> {
    KERNELS.iter().find(|k| k.key == key)
}
