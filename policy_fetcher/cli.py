import argparse
import asyncio
import logging
import sys
from pathlib import Path

import policy_fetcher.fetcher as fetcher


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S"
    )


async def main():
    parser = argparse.ArgumentParser(description="Mastodon Policy Fetcher Utility")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--server-list", type=Path, help="Path to a text file with domains (one per line)")
    group.add_argument("--fetch", type=str, help="Single domain to fetch")
    group.add_argument("--cached", type=str, help="Read a single domain from cache only")

    parser.add_argument("--version", action="store_true", help="Show version info")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")

    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger("cli")

    if args.version:
        print("Mastodon Policy Fetcher v1.0.0")
        return

    # Default storage directory
    policy_dir = Path("policies")

    try:
        if args.cached:
            content = await fetcher.get_cached_policy(args.cached, policy_dir)
            if content:
                print(f"--- Cached Policy for {args.cached} ---")
                print(content[:500] + "... (truncated)")
            else:
                logger.warning(f"No cached policy found for {args.cached}")
                sys.exit(1)

        elif args.fetch:
            content = await fetcher.fetch_policy(args.fetch, policy_dir)
            print(f"--- Policy for {args.fetch} ---")
            print(content[:200] + "...")
            logger.info("Fetch complete.")

        elif args.server_list:
            if not args.server_list.exists():
                logger.error(f"Server list file not found: {args.server_list}")
                sys.exit(1)

            # Read domains from file (blocking read is okay in CLI startup)
            raw_content = args.server_list.read_text(encoding="utf-8")
            domains = [line.strip() for line in raw_content.splitlines() if line.strip()]

            await fetcher.fetch_many(domains, policy_dir)
            logger.info("Batch processing complete.")

        else:
            parser.print_help()

    except fetcher.PolicyFetchError as e:
        logger.error(f"Operation failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")