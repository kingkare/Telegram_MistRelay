"""Fail-closed handling for the retired YAML configuration path."""

import os
import stat
import tempfile
from pathlib import Path

import yaml


LEGACY_BOOTSTRAP_ENV = "MISTRELAY_ALLOW_LEGACY_YAML_BOOTSTRAP"
MAX_LEGACY_CONFIG_BYTES = 64 * 1024
RETIRED_CONFIG_CONTENT = (
    "# Legacy configuration retired after secure database migration.\n"
    "{}\n"
)


class LegacyConfigError(RuntimeError):
    pass


def legacy_yaml_bootstrap_enabled() -> bool:
    """Require an exact, explicit opt-in; absence and all other values fail closed."""
    return os.environ.get(LEGACY_BOOTSTRAP_ENV) == "1"


def legacy_config_path(database_path: str | Path) -> Path:
    return Path(database_path).with_name("config.yml")


def _regular_owner_only_file(path: Path) -> os.stat_result:
    try:
        file_stat = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise LegacyConfigError(f"cannot access legacy configuration: {exc}") from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise LegacyConfigError("legacy configuration must be a regular file")
    if file_stat.st_uid != os.geteuid():
        raise LegacyConfigError("legacy configuration must be owned by the runtime user")
    if stat.S_IMODE(file_stat.st_mode) & 0o077:
        raise LegacyConfigError("legacy configuration permissions must be 0600 or stricter")
    if file_stat.st_size <= 0 or file_stat.st_size > MAX_LEGACY_CONFIG_BYTES:
        raise LegacyConfigError("legacy configuration size is invalid")
    return file_stat


def load_legacy_config(path: str | Path) -> dict:
    if not legacy_yaml_bootstrap_enabled():
        raise LegacyConfigError("legacy YAML bootstrap is not explicitly enabled")
    config_path = Path(path)
    _regular_owner_only_file(config_path)
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise LegacyConfigError("legacy configuration is unreadable or invalid") from exc
    if not isinstance(config, dict):
        raise LegacyConfigError("legacy configuration must contain a YAML mapping")
    return config


def retire_legacy_config(path: str | Path) -> bool:
    """Atomically replace a legacy config with a non-secret inert document."""
    config_path = Path(path)
    try:
        file_stat = config_path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise LegacyConfigError(f"cannot access legacy configuration: {exc}") from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise LegacyConfigError("refusing to retire a non-regular legacy configuration")
    if file_stat.st_nlink != 1:
        raise LegacyConfigError("refusing to retire a hard-linked legacy configuration")

    parent = config_path.parent
    try:
        parent_stat = parent.stat(follow_symlinks=False)
    except OSError as exc:
        raise LegacyConfigError(f"cannot access legacy configuration directory: {exc}") from exc
    if not stat.S_ISDIR(parent_stat.st_mode):
        raise LegacyConfigError("legacy configuration parent must be a real directory")

    temp_fd = -1
    temp_name = None
    try:
        temp_fd, temp_name = tempfile.mkstemp(
            prefix=f".{config_path.name}.retired-",
            dir=parent,
        )
        os.fchmod(temp_fd, 0o600)
        if os.geteuid() == 0:
            os.fchown(temp_fd, file_stat.st_uid, file_stat.st_gid)
        with os.fdopen(temp_fd, "w", encoding="utf-8", closefd=True) as handle:
            temp_fd = -1
            handle.write(RETIRED_CONFIG_CONTENT)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, config_path)
        temp_name = None
        directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise LegacyConfigError(f"cannot retire legacy configuration: {exc}") from exc
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
    return True
