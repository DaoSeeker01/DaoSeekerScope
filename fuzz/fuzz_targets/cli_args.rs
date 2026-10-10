#![no_main]
libfuzzer_sys::fuzz_target!(|data: &[u8]| {
    if data.len() > 8192 {
        return;
    }
    if let Ok(text) = std::str::from_utf8(data) {
        let args = text
            .split('\n')
            .take(9)
            .map(str::to_owned)
            .collect::<Vec<_>>();
        if let Ok(daoseeker_scope_cli::Invocation::Collect { options, .. }) =
            daoseeker_scope_cli::parse_args(&args)
        {
            options.validate().expect("accepted options validate");
            assert!(!options.privacy.include_sensitive || options.privacy.caller_authorized);
        }
    }
});
