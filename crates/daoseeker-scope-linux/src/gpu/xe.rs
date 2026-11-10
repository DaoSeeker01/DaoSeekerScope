//! Intel Xe device-local memory from the DRM memory-regions query.
use super::{RenderNode, invalid, unsupported};
use daoseeker_scope_core::{Observed, ReasonCode, ScopeError, Source};
use std::path::Path;

pub(super) fn collect(
    drm_root: &Path,
    device: &Path,
    render_node: RenderNode,
    check: &mut impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<u64>, ScopeError> {
    if !cfg!(all(
        target_os = "linux",
        target_pointer_width = "64",
        any(target_arch = "x86_64", target_arch = "aarch64")
    )) {
        return Ok(unsupported());
    }
    let minor = match render_node {
        RenderNode::Missing => {
            return Ok(Observed::unavailable(Source::Drm, ReasonCode::NotPresent));
        }
        RenderNode::Unique(minor) => minor,
        RenderNode::Ambiguous => return Ok(invalid(Source::Drm)),
    };
    query(drm_root, device, minor, check)
}

#[cfg(not(all(
    target_os = "linux",
    target_pointer_width = "64",
    any(target_arch = "x86_64", target_arch = "aarch64")
)))]
fn query(
    _drm_root: &Path,
    _device: &Path,
    _minor: u32,
    _check: &mut impl FnMut() -> Result<(), ScopeError>,
) -> Result<Observed<u64>, ScopeError> {
    Ok(unsupported())
}

#[cfg(all(
    target_os = "linux",
    target_pointer_width = "64",
    any(target_arch = "x86_64", target_arch = "aarch64")
))]
use native::query;

#[cfg(all(
    target_os = "linux",
    target_pointer_width = "64",
    any(target_arch = "x86_64", target_arch = "aarch64")
))]
mod native {
    use super::*;
    use daoseeker_scope_core::Timestamp;
    use std::{
        fs::{self, File, Metadata, OpenOptions},
        io,
        os::{
            fd::AsRawFd,
            unix::fs::{FileTypeExt, MetadataExt, OpenOptionsExt},
        },
        ptr,
    };

    const DRM_MAJOR: u32 = 226;
    const FIRST_RENDER_MINOR: u32 = 128;
    const REGION_HEADER: usize = 8;
    const REGION_SIZE: usize = 88;
    const MAX_REGIONS: usize = 32;
    const MAX_PAYLOAD: usize = REGION_HEADER + MAX_REGIONS * REGION_SIZE;
    const MEM_REGIONS: u32 = 1;

    // Linux v6.12 include/uapi/drm/{drm,xe_drm}.h, native LP64 layout.
    #[repr(C)]
    struct DrmVersion {
        major: libc::c_int,
        minor: libc::c_int,
        patch: libc::c_int,
        name_len: usize,
        name: *mut u8,
        date_len: usize,
        date: *mut u8,
        desc_len: usize,
        desc: *mut u8,
    }

    #[repr(C)]
    struct DeviceQuery {
        extensions: u64,
        query: u32,
        size: u32,
        data: u64,
        reserved: [u64; 2],
    }

    #[repr(align(8))]
    struct Payload([u8; MAX_PAYLOAD]);

    // _IOWR('d', nr, type) on x86_64 and arm64.
    const fn drm_iowr<T>(nr: u32) -> u32 {
        (3 << 30) | ((size_of::<T>() as u32) << 16) | ((b'd' as u32) << 8) | nr
    }
    const DRM_VERSION: u32 = drm_iowr::<DrmVersion>(0);
    const XE_DEVICE_QUERY: u32 = drm_iowr::<DeviceQuery>(0x40);
    const _: () = {
        assert!(size_of::<DrmVersion>() == 64);
        assert!(std::mem::offset_of!(DrmVersion, name_len) == 16);
        assert!(size_of::<DeviceQuery>() == 40);
        assert!(std::mem::offset_of!(DeviceQuery, data) == 16);
        assert!(DRM_VERSION == 0xc040_6400);
        assert!(XE_DEVICE_QUERY == 0xc028_6440);
    };

    #[allow(unsafe_code)]
    fn verify_driver(file: &File) -> io::Result<bool> {
        let mut name = [0; 2];
        let mut version = DrmVersion {
            major: 0,
            minor: 0,
            patch: 0,
            name_len: name.len(),
            name: name.as_mut_ptr(),
            date_len: 0,
            date: ptr::null_mut(),
            desc_len: 0,
            desc: ptr::null_mut(),
        };
        // SAFETY: the request matches DrmVersion. The kernel may write at most
        // name_len bytes to the live name buffer. The unused string lengths are zero.
        let result = unsafe { libc::ioctl(file.as_raw_fd(), DRM_VERSION as _, &raw mut version) };
        if result != 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(version.name_len == name.len() && name == *b"xe")
    }

    #[allow(unsafe_code)]
    fn query_regions(file: &File, output: Option<&mut [u8]>) -> io::Result<usize> {
        let (size, data) = output
            .map(|bytes| (bytes.len() as u32, bytes.as_mut_ptr() as u64))
            .unwrap_or((0, 0));
        let mut query = DeviceQuery {
            extensions: 0,
            query: MEM_REGIONS,
            size,
            data,
            reserved: [0; 2],
        };
        // SAFETY: the caller verified the Xe driver on this live descriptor.
        // A zero size requests the required length without dereferencing data.
        // Otherwise data points to an exclusive, writable slice of exactly size bytes.
        let result = unsafe { libc::ioctl(file.as_raw_fd(), XE_DEVICE_QUERY as _, &raw mut query) };
        if result != 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(query.size as usize)
    }

    fn render_device(metadata: &Metadata, minor: u32) -> bool {
        metadata.file_type().is_char_device()
            && libc::major(metadata.rdev()) == DRM_MAJOR
            && libc::minor(metadata.rdev()) == minor
    }

