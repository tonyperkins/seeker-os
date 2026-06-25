"""Shared utility for writing key-value pairs to the .env file."""

from __future__ import annotations

import os


def write_env(updates: dict[str, str]) -> None:
    """Write key=value pairs to .env, updating existing keys.

    Also updates os.environ so changes take effect without a restart.
    """
    from seeker_os.config import PROJECT_ROOT

    env_path = PROJECT_ROOT / ".env"
    existing_env: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                existing_env[k.strip()] = v.strip()

    existing_env.update(updates)
    env_lines = [f"{k}={v}" for k, v in existing_env.items()]
    env_path.write_text("\n".join(env_lines) + "\n")

    os.environ.update(updates)
