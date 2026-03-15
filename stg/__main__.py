"""
STG CLI entry point
"""
import uvicorn
from stg.config import config


def main():
    """Start the STG proxy server"""
    print(f"Starting Smart Token Gateway on port {config.gateway_port}")
    print(f"Upstream API: {config.upstream_base_url}")
    print(f"Compression threshold: {config.compressor_threshold_tokens} tokens")
    print(f"Summary max tokens: {config.compressor_summary_max_tokens} tokens")

    uvicorn.run(
        "stg.proxy:app",
        host="0.0.0.0",
        port=config.gateway_port,
        log_level="info"
    )


if __name__ == "__main__":
    main()
