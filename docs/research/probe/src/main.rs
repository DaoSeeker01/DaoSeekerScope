fn main() {
    let mut system = sysinfo::System::new();
    system.refresh_cpu_list(sysinfo::CpuRefreshKind::nothing());
    system.refresh_memory();
    println!("os={:?}; arch={}; logical_cpus={}; physical_cores={:?}; usable_memory_bytes={}; cpu_brand={:?}",
        sysinfo::System::name(), sysinfo::System::cpu_arch(), system.cpus().len(),
        sysinfo::System::physical_core_count(), system.total_memory(),
        system.cpus().first().map(|cpu| cpu.brand()));
}
