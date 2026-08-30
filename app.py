"""One Aurora Serverless v2 cluster per environment, scaling to zero when idle.

Keep this as its own CDK app, separate from the application stacks, so a
``cdk destroy`` of the application cannot take the data with it.
"""

import os

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
        **kwargs,
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
            # Long enough that a working session does not keep cold-starting. Staying awake
            # the extra 45 minutes costs about 8 cents at the 0.5 ACU floor.
            serverless_v2_auto_pause_duration=Duration.hours(1),
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


app = cdk.App()

for env_name, region, public in ENVIRONMENTS:
    slug = env_name.lower()
    ServerlessDatabaseStack(
        app,
        f'{PREFIX}-{slug}-database',
        cluster_identifier=f'{PREFIX}-{slug}',
        database_name=f'{PREFIX}{slug}',
        secret_name=f'{PREFIX}-{slug}-db',
        public=public,
        # The CDK CLI sets CDK_DEFAULT_ACCOUNT from the active AWS credentials.
        env=cdk.Environment(account=os.environ['CDK_DEFAULT_ACCOUNT'], region=region),
    )

app.synth()
