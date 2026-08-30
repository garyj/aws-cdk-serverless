"""Deployment settings. Every stack, cluster, database, and secret name derives from these."""

from typing import NamedTuple

# Lowercase letters and digits only; it is embedded in database names, which
# cannot contain hyphens.
PREFIX = 'myapp'

MASTER_USERNAME = 'dbadmin'

# Not 5432, because the endpoint may be public and scanners look for the default.
PORT = 36784

# CIDRs that can reach every cluster, such as a peered application VPC.
ALLOWED_CIDRS = ()


class DatabaseEnvironment(NamedTuple):
    name: str
    region: str
    # A public writer gets an IPv4 address, which bills even while the cluster is paused.
    public: bool
    # Idle minutes before the cluster pauses. Waking it again takes 15 seconds and up.
    auto_pause_minutes: int


ENVIRONMENTS = (
    DatabaseEnvironment(
        name='Testing',
        region='ap-southeast-2',
        public=True,
        auto_pause_minutes=15,
    ),
    DatabaseEnvironment(
        name='Staging',
        region='ap-southeast-1',
        public=True,
        auto_pause_minutes=15,
    ),
)
