//! Bounded CLI argument parsing, independent of hardware collection.
#![forbid(unsafe_code)]
use daoseeker_scope::Options;

pub const MAX_ARGUMENTS: usize = 8;
pub const MAX_ARGUMENT_BYTES: usize = 256;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Command {
    Cpu,
    Memory,
    Gpu,
    Disk,
    Network,
    Battery,
    Sensors,
    System,
    Capabilities,
    /// Display views reported by the OS, not a physical monitor count.
    Display,
}

#[derive(Debug)]
pub enum Invocation {
    Help,
    Version,
    Collect {
        command: Command,
        json: bool,
        options: Options,
    },
}

/// Rejects unknown/duplicate arguments and sensitive requests without authorization.
/// Does not collect hardware or print input in errors.
pub fn parse_args(args: &[String]) -> Result<Invocation, &'static str> {
    if args.len() > MAX_ARGUMENTS || args.iter().any(|arg| arg.len() > MAX_ARGUMENT_BYTES) {
        return Err("invalid arguments");
    }
    if args == ["--help"] || args == ["-h"] {
        return Ok(Invocation::Help);
    }
    if args == ["--version"] || args == ["-V"] {
        return Ok(Invocation::Version);
    }
    let mut command = None;
    let mut json = false;
    let mut options = Options::default();
    for arg in args {
        let selected = match arg.as_str() {
            "cpu" => Command::Cpu,
            "memory" => Command::Memory,
            "gpu" => Command::Gpu,
            "disk" => Command::Disk,
            "network" => Command::Network,
            "battery" => Command::Battery,
            "sensors" => Command::Sensors,
            "system" => Command::System,
            "capabilities" => Command::Capabilities,
            "display" => Command::Display,
            "--json" if !json => {
                json = true;
                continue;
            }
            "--include-sensitive" if !options.privacy.include_sensitive => {
                options.privacy.include_sensitive = true;
                continue;
            }
            "--authorized" if !options.privacy.caller_authorized => {
                options.privacy.caller_authorized = true;
                continue;
            }
            _ => return Err("invalid argument; use --help"),
        };
        if command.replace(selected).is_some() {
            return Err("invalid argument; use --help");
        }
    }
    if options.privacy.include_sensitive && !options.privacy.caller_authorized {
        return Err(
            "--include-sensitive requires --authorized; confirm authorization before requesting identifiers",
        );
    }
    options
        .validate()
        .map_err(|_| "invalid options; use --help")?;
    Ok(Invocation::Collect {
        command: command.unwrap_or(Command::System),
        json,
        options,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    fn parse(args: &[&str]) -> Result<Invocation, &'static str> {
        parse_args(&args.iter().map(|arg| (*arg).to_owned()).collect::<Vec<_>>())
    }
    #[test]
    fn validates_commands_limits_and_privacy_before_collecting() {
        for command in [
            "cpu",
            "memory",
            "gpu",
            "disk",
            "network",
            "battery",
            "sensors",
            "system",
            "capabilities",
            "display",
        ] {
            let Invocation::Collect { json, options, .. } =
                parse(&[command, "--json"]).expect("command")
            else {
                panic!("collect")
            };
            assert!(json);
            assert!(!options.privacy.permits_sensitive());
        }
        assert!(matches!(parse(&["--help"]), Ok(Invocation::Help)));
        assert!(matches!(parse(&["--version"]), Ok(Invocation::Version)));
        for args in [
            vec!["cpu", "memory"],
            vec!["--json", "--json"],
            vec!["--help", "cpu"],
            vec!["--include-sensitive"],
            vec!["--authorized", "--authorized"],
            vec!["cpu"; 9],
        ] {
            assert!(parse(&args).is_err());
        }
        assert!(parse_args(&["x".repeat(MAX_ARGUMENT_BYTES + 1)]).is_err());
        let Invocation::Collect { options, .. } =
            parse(&["--authorized", "--include-sensitive"]).expect("authorized")
        else {
            panic!("collect")
        };
        assert!(options.privacy.permits_sensitive());
    }
    #[test]
    fn bounded_arbitrary_inputs_never_enable_sensitive_access() {
        for byte in 0..=255u8 {
            let args = vec![String::from_utf8_lossy(&[byte; MAX_ARGUMENT_BYTES]).into_owned()];
            assert!(parse_args(&args).is_err());
        }
        let alphabet = [
            "cpu",
            "--json",
            "--include-sensitive",
            "--authorized",
            "--help",
            "",
            "\0",
            "未知",
        ];
        for bits in 0..4096usize {
            let args = (0..4)
                .map(|i| alphabet[(bits >> (i * 3)) & 7].to_owned())
                .collect::<Vec<_>>();
            if let Ok(Invocation::Collect { options, .. }) = parse_args(&args) {
                assert!(!options.privacy.include_sensitive || options.privacy.caller_authorized);
                options.validate().expect("validated options");
            }
        }
    }
    #[test]
    fn display_selection_preserves_json_and_explicit_privacy_contract() {
        for args in [vec!["display"], vec!["--json", "display"]] {
            let Invocation::Collect {
                command,
                json,
                options,
            } = parse(&args).expect("display")
            else {
                panic!("collect")
            };
            assert_eq!(command, Command::Display);
            assert_eq!(json, args.contains(&"--json"));
            assert!(!options.privacy.permits_sensitive());
        }
        assert!(parse(&["display", "display"]).is_err());
        assert!(parse(&["display", "cpu"]).is_err());
        assert!(parse(&["display", "--include-sensitive"]).is_err());
        let Invocation::Collect {
            command, options, ..
        } = parse(&["display", "--include-sensitive", "--authorized"]).expect("authorized")
        else {
            panic!("collect")
        };
        assert_eq!(command, Command::Display);
        assert!(options.privacy.permits_sensitive());
    }
}
