use label_studio_server::{api, config::Config};
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let config = Config::load()?;
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args
        .first()
        .is_some_and(|s| s == "power-get" || s == "power-set")
    {
        let minutes = if args[0] == "power-set" {
            Some(
                args.get(1)
                    .ok_or_else(|| anyhow::anyhow!("Usage: label-studio-server power-set MINUTES"))?
                    .parse::<u8>()?,
            )
        } else {
            None
        };
        println!(
            "{}",
            serde_json::to_string_pretty(&label_studio_server::power::power(&config, minutes)?)?
        );
        return Ok(());
    }
    anyhow::ensure!(
        args.is_empty(),
        "Unknown command. Use power-get or power-set MINUTES, or no arguments to serve."
    );
    let host = std::env::var("SERVER_HOST").unwrap_or_else(|_| "127.0.0.1".into());
    let port = std::env::var("SERVER_PORT")
        .unwrap_or_else(|_| "8016".into())
        .parse::<u16>()?;
    let app = api::router(config)?;
    let listener = tokio::net::TcpListener::bind((host.as_str(), port)).await?;
    eprintln!("Label Studio listening on http://{host}:{port}/studio/");
    axum::serve(listener, app)
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await?;
    Ok(())
}
