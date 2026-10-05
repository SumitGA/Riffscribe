"""Print a dev access token: `python -m api.devtoken alice [--ttl 3600]` (or `make token`).

Reads JWT_ISSUER and JWT_DEV_SECRET (and JWT_AUDIENCE if set) like the API does.
"""

import argparse

from api.auth import AuthSettings, issue_dev_token


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m api.devtoken", description=__doc__)
    parser.add_argument("user_id", help="becomes the token's `sub`")
    parser.add_argument("--ttl", type=int, default=3600, help="lifetime in seconds")
    args = parser.parse_args(argv)
    print(issue_dev_token(AuthSettings(), args.user_id, ttl_s=args.ttl))


if __name__ == "__main__":
    main()