    fn open_render(path: &Path, minor: u32) -> io::Result<File> {
        if !render_device(&fs::symlink_metadata(path)?, minor) {
            return Err(io::ErrorKind::InvalidData.into());
        }
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_NOCTTY)
            .open(path)?;
        if !render_device(&file.metadata()?, minor) {
            return Err(io::ErrorKind::Interrupted.into());
        }
        Ok(file)
    }

    fn ioctl_failure(error: io::Error) -> Observed<u64> {
        match error.raw_os_error() {
            Some(libc::ENOTTY | libc::EOPNOTSUPP) => unsupported(),
            Some(libc::ENODEV | libc::ENXIO) => {
                Observed::unavailable(Source::Drm, ReasonCode::NotPresent)
            }
            Some(libc::EAGAIN | libc::ENOMEM | libc::EBUSY) => {
                Observed::unavailable(Source::Drm, ReasonCode::TemporarilyUnavailable)
            }
            Some(libc::EINVAL | libc::ENOSPC) => invalid(Source::Drm),
            _ => super::super::failure(error.kind(), Source::Drm),
        }
    }

    fn valid_size(size: usize) -> bool {
        (REGION_HEADER + REGION_SIZE..=MAX_PAYLOAD).contains(&size)
            && (size - REGION_HEADER).is_multiple_of(REGION_SIZE)
    }

    fn capacity(bytes: &[u8]) -> Option<Option<u64>> {
        if !valid_size(bytes.len()) {
            return None;
        }
        let (header, entries) = bytes.split_at(REGION_HEADER);
        let count = u32::from_ne_bytes(header[..4].try_into().ok()?) as usize;
        if count != entries.len() / REGION_SIZE || header[4..] != [0; 4] {
            return None;
        }
        let mut instances = 0u64;
        let mut total = None::<u64>;
        for entry in entries.chunks_exact(REGION_SIZE) {
            let class = u16::from_ne_bytes(entry[..2].try_into().ok()?);
            let instance = u16::from_ne_bytes(entry[2..4].try_into().ok()?);
            let bit = 1u64.checked_shl(u32::from(instance))?;
            if instances & bit != 0 {
                return None;
            }
            instances |= bit;
            match class {
                0 => {} // System memory is shared with the CPU.
                1 => {
                    let bytes = u64::from_ne_bytes(entry[8..16].try_into().ok()?);
                    total = Some(total.unwrap_or(0).checked_add(bytes)?);
                }
                _ => return None,
            }
        }
        Some(total)
    }

    pub(super) fn query(
        drm_root: &Path,
        device: &Path,
        minor: u32,
        check: &mut impl FnMut() -> Result<(), ScopeError>,
    ) -> Result<Observed<u64>, ScopeError> {
        if minor < FIRST_RENDER_MINOR {
            return Ok(invalid(Source::Drm));
        }
        let node = format!("renderD{minor}");
        check()?;
        let file = open_render(&Path::new("/dev/dri").join(&node), minor);
        check()?;
        let file = match file {
            Ok(file) => file,
            Err(error) => return Ok(ioctl_failure(error)),
        };
        let bound_device = fs::canonicalize(drm_root.join(node).join("device"));
        check()?;
        match bound_device {
            Ok(path) if path == device => {}
            Ok(_) => {
                return Ok(Observed::unavailable(
                    Source::Drm,
                    ReasonCode::TemporarilyUnavailable,
                ));
            }
            Err(error) => return Ok(super::super::failure(error.kind(), Source::Drm)),
        }
        let verified = verify_driver(&file);
        check()?;
        match verified {
            Ok(true) => {}
            Ok(false) => {
                return Ok(Observed::unavailable(
                    Source::Drm,
                    ReasonCode::TemporarilyUnavailable,
                ));
            }
            Err(error) => return Ok(ioctl_failure(error)),
        }
        read_capacity(|output| query_regions(&file, output), check)
    }

    fn read_capacity(
        mut query: impl FnMut(Option<&mut [u8]>) -> io::Result<usize>,
        check: &mut impl FnMut() -> Result<(), ScopeError>,
    ) -> Result<Observed<u64>, ScopeError> {
        let size = query(None);
        check()?;
        let size = match size {
            Ok(size) if valid_size(size) => size,
            Ok(_) => return Ok(invalid(Source::Drm)),
            Err(error) => return Ok(ioctl_failure(error)),
        };
        let mut payload = Payload([0; MAX_PAYLOAD]);
        let bytes = &mut payload.0[..size];
        let result = query(Some(bytes));
        check()?;
        Ok(match result {
            Ok(actual) if actual == size => match capacity(bytes) {
                Some(Some(value)) => Observed::available(value, Source::Drm, Timestamp::now()?),
                Some(None) => Observed::not_applicable(Source::Drm),
                None => invalid(Source::Drm),
            },
            Ok(_) => invalid(Source::Drm),
            Err(error) => ioctl_failure(error),
        })
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        use daoseeker_scope_core::Availability;

        fn response(regions: &[(u16, u16, u64)]) -> Vec<u8> {
            let mut bytes = vec![0; REGION_HEADER + regions.len() * REGION_SIZE];
            bytes[..4].copy_from_slice(&(regions.len() as u32).to_ne_bytes());
            for (entry, &(class, instance, total)) in bytes[REGION_HEADER..]
                .chunks_exact_mut(REGION_SIZE)
                .zip(regions)
            {
                entry[..2].copy_from_slice(&class.to_ne_bytes());
                entry[2..4].copy_from_slice(&instance.to_ne_bytes());
                entry[8..16].copy_from_slice(&total.to_ne_bytes());
                entry[16..40].fill(0x55); // Usage and CPU-visible fields are irrelevant.
            }
            bytes
        }

        #[test]
        fn sums_device_local_regions_without_system_or_visible_memory() {
            assert_eq!(capacity(&response(&[(0, 0, u64::MAX)])), Some(None));
            assert_eq!(capacity(&response(&[(1, 0, 0)])), Some(Some(0)));
            assert_eq!(
                capacity(&response(&[(1, 4, 4096), (0, 0, u64::MAX), (1, 1, 8192)])),
                Some(Some(12288))
            );
        }

        #[test]
        fn invalid_or_oversized_responses_never_return_a_partial_sum() {
            for regions in [
                &[][..],
                &[(1, 0, 4096), (1, 0, 8192)],
                &[(1, 0, 4096), (2, 1, 8192)],
                &[(1, 0, 4096), (1, 64, 8192)],
                &[(1, 0, u64::MAX), (1, 1, 1)],
                &[(1, 0, 4096); MAX_REGIONS + 1],
            ] {
                assert_eq!(capacity(&response(regions)), None);
            }
            let mut bytes = response(&[(1, 0, 4096)]);
            assert_eq!(capacity(&bytes[..bytes.len() - 1]), None);
            bytes[..4].copy_from_slice(&2u32.to_ne_bytes());
            assert_eq!(capacity(&bytes), None);
            assert!(!valid_size(usize::MAX));
        }

        #[test]
        fn foreign_character_device_is_rejected_before_driver_query() {
            let path = Path::new("/dev/null");
            assert_eq!(
                open_render(path, 128).unwrap_err().kind(),
                io::ErrorKind::InvalidData
            );
            let file = File::open(path).unwrap();
            let result = ioctl_failure(verify_driver(&file).unwrap_err());
            assert_eq!(result.availability(), Availability::Unsupported);
            assert_eq!(result.reason(), Some(ReasonCode::NotSupported));
            assert_eq!(
                ioctl_failure(io::Error::from_raw_os_error(libc::EACCES)).availability(),
                Availability::Restricted
            );
        }

        #[test]
        fn size_handshake_bounds_the_second_request_and_keeps_observation_status() {
            let value = read_capacity(
                |output| match output {
                    None => Ok(MAX_PAYLOAD + 1),
                    Some(_) => panic!("invalid length must stop the query"),
                },
                &mut || Ok(()),
            )
            .unwrap();
            assert_eq!(value.reason(), Some(ReasonCode::InvalidData));

            let cancelled = read_capacity(
                |output| {
                    assert!(
                        output.is_none(),
                        "cancellation must stop the payload request"
                    );
                    Ok(REGION_HEADER + REGION_SIZE)
                },
                &mut || Err(ScopeError::new(daoseeker_scope_core::ErrorCode::Cancelled)),
            )
            .unwrap_err();
            assert_eq!(cancelled.code, daoseeker_scope_core::ErrorCode::Cancelled);

            for (regions, expected) in [
                (&[(0, 0, 123)][..], None),
                (&[(0, 0, 123), (1, 1, 4096)][..], Some(4096)),
            ] {
                let bytes = response(regions);
                let mut requests = 0;
                let value = read_capacity(
                    |output| {
                        requests += 1;
                        if let Some(output) = output {
                            output.copy_from_slice(&bytes);
                        }
                        Ok(bytes.len())
                    },
                    &mut || Ok(()),
                )
                .unwrap();
                assert_eq!(requests, 2);
                assert_eq!(value.source(), Source::Drm);
                assert_eq!(value.value().copied(), expected);
                if expected.is_some() {
                    assert_eq!(value.availability(), Availability::Available);
                    assert!(value.observed_at().is_some());
                } else {
                    assert_eq!(value.availability(), Availability::NotApplicable);
                    assert_eq!(value.reason(), Some(ReasonCode::NotPresent));
                }
            }
        }
    }
}
