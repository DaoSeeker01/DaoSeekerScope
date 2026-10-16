//! Bounded stdin-driven refresh probe for kernel-enforced CI fixtures.
//! No fixture paths or identifiers are accepted by the production library.
#![forbid(unsafe_code)]
use daoseeker_scope::{Hardware, Options, PrivacyOptions, Timestamp, to_json};
use std::io::{self, BufRead, Read, Write};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut hardware = Hardware::new()?;
    let mut snapshot = hardware.collect()?;
    println!("{}", to_json(&snapshot)?);
    io::stdout().flush()?;
    let stdin = io::stdin();
    let mut input = stdin.lock();
    for _ in 0..64 {
        let mut command = String::new();
        if input.by_ref().take(16).read_line(&mut command)? == 0 {
            break;
        }
        if command == "quit\n" {
            return Ok(());
        }
        if command == "rebuild\n" || command == "authorize\n" {
            // Test probe only: explicit opt-in against synthetic, mounted fixtures.
            // Production callers still need their own authorization and OS access.
            hardware = if command == "authorize\n" {
                Hardware::with_options(Options {
                    privacy: PrivacyOptions {
                        include_sensitive: true,
                        caller_authorized: true,
                    },
                    ..Options::default()
                })?
            } else {
                Hardware::new()?
            };
            snapshot = hardware.collect()?;
            println!("{}", to_json(&snapshot)?);
            io::stdout().flush()?;
            continue;
        }
        if command != "refresh\n" {
            return Err("invalid probe command".into());
        }
        snapshot.dynamic = hardware.refresh_dynamic()?;
        snapshot.capabilities = hardware.capabilities();
        snapshot.collected_at = Timestamp::now()?;
        println!("{}", to_json(&snapshot)?);
        io::stdout().flush()?;
    }
    Ok(())
}
