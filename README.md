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

## Quick start

Required:

- [uv](https://docs.astral.sh/uv/). The CDK runs the app through it, which installs the
  Python dependencies on first use.
- The CDK CLI: `npm install -g aws-cdk`.
- AWS credentials for the account you are deploying into.

Optional:

- The [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html),
  for `aws sso login` and for everything under [Day to day](#day-to-day). Deploying does
  not need it, because the CDK reads your credentials itself.
- [just](https://github.com/casey/just), for the recipes.
- `jq`, to build a connection URL out of the generated secret.
- A Postgres client, to connect. `just psql` runs one in Docker instead.

```bash
git clone https://github.com/garyj/aws-cdk-serverless
cd aws-cdk-serverless
```

Open `config.py` and set `PREFIX` to something short and specific to your project. It
names every stack, cluster, database, and secret. Then list your environments, one
`DatabaseEnvironment` each, and delete the ones you do not want.

Give the CDK credentials. Any method the AWS CLI understands works, including
`AWS_PROFILE` and `aws sso login`:

```bash
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
```

Bootstrap once per account and region, then deploy. Neither command needs arguments
naming your regions, because the CDK reads them from `config.py`:

```bash
cdk bootstrap
cdk ls                            # your stack names, e.g. myapp-testing-database
cdk deploy myapp-testing-database # or: cdk deploy --all
```

Creating a cluster takes about 10 minutes. When it finishes, the stack outputs the
endpoint, the port, and the name of the Secrets Manager secret holding the generated
credentials.

Each cluster needs a default VPC in its region. Every AWS account starts with one, but
if yours was deleted, recreate it with
`aws ec2 create-default-vpc --region <region>` before deploying.

## Day to day

These are plain AWS CLI calls. Substitute your own prefix, environment, and region.

Read the stack outputs:

```bash
aws cloudformation describe-stacks --region ap-southeast-2 \
    --stack-name myapp-testing-database \
    --query 'Stacks[0].Outputs' --output table
```

Check whether a cluster has paused. `ServerlessDatabaseCapacity` reads 0 while paused,
and reports nothing at all until the cluster has run once:

```bash
aws cloudwatch get-metric-statistics --region ap-southeast-2 \
    --namespace AWS/RDS --metric-name ServerlessDatabaseCapacity \
    --dimensions Name=DBClusterIdentifier,Value=myapp-testing \
    --start-time "$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)" \
    --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --period 60 --statistics Minimum Maximum --output table
```

That `date` call is GNU. On macOS, use `date -u -v-1H +%Y-%m-%dT%H:%M:%SZ` instead.

Build a connection URL from the secret and open a session, from any machine that can
reach the endpoint. Connecting wakes the cluster and resets its idle timer:

```bash
url=$(aws secretsmanager get-secret-value --region ap-southeast-2 \
    --secret-id myapp-testing-db --query SecretString --output text \
    | jq -r '"postgresql://\(.username):\(.password)@\(.host):\(.port)/\(.dbname)"')
psql "$url"
```

### With just

[just](https://github.com/casey/just) is a convenience, not a requirement. The recipes
read `config.py`, so they fill in the prefix, stack names, and regions for you:

```bash
just              # list recipes
just status       # every cluster: paused or running
just capacity     # ACU over the last hour; a minimum of 0 means it paused
just endpoint     # stack outputs per environment
just psql testing # open a session
```

`just psql` runs `psql` in a Docker container. It is the only recipe that needs Docker.

## Go private

A public IPv4 address bills whether or not the cluster is paused, so it dominates the
idle cost. To shed it, set `public` to `False` for that environment and redeploy.
A private cluster has no route in from the internet, so nothing reaches it from a laptop
without peering or a VPN. Of the sources that can reach it, `ALLOWED_CIDRS` decides which
are admitted; a home IP address there achieves nothing on its own, because no route
carries the packets.

The usual private setup is VPC peering: peer your application's VPC with the default
VPC the cluster lives in, add routes both ways, and put the application VPC's CIDR in
`ALLOWED_CIDRS`. The peering itself belongs to your application's network stacks, not
here.

### Reaching a private cluster from a laptop

Peering serves your application, not your `psql` session. There are three ways in.

**SSM Session Manager port forwarding** works on any port, but needs an EC2 instance
running the SSM agent inside the VPC. The cheapest such instance costs more per month
than a public IPv4 address, so it saves nothing over leaving the cluster public.

**EC2 Instance Connect Endpoint** costs nothing and needs no instance, but it accepts
only two remote ports. Tunnelling to 36784 fails with `The specified RemotePort is not
valid. Specify either 22 or 3389 as the RemotePort`. RDS rejects port 22, so the only
way through is to run Postgres on 3389:

```bash
aws ec2-instance-connect open-tunnel \
    --instance-connect-endpoint-id eice-0123456789abcdef0 \
    --private-ip-address "$(dig +short <cluster-endpoint> | tail -1)" \
    --remote-port 3389 --local-port 13389
psql "postgresql://dbadmin:...@127.0.0.1:13389/myapptesting"
```

That path is tested and carries a normal session, writes included. AWS caps each tunnel
at one hour, throttles anything resembling a bulk transfer, and documents the endpoint
as targeting EC2 instances rather than databases, so treat it as a convenience for
occasional access rather than a data path. One trap: the tunnel opens its local port
before the connection is authorized, so a listening port is not proof of a working
tunnel.

**RDS Data API** needs no network path at all, just IAM over HTTPS, and a request wakes a
paused cluster. It is not `psql`, though: one statement per call, JSON back, no
interactive session. Enable it with `enable_data_api` on the cluster.

## What stops a cluster pausing

Minimum capacity 0 is the auto-pause feature itself; at 0.5 a cluster never pauses and
bills ~$73/month. A cluster also stays awake while any connection is open (a forgotten
`psql` session counts), or when it uses an attached RDS Proxy, logical replication,
Global Database, zero-ETL integration with Redshift, or Babelfish.

`auto_pause_minutes` sets the idle timer per environment, 15 minutes by default. AWS
accepts 5 minutes to 1 day. Raise it if a work session with gaps keeps hitting cold
starts: an idle cluster waiting to pause holds 0.5 ACU, so an extra hour awake costs
about 6 cents.

## Destroy

`cdk destroy` takes a final snapshot instead of deleting the data
(`RemovalPolicy.SNAPSHOT`). The snapshot bills for storage until you delete it from the
RDS console.

## License

[MIT](LICENSE)
