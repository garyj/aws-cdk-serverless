"""Deployment settings. Every stack, cluster, database, and secret name derives from these."""

# Lowercase letters and digits only; it is embedded in database names, which
# cannot contain hyphens.
PREFIX = 'myapp'

MASTER_USERNAME = 'dbadmin'

# Not 5432, because the endpoint may be public and scanners look for the default.
PORT = 36784

# CIDRs that can reach every cluster, such as a peered application VPC.
ALLOWED_CIDRS = ()

# (name, region, public). public=True gives the writer a public IP so anything
# can reach the endpoint; the IPv4 address bills even while the cluster is paused.
ENVIRONMENTS = (
    ('Testing', 'ap-southeast-2', True),
    ('Staging', 'ap-southeast-1', True),
)
