//! Validation of exchange data before encoding and after decoding.
use crate::*;
use std::io::{self, Write};

/// Count serialized bytes before accepting a decoded model, and cap writes
/// before allocation when encoding a model supplied by a Rust caller.
pub(crate) fn encode<W: Write>(snapshot: &Snapshot, writer: W) -> Result<(), ScopeError> {
    struct Bounded<W> {
        inner: W,
        remaining: usize,
        exhausted: bool,
    }
    impl<W: Write> Write for Bounded<W> {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            if bytes.len() > self.remaining {
                self.exhausted = true;
                return Err(io::Error::other("JSON limit"));
            }
            let written = self.inner.write(bytes)?;
            self.remaining -= written;
            Ok(written)
        }
        fn flush(&mut self) -> io::Result<()> {
            self.inner.flush()
        }
    }
    let mut bounded = Bounded {
        inner: writer,
        remaining: MAX_JSON_BYTES,
        exhausted: false,
    };
    serde_json::to_writer(&mut bounded, snapshot).map_err(|_| {
        ScopeError::new(if bounded.exhausted {
            ErrorCode::ResourceLimit
        } else {
            ErrorCode::InvalidArgument
        })
    })
}
fn invalid() -> ScopeError {
    ScopeError::new(ErrorCode::InvalidArgument)
}
fn text(value: &Observed<String>) -> Result<(), ScopeError> {
    if value.value().is_some_and(|text| {
        text.is_empty() || text.len() > 4096 || text.chars().any(char::is_control)
    }) {
        return Err(invalid());
    }
    Ok(())
}
fn list<T>(value: &Observed<Vec<T>>) -> Result<(), ScopeError> {
    if value.value().is_some_and(|items| items.len() > 1024) {
        return Err(invalid());
    }
    Ok(())
}
fn metadata(value: &str) -> Result<(), ScopeError> {
    if value.is_empty() || value.len() > 128 || value.chars().any(char::is_control) {
        return Err(invalid());
    }
    Ok(())
}
pub(crate) fn validate(snapshot: &Snapshot) -> Result<(), ScopeError> {
    if snapshot.schema_version != SCHEMA_VERSION
        || snapshot.capabilities.len() > 25
        || snapshot.issues.len() > 32
        || snapshot.conflicts.len() > 400
    {
        return Err(invalid());
    }
    let static_info = &snapshot.static_info;
    text(&static_info.system.os.name)?;
    text(&static_info.system.os.version)?;
    text(&static_info.system.os.kernel_version)?;
    text(&static_info.system.device.model)?;
    text(&static_info.system.device.vendor)?;
    text(&static_info.system.device.serial_number)?;
    text(&static_info.system.cpu.brand)?;
    text(&static_info.system.cpu.architecture)?;
    text(&static_info.system.motherboard.vendor)?;
    text(&static_info.system.motherboard.model)?;
    text(&static_info.system.firmware.vendor)?;
    text(&static_info.system.firmware.version)?;

    for count in [
        &static_info.system.cpu.logical_count,
        &static_info.system.cpu.physical_count,
    ] {
        if count.value() == Some(&0) {
            return Err(invalid());
        }
    }
    if static_info.system.memory.total_usable_bytes.value() == Some(&0)
        || static_info.system.memory.installed_bytes.value() == Some(&0)
    {
        return Err(invalid());
    }
    for cap in &snapshot.capabilities {
        metadata(&cap.field)?;
    }
    for issue in &snapshot.issues {
        metadata(&issue.backend)?;
    }
    for event in &snapshot.conflicts {
        metadata(&event.field)?;
    }
    list(&static_info.gpus)?;
    list(&static_info.storage)?;
    list(&static_info.displays)?;
    if let Some(items) = static_info.gpus.value() {
        for item in items {
            text(&item.name)?;
        }
    }
    if let Some(items) = static_info.storage.value() {
        for item in items {
            text(&item.name)?;
        }
    }
    if let Some(items) = static_info.displays.value() {
        for item in items {
            text(&item.name)?;
            if item.width_pixels.value() == Some(&0) || item.height_pixels.value() == Some(&0) {
                return Err(invalid());
            }
        }
    }
    let dynamic = &snapshot.dynamic;
    fn percent(value: &Observed<f64>) -> Result<(), ScopeError> {
        if value
            .value()
            .is_some_and(|number| !number.is_finite() || !(0.0..=100.0).contains(number))
        {
            return Err(invalid());
        }
        Ok(())
    }
    percent(&dynamic.cpu_usage_percent)?;
    if let (Some(available), Some(total)) = (
        dynamic.memory_available_bytes.value(),
        static_info.system.memory.total_usable_bytes.value(),
    ) && available > total
    {
        return Err(invalid());
    }
    list(&dynamic.batteries)?;
    list(&dynamic.sensors)?;
    list(&dynamic.networks)?;
    if let Some(items) = dynamic.batteries.value() {
        for item in items {
            percent(&item.charge_percent)?;
        }
    }
    if let Some(items) = dynamic.sensors.value() {
        for item in items {
            text(&item.label)?;
            if item
                .temperature_celsius
                .value()
                .is_some_and(|number| !number.is_finite() || !(-273.15..=1000.0).contains(number))
            {
                return Err(invalid());
            }
        }
    }
    if let Some(items) = dynamic.networks.value() {
        for item in items {
            text(&item.interface_name)?;
        }
    }
    Ok(())
}
