# Aurora Serverless v2 that scales to zero

A small AWS CDK app that deploys one Aurora Serverless v2 PostgreSQL cluster per
environment, with minimum capacity 0 so each cluster pauses when idle and bills nothing
for compute. Built for testing and staging environments that see use a few times a
month, where a real managed Postgres for a few dollars beats signing up for yet another
database service.

While a cluster is paused you pay for storage, the credentials secret, and the public
IPv4 address if the cluster has one:

|                  | Per cluster, monthly |
| ---------------- | -------------------- |
| Storage, ~0.5 GB | $0.05                |
| Secrets Manager  | $0.40                |
| Public IPv4      | $3.65                |
| **Idle total**   | **~$4.10**           |

Drop the public IP (see [Go private](#go-private)) and an idle cluster costs under a
dollar a month. The trade-off is cold starts: the first connection after a pause takes
about 15 seconds, or 30 seconds and more once the cluster has been paused for over a
day.

Each cluster lands in the public subnets of its region's default VPC. This app is
deliberately not part of any application stack: keep it deployed on its own, so a
`cdk destroy` of your application cannot take the data with it.

## Prerequisites

- AWS credentials configured locally.
- The CDK CLI (`npm install -g aws-cdk`), with your account
  [bootstrapped](https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping.html) in each
  region you deploy to.
- [uv](https://docs.astral.sh/uv/). The CDK invokes the app through `uv run`, which
  installs the Python dependencies on first use.
- [just](https://github.com/casey/just) for the recipes below.
- Docker, only for `just psql`.

## Deploy

1. Edit `config.py`: set `PREFIX` to your project name and list your environments,
   one `(name, region, public)` row each.
2. Run `just diff` to see what a stack creates.
3. Run `just deploy testing`, substituting your environment name.

The stack outputs the cluster endpoint, the port, and the name of the Secrets Manager
secret that holds the generated credentials.

## Day to day

```bash
just              # list recipes
just status       # every cluster: paused or running
just capacity     # ACU over the last hour; a minimum of 0 means it paused
just endpoint     # stack outputs per environment
just psql testing # open a session (wakes the cluster, resets its idle timer)
```

`just psql` builds a connection URL from the secret and runs `psql` in a Docker
container, so nothing needs to be installed locally.

## Go private

A public IPv4 address bills whether or not the cluster is paused, so it dominates the
idle cost. To shed it, set `public` to `False` in the environment's row and redeploy.
The cluster is then reachable only from the CIDRs in `ALLOWED_CIDRS`.

The usual private setup is VPC peering: peer your application's VPC with the default
VPC the cluster lives in, add routes both ways, and put the application VPC's CIDR in
`ALLOWED_CIDRS`. The peering itself belongs to your application's network stacks, not
here.

## What stops a cluster pausing

Minimum capacity 0 is the auto-pause feature itself; at 0.5 a cluster never pauses and
bills ~$73/month. A cluster also stays awake while any connection is open (a forgotten
`psql` session counts), or when it uses an attached RDS Proxy, logical replication,
Global Database, zero-ETL integration with Redshift, or Babelfish.

The idle timer is one hour (`serverless_v2_auto_pause_duration` in `app.py`). Long
enough that a working session does not keep cold-starting, and the extra idle time
costs cents.

## Destroy

`cdk destroy` takes a final snapshot instead of deleting the data
(`RemovalPolicy.SNAPSHOT`). The snapshot bills for storage until you delete it from the
RDS console.

## License

[MIT](LICENSE)
