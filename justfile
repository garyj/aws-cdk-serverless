set shell := ["bash", "-uc"]

prefix := `python3 -c "import config; print(config.PREFIX)"`
environments := `python3 -c "import config; print(' '.join(f'{n.lower()}:{r}' for n, r, _ in config.ENVIRONMENTS))"`
first_env := `python3 -c "import config; print(config.ENVIRONMENTS[0][0].lower())"`

default:
    @just --list

synth:
    cdk synth

diff:
    cdk diff

deploy env:
    cdk deploy {{ prefix }}-{{ env }}-database

# Every cluster: paused or running, and what that costs
status:
    #!/usr/bin/env bash
    set -euo pipefail
    printf "%-12s %-16s %-20s %s\n" ENV REGION CLUSTER STATE
    for pair in {{ environments }}; do
        env="${pair%%:*}"; region="${pair##*:}"
        acu=$(aws cloudwatch get-metric-statistics --region "$region" \
            --namespace AWS/RDS --metric-name ServerlessDatabaseCapacity \
            --dimensions Name=DBClusterIdentifier,Value="{{ prefix }}-$env" \
            --start-time "$(date -u -d '20 min ago' +%Y-%m-%dT%H:%M:%SZ)" \
            --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            --period 60 --statistics Average \
            --query 'sort_by(Datapoints,&Timestamp)[-1].Average' --output text 2>/dev/null || echo None)
        case "$acu" in
            None|"")   state="no metric yet" ;;
            0|0.0)     state="PAUSED, storage only" ;;
            *)         state="RUNNING at $acu ACU" ;;
        esac
        printf "%-12s %-16s %-20s %s\n" "$env" "$region" "{{ prefix }}-$env" "$state"
    done

# Stack outputs: endpoint, port, and secret name per environment
endpoint:
    #!/usr/bin/env bash
    set -euo pipefail
    for pair in {{ environments }}; do
        aws cloudformation describe-stacks --region "${pair##*:}" \
            --stack-name "{{ prefix }}-${pair%%:*}-database" \
            --query 'Stacks[0].Outputs[].{key:OutputKey,value:OutputValue}' --output table
    done

# ACU over the last hour; a minimum of 0 means the cluster paused
capacity env=first_env:
    #!/usr/bin/env bash
    set -euo pipefail
    region=$(just _region {{ env }})
    aws cloudwatch get-metric-statistics --region "$region" \
        --namespace AWS/RDS --metric-name ServerlessDatabaseCapacity \
        --dimensions Name=DBClusterIdentifier,Value={{ prefix }}-{{ env }} \
        --start-time "$(date -u -d '60 min ago' +%Y-%m-%dT%H:%M:%SZ)" \
        --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --period 60 --statistics Minimum Maximum \
        --query 'sort_by(Datapoints,&Timestamp)[].{time:Timestamp,min:Minimum,max:Maximum}' --output table

# Open a session; this wakes the cluster and resets its idle timer
psql env=first_env:
    #!/usr/bin/env bash
    set -euo pipefail
    region=$(just _region {{ env }})
    url=$(aws secretsmanager get-secret-value --region "$region" --secret-id {{ prefix }}-{{ env }}-db \
        --query SecretString --output text \
        | python3 -c "import json,sys; s=json.load(sys.stdin); print('postgresql://%s:%s@%s:%s/%s' % (s['username'],s['password'],s['host'],s['port'],s['dbname']))")
    docker run --rm -it --network host postgres:16-alpine psql "$url"

_region env:
    #!/usr/bin/env bash
    set -euo pipefail
    for pair in {{ environments }}; do
        [[ "${pair%%:*}" == "{{ env }}" ]] && { echo "${pair##*:}"; exit 0; }
    done
    echo "unknown env: {{ env }}" >&2
    exit 1
