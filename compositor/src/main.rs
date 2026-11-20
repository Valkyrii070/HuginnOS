//! huginn-compositor: Huginn OS's own Wayland compositor.
//!
//!     huginn-compositor            on the computer's screens (a session started from the sign-in screen)
//!     huginn-compositor --winit    in a window of another desktop (testing)

fn main() {
    // To stderr: the sign-in screen sends a session's stdout nowhere and its stderr to
    // ~/.local/share/sddm/wayland-session.log, which problem reports (huginn-report) read. Plain text there.
    use std::io::IsTerminal;
    let filter = tracing_subscriber::EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info"));
    tracing_subscriber::fmt()
        .compact()
        .with_writer(std::io::stderr)
        .with_ansi(std::io::stderr().is_terminal())
        .with_env_filter(filter)
        .init();
    profiling::register_thread!("Main Thread");

    let mut args: Vec<String> = std::env::args().skip(1).collect();
    if let Some(i) = args.iter().position(|a| a == "--") {
        let session = args.split_off(i + 1);
        args.pop();
        let _ = huginn_compositor::huginn::SESSION.set(session);
    }
    if args.iter().any(|a| a == "--help" || a == "-h") {
        #[allow(clippy::disallowed_macros)]
        {
            println!("huginn-compositor [--winit] [-- SESSION COMMAND…]");
            println!("  (no option)  run on the computer's screens, from a session");
            println!("  --winit      run in a window of another desktop, for testing");
            println!("  -- COMMAND   start this once listening (WAYLAND_DISPLAY and DISPLAY set); end when it ends");
        }
        return;
    }
    if args.iter().any(|a| a == "--winit") {
        #[cfg(feature = "winit")]
        {
            tracing::info!("Starting in a window (winit)");
            huginn_compositor::winit::run_winit();
        }
        return;
    }
    #[cfg(feature = "udev")]
    {
        tracing::info!("Starting on the computer's screens (udev)");
        huginn_compositor::udev::run_udev();
    }
}
