from datetime import datetime, timezone
from pathlib import Path

import yaml


class MetadataFormatError(ValueError):
    """Raised when a ROS 2 metadata file cannot be normalized."""


_QOS_POLICIES = {
    "history": {
        0: "system_default",
        1: "keep_last",
        2: "keep_all",
        3: "unknown",
    },
    "reliability": {
        0: "system_default",
        1: "reliable",
        2: "best_effort",
        3: "unknown",
        4: "best_available",
    },
    "durability": {
        0: "system_default",
        1: "transient_local",
        2: "volatile",
        3: "unknown",
        4: "best_available",
    },
    "liveliness": {
        0: "system_default",
        1: "automatic",
        2: "manual_by_node",
        3: "manual_by_topic",
        4: "unknown",
        5: "best_available",
    },
}


def _mapping(value, field):
    if not isinstance(value, dict):
        raise MetadataFormatError(f"'{field}' must be a mapping.")
    return value


def _sequence(value, field):
    if not isinstance(value, list):
        raise MetadataFormatError(f"'{field}' must be a sequence.")
    return value


def _string(value, field):
    if not isinstance(value, str):
        raise MetadataFormatError(f"'{field}' must be a string.")
    return value


def _integer(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MetadataFormatError(f"'{field}' must be a non-negative integer.")
    return value


def _nanoseconds(value, field):
    value = _mapping(value, field)
    return _integer(value.get("nanoseconds"), f"{field}.nanoseconds")


def _timestamp_nanoseconds(value, field):
    value = _mapping(value, field)
    return _integer(
        value.get("nanoseconds_since_epoch"),
        f"{field}.nanoseconds_since_epoch",
    )


def _timestamp(value):
    seconds, nanoseconds = divmod(value, 1_000_000_000)
    try:
        date = datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as error:
        raise MetadataFormatError("'starting_time' is outside the supported range.") from error
    return f"{date:%Y-%m-%dT%H:%M:%S}.{nanoseconds:09d}Z"


def _duration(value):
    return {
        "nanoseconds": str(value),
        "seconds": value / 1_000_000_000,
    }


def _optional_string(value, field):
    if value is None or value == "":
        return None
    return _string(value, field)


def _qos_profiles(value, version):
    if value is None or value == "":
        return []

    if version < 9:
        if not isinstance(value, str):
            raise MetadataFormatError("'offered_qos_profiles' must be YAML text.")
        try:
            value = yaml.safe_load(value)
        except yaml.YAMLError as error:
            raise MetadataFormatError("Invalid QoS profile YAML.") from error

    profiles = _sequence(value, "offered_qos_profiles")
    normalized = []
    for profile in profiles:
        profile = dict(_mapping(profile, "offered_qos_profiles[]"))
        for field, names in _QOS_POLICIES.items():
            policy = profile.get(field)
            if isinstance(policy, int) and not isinstance(policy, bool):
                profile[field] = names.get(policy, "unknown")
            elif policy is not None and not isinstance(policy, str):
                raise MetadataFormatError(f"QoS policy '{field}' is invalid.")
        normalized.append(profile)
    return normalized


def _topic(value, version):
    value = _mapping(value, "topics_with_message_count[]")
    metadata = _mapping(value.get("topic_metadata"), "topic_metadata")
    return {
        "name": _string(metadata.get("name"), "topic_metadata.name"),
        "type": _string(metadata.get("type"), "topic_metadata.type"),
        "message_count": _integer(value.get("message_count"), "message_count"),
        "advanced": {
            "serialization_format": _string(
                metadata.get("serialization_format"),
                "topic_metadata.serialization_format",
            ),
            "type_description_hash": _optional_string(
                metadata.get("type_description_hash"),
                "topic_metadata.type_description_hash",
            ),
            "offered_qos_profiles": _qos_profiles(
                metadata.get("offered_qos_profiles"), version
            ),
        },
    }


def _files(info, version):
    if version < 5:
        paths = _sequence(info.get("relative_file_paths"), "relative_file_paths")
        return [
            {
                "path": _string(path, "relative_file_paths[]"),
                "started_at": None,
                "duration": None,
                "message_count": None,
            }
            for path in paths
        ]

    files = []
    for value in _sequence(info.get("files"), "files"):
        value = _mapping(value, "files[]")
        start = _timestamp_nanoseconds(
            value.get("starting_time"), "files[].starting_time"
        )
        duration = _nanoseconds(value.get("duration"), "files[].duration")
        files.append(
            {
                "path": _string(value.get("path"), "files[].path"),
                "started_at": _timestamp(start),
                "duration": _duration(duration),
                "message_count": _integer(
                    value.get("message_count"), "files[].message_count"
                ),
            }
        )
    return files


def parse_rosbag_metadata(path: Path):
    """Parse ROS 2 metadata.yaml versions 4-9 into the API representation."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise MetadataFormatError("metadata.yaml is not valid YAML.") from error
    except UnicodeError as error:
        raise MetadataFormatError("metadata.yaml is not valid UTF-8.") from error

    document = _mapping(document, "document")
    info = _mapping(
        document.get("rosbag2_bagfile_information"),
        "rosbag2_bagfile_information",
    )
    version = _integer(info.get("version"), "version")
    if version < 4 or version > 9:
        raise MetadataFormatError("Only ROS 2 metadata versions 4 through 9 are supported.")

    start = _timestamp_nanoseconds(info.get("starting_time"), "starting_time")
    duration = _nanoseconds(info.get("duration"), "duration")
    topics = [
        _topic(topic, version)
        for topic in _sequence(
            info.get("topics_with_message_count"), "topics_with_message_count"
        )
    ]

    compression_format = _optional_string(
        info.get("compression_format"), "compression_format"
    )
    compression_mode = _optional_string(
        info.get("compression_mode"), "compression_mode"
    )

    custom_data = info.get("custom_data")
    if custom_data is None:
        custom_data = {}
    custom_data = _mapping(custom_data, "custom_data")
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in custom_data.items()
    ):
        raise MetadataFormatError("'custom_data' must contain string keys and values.")

    return {
        "summary": {
            "started_at": _timestamp(start),
            "duration": _duration(duration),
            "message_count": _integer(info.get("message_count"), "message_count"),
            "topic_count": len(topics),
            "ros_distro": _optional_string(info.get("ros_distro"), "ros_distro"),
            "storage_identifier": _string(
                info.get("storage_identifier"), "storage_identifier"
            ),
            "compression": {
                "mode": compression_mode,
                "format": compression_format,
            },
        },
        "topics": topics,
        "files": _files(info, version),
        "advanced": {
            "metadata_version": version,
            "custom_data": custom_data,
        },
    }
