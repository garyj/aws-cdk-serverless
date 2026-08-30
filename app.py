"""One Aurora Serverless v2 cluster per environment, scaling to zero when idle.

Keep this as its own CDK app, separate from the application stacks, so a
``cdk destroy`` of the application cannot take the data with it.
"""

import os
from typing import Any

import aws_cdk as cdk
from aws_cdk import CfnOutput, Duration, RemovalPolicy
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from constructs import Construct

from config import ALLOWED_CIDRS, ENVIRONMENTS, MASTER_USERNAME, PORT, PREFIX


class ServerlessDatabaseStack(cdk.Stack):
    """One Serverless v2 writer, scaling to zero, for a single environment."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cluster_identifier: str,
        database_name: str,
        secret_name: str,
        public: bool,
        auto_pause_duration: Duration,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        vpc = ec2.Vpc.from_lookup(self, 'DefaultVpc', is_default=True)

        cluster = rds.DatabaseCluster(
            self,
            'Cluster',
            cluster_identifier=cluster_identifier,
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_16_13,
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            writer=rds.ClusterInstance.serverless_v2('Writer', publicly_accessible=public),
            # 0 is the auto-pause feature itself; 0.5 never pauses and bills ~$73/month.
            serverless_v2_min_capacity=0,
            serverless_v2_max_capacity=4,
            serverless_v2_auto_pause_duration=auto_pause_duration,
            port=PORT,
            default_database_name=database_name,
            credentials=rds.Credentials.from_generated_secret(
                MASTER_USERNAME,
                secret_name=secret_name,
            ),
            # One day is the longest retention inside the free backup allocation.
            backup=rds.BackupProps(retention=Duration.days(1)),
            storage_encrypted=True,
            removal_policy=RemovalPolicy.SNAPSHOT,
        )

        for cidr in ALLOWED_CIDRS:
            cluster.connections.allow_from(
                ec2.Peer.ipv4(cidr),
                ec2.Port.tcp(PORT),
                description=f'Allowed CIDR {cidr}',
            )

        if public:
            cluster.connections.allow_from_any_ipv4(
                ec2.Port.tcp(PORT),
                description='Public endpoint',
            )

        CfnOutput(self, 'ClusterEndpoint', value=cluster.cluster_endpoint.hostname)
        CfnOutput(self, 'ClusterPort', value=str(PORT))
        CfnOutput(self, 'CredentialsSecret', value=secret_name)


ACCOUNT = os.environ.get('CDK_DEFAULT_ACCOUNT')
if not ACCOUNT:
    raise SystemExit(
        'No AWS account resolved. The CDK CLI sets CDK_DEFAULT_ACCOUNT from your active '
        'credentials, so check them with `aws sts get-caller-identity`, then export your '
        'keys or set AWS_PROFILE.'
    )

app = cdk.App()

for environment in ENVIRONMENTS:
    slug = environment.name.lower()
    ServerlessDatabaseStack(
        app,
        f'{PREFIX}-{slug}-database',
        cluster_identifier=f'{PREFIX}-{slug}',
        database_name=f'{PREFIX}{slug}',
        secret_name=f'{PREFIX}-{slug}-db',
        public=environment.public,
        auto_pause_duration=Duration.minutes(environment.auto_pause_minutes),
        env=cdk.Environment(account=ACCOUNT, region=environment.region),
    )

app.synth()
