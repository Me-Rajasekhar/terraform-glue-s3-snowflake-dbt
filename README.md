# UPCrewPro — End-to-end S3 → Glue → Snowflake → dbt ETL Reference Project

**Purpose**: A ready-to-run, interview-ready reference project that demonstrates an enterprise-grade pipeline extracting from Oracle (on AWS) using AWS Glue, landing data into S3, auto-ingesting into Snowflake via Snowpipe, applying transformations with dbt, and exposing BI-ready tables. Includes infrastructure as code, CI/CD, monitoring, alerting, and a runbook.

---

## What I created in this repo

* `terraform/` — Terraform modules to provision AWS resources: S3 buckets, IAM, Glue, Lambda, SNS, CloudWatch. (Example partials included.)
* `glue/jobs/` — Glue PySpark job to extract from Oracle via JDBC and write partitioned parquet to S3.
* `lambda/snowpipe_notifier/` — Lambda that handles S3 event, calls Snowflake REST API to notify Snowpipe (auto-ingest). Example code included.
* `snowflake/sql/` — Snowflake DDL: stage, file format, pipe, table schemas, grants, and a sample Snowflake task to run ingestion validation.
* `dbt/` — dbt project (v1.x) with `models/staging/`, `models/marts/`, sample `profiles.yml` template and sample `schema.yml` for tests.
* `.github/workflows/` — GitHub Actions workflows for CI: terraform plan/apply (example), dbt run/test, and deploy Snowflake DDL.
* `monitoring/` — CloudWatch alarm definitions and example SNS/Lambda integrations for alerting.
* `sample_data/` — Small sample CSV and SQL to load for demo.
* `README.md` — This file (project overview, how to run locally and in AWS, security notes, runbook and interview notes).

> NOTE: This repo is intentionally templated with placeholders for sensitive values (private keys, passwords, account IDs). Replace placeholders before deploying.

---

## Architecture (short)

1. Oracle DB hosted on Amazon RDS/EC2 in a private subnet.
2. AWS Glue job (PySpark) with a JDBC connection to Oracle extracts incremental data (CDC via watermark column or timestamp) as Parquet into S3 (raw bucket) in `s3://upcrewpro-raw/<source>/<table>/date=YYYY-MM-DD/`.
3. S3 bucket configured with event notifications to Lambda or direct Snowpipe notification integration; Lambda calls Snowflake Snowpipe REST ingest endpoint (or uses SQS + Snowpipe native notifications) so Snowpipe loads files into staging tables.
4. Snowflake uses micro-partitioned tables; Snowpipe populates staging tables. Continuous ingestion with `COPY INTO` handled by Snowpipe.
5. dbt runs transformations: staging -> intermediate -> marts (BI-ready star schemas). dbt is executed via GitHub Actions for CI and can be run on a scheduled runner in AWS (EC2/ECS) for regular cadence.
6. Monitoring: CloudWatch Glue job metrics, CloudWatch Logs, CloudTrail, SNS alerts, Snowflake usage monitors, and dbt tests. PagerDuty / Slack integration via SNS subscription.

---

## Repo layout (file tree)

```
UPCrewPro_ETL/
├─ terraform/
│  ├─ main.tf
│  ├─ s3.tf
│  ├─ glue.tf
│  ├─ iam.tf
│  └─ lambda.tf
├─ glue/
│  └─ jobs/
│     └─ oracle_to_s3.py
├─ lambda/
│  └─ snowpipe_notifier/
│     └─ handler.py
├─ snowflake/
│  └─ sql/
│     ├─ 01_create_database.sql
│     ├─ 02_create_file_format_and_stage.sql
│     ├─ 03_create_tables_and_pipe.sql
│     └─ 04_grants.sql
├─ dbt/
│  ├─ dbt_project.yml
│  ├─ profiles.yml.template
│  └─ models/
│     ├─ staging/
│     │  └─ stg_orders.sql
│     └─ marts/
│        └─ orders_fct.sql
├─ .github/workflows/
│  ├─ terraform.yml
│  └─ dbt.yml
├─ monitoring/
│  └─ cloudwatch_alarms.md
├─ sample_data/
│  └─ orders_sample.csv
└─ README.md
```

---

## Quick start — local (dev/demo)

1. Install requirements: `python>=3.9`, `pip`, `terraform`, `awscli`, `snowflake-cli` (snowsql), `dbt-core` + `dbt-snowflake`.
2. Copy `dbt/profiles.yml.template` to `~/.dbt/profiles.yml` and fill Snowflake connection details.
3. Open `snowflake/sql/01_create_database.sql` and run via `snowsql -f` to create database, schema.
4. Run dbt locally for a demo dataset: `dbt deps && dbt seed && dbt run --profiles-dir .` (seed will load `sample_data/`).

This demonstrates the transformation layer without provisioning AWS.

---

## Quick start — deploy to AWS (high-level)

1. Prepare AWS credentials and Snowflake service user JWT/private key for Snowpipe REST auth.
2. `cd terraform` and set vars or export env vars. Run `terraform init`, `terraform plan` and `terraform apply` (be careful in prod).
3. Upload `glue/jobs/oracle_to_s3.py` to S3 (or use Terraform to upload) and create Glue job using the created IAM role.
4. Deploy Lambda `lambda/snowpipe_notifier/handler.py`, give it `s3:GetObject` and network access to call external Snowflake endpoint via NAT/GW.
5. Configure S3 event notification to invoke the Lambda for `s3:ObjectCreated:*` on prefix `raw/<source>/`.
6. Create Snowflake stage and pipe (`snowflake/sql`), and configure SNS or use direct Snowpipe notifications if available.
7. Schedule Glue job (or run on demand) to extract data from Oracle.
8. After files land in S3, Snowpipe will ingest into Snowflake staging tables automatically.
9. Run dbt (GitHub Actions or a scheduled runner) to transform and build marts.

---

## Important files & samples (copy/paste from repo)

### 1) Glue job — `glue/jobs/oracle_to_s3.py` (PySpark)

```python
# oracle_to_s3.py
import sys
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql.functions import current_date

args = getResolvedOptions(sys.argv, ['JOB_NAME', 'TABLE_NAME', 'WATERMARK_COLUMN', 'LAST_WATERMARK'])
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

table = args['TABLE_NAME']
watermark_col = args['WATERMARK_COLUMN']
last_watermark = args['LAST_WATERMARK']  # e.g. '2025-01-01 00:00:00'

jdbc_url = "jdbc:oracle:thin:@//${ORACLE_HOST}:${ORACLE_PORT}/${ORACLE_SID}"
connection_properties = {
    'user': '${ORACLE_USER}',
    'password': '${ORACLE_PASSWORD}',
    'driver': 'oracle.jdbc.OracleDriver'
}

query = f"(SELECT * FROM {table} WHERE {watermark_col} > TO_TIMESTAMP('{last_watermark}', 'YYYY-MM-DD HH24:MI:SS')) tmp"

df = spark.read.jdbc(url=jdbc_url, table=query, properties=connection_properties)

# Add ingestion_date column for partitioning
df = df.withColumn('ingestion_date', current_date())

s3_path = f"s3://upcrewpro-raw/{table}/ingestion_date={{{{ds}}}}/"
# Write as parquet partitioned by date
(df.write
   .mode('append')
   .parquet(s3_path))

job.commit()
```

> **Notes**: Use Glue Studio to parameterize `ORACLE_HOST`, `ORACLE_USER`, secrets stored in AWS Secrets Manager or AWS Glue Connection. Use official Oracle JDBC driver in the Glue job (upload as job library).

### 2) Snowflake SQL (create stage, file format, pipe) — `snowflake/sql/03_create_tables_and_pipe.sql`

```sql
-- 1. Create file format
CREATE OR REPLACE FILE FORMAT UPCREWPRO.PUB.FILE_FORMAT_PARQUET
  TYPE = 'PARQUET'
  COMPRESSION = 'AUTO';

-- 2. Create stage (external stage pointing to S3)
CREATE OR REPLACE STAGE UPCREWPRO.PUB.EXT_RAW_ORDERS
  URL='s3://upcrewpro-raw/orders'
  FILE_FORMAT = UPCREWPRO.PUB.FILE_FORMAT_PARQUET
  CREDENTIALS=(AWS_KEY_ID='{{SNOWFLAKE_AWS_KEY}}' AWS_SECRET_KEY='{{SNOWFLAKE_AWS_SECRET}}');

-- 3. Staging table
CREATE OR REPLACE TABLE UPCREWPRO.PUB.STG_ORDERS (
  order_id STRING,
  customer_id STRING,
  amount NUMBER(10,2),
  order_ts TIMESTAMP_NTZ,
  ingestion_date DATE
);

-- 4. Create pipe using COPY INTO that Snowpipe will use
CREATE OR REPLACE PIPE UPCREWPRO.PUB.PIPE_LOAD_STG_ORDERS
  AUTO_INGEST = TRUE
  AS
  COPY INTO UPCREWPRO.PUB.STG_ORDERS
  FROM @UPCREWPRO.PUB.EXT_RAW_ORDERS
  FILE_FORMAT = (FORMAT_NAME = 'UPCREWPRO.PUB.FILE_FORMAT_PARQUET')
  ON_ERROR = 'CONTINUE'
  PURGE = FALSE;
```

> **Notes**: In production use an IAM role and Snowflake storage integration rather than plaintext AWS keys. See Snowflake docs for `CREATE STORAGE INTEGRATION` and `NOTIFICATION_INTEGRATION` with SQS.

### 3) Lambda for Snowpipe notification — `lambda/snowpipe_notifier/handler.py`

```python
import json
import os
import boto3
import requests

SNOWFLAKE_ACCOUNT = os.environ['SNOWFLAKE_ACCOUNT']
SNOWFLAKE_USER = os.environ['SNOWFLAKE_USER']
SNOWFLAKE_PRIVATE_KEY = os.environ['SNOWFLAKE_PRIVATE_KEY']  # prefer KMS/Secrets
PIPE_NAME = os.environ.get('PIPE_NAME', 'UPCREWPRO.PUB.PIPE_LOAD_STG_ORDERS')

# This example uses REST API to notify Snowpipe (simple). In production use SQS/SNS + notification integrations.

def lambda_handler(event, context):
    print('Event:', json.dumps(event))
    # Extract S3 file details
    for record in event.get('Records', []):
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        # Build file path for Snowflake stage
        file_path = f"s3://{bucket}/{key}"
        # Form the REST URL
        url = f"https://{SNOWFLAKE_ACCOUNT}.snowflakecomputing.com/v1/data/pipes/{PIPE_NAME}/insertFiles"
        payload = {"files": [{"path": file_path}]}
        # Authentication: use Snowflake OAuth/JWT or basic (not recommended)
        headers = {'Content-Type': 'application/json'}
        r = requests.post(url, json=payload, headers=headers)
        print('Snowpipe response', r.status_code, r.text)

    return {'status': 'ok'}
```

> **Security**: Use Snowflake key-pair authentication or OAuth, not plaintext. Store secrets in AWS Secrets Manager and retrieve in Lambda.

### 4) dbt sample model — `dbt/models/staging/stg_orders.sql`

```sql
{{ config(materialized='view') }}

with raw as (
  select
    order_id::string as order_id,
    customer_id::string as customer_id,
    amount::number as amount,
    order_ts::timestamp_ntz as order_ts,
    ingestion_date::date as ingestion_date
  from {{ source('upcrewpro','stg_orders') }}
)

select *
from raw
where order_ts is not null
```

And a mart model `dbt/models/marts/orders_fct.sql` converts to a fact table.

### 5) GitHub Actions — `/.github/workflows/dbt.yml` (simplified)

```yaml
name: dbt CI
on:
  push:
    branches: [ main ]

jobs:
  dbt-run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'
      - name: Install dbt
        run: |
          pip install dbt-core dbt-snowflake
      - name: Run dbt
        env:
          DBT_PROFILES_DIR: ./dbt
          SNOWFLAKE_USER: ${{ secrets.SF_USER }}
          SNOWFLAKE_PASSWORD: ${{ secrets.SF_PWD }}
        run: |
          cd dbt
          dbt deps
          dbt seed --profiles-dir .
          dbt run --profiles-dir .
          dbt test --profiles-dir .
```

### 6) Terraform — example S3 + IAM snippet `terraform/s3.tf`

```hcl
resource "aws_s3_bucket" "raw" {
  bucket = "upcrewpro-raw"
  acl    = "private"
  server_side_encryption_configuration {
    rule {
      apply_server_side_encryption_by_default {
        sse_algorithm = "aws:kms"
        kms_master_key_id = aws_kms_key.s3_key.arn
      }
    }
  }
  versioning { enabled = true }
  tags = {
    Project = "UPCrewPro"
  }
}

resource "aws_kms_key" "s3_key" {
  description = "KMS key for S3 encryption"
}
```

### 7) Monitoring & Alerts (high-level)

* **Glue**: CloudWatch metric filters for `Glue` job `Failed`/`Succeeded`. Create alarm on `glue-job-errors` when failures > 0 within 5 minutes.
* **Lambda**: CloudWatch alarms on `Errors` and `Duration` thresholds.
* **Snowflake**: Use Snowflake ACCOUNT_USAGE views to monitor pipe load latency and failures; alert if lag > threshold.
* **dbt**: dbt tests in CI; failures trigger GitHub Action failure and alert via Slack webhook.
* **Notifications**: SNS topic `upcrewpro-alerts` with subscriptions to email/Slack/PagerDuty.

Example CloudWatch alarm (Terraform or Console) for Glue failed jobs included in `monitoring/cloudwatch_alarms.md`.

---

## Security & Best Practices

* Use AWS Secrets Manager for DB credentials; assign Glue job role permissions to decrypt secrets only.
* Use Snowflake Storage Integration + AWS IAM role for secure access (avoid AWS keys in Snowflake SQL). See `CREATE STORAGE INTEGRATION` pattern (placeholder in DDL).
* Limit IAM privilege: least privilege for Glue, Lambda, and CI service account.
* Encrypt data at rest (S3 SSE-KMS) and in transit (TLS for JDBC and Snowflake).
* Audit with CloudTrail and maintain S3 access logs.

---

## Runbook (failure scenarios)

* **Glue job fails**: Check CloudWatch Logs, check JDBC connectivity, check secret rotation. Restart job manually or rerun with adjusted watermark.
* **Snowpipe ingestion failing**: Check Lambda logs for REST failures, Snowflake `LOAD_HISTORY` and `INFORMATION_SCHEMA.LOAD_HISTORY`, queue in SQS if using notification integration.
* **dbt tests failing**: Inspect failing tests in CI logs, run `dbt test` locally with `--select` to isolate.

---

## Interview talking points (ready-made bullet points)

* Designed and implemented secure, scalable CDC pipeline from Oracle to Snowflake using AWS Glue, S3, Snowpipe and dbt.
* Implemented automated ingestion with Snowpipe and S3 event notifications via Lambda; reduced data latency from batch to near-real-time.
* Used parquet format and partitioning to optimize storage and Snowflake ingestion costs.
* Ensured observability via CloudWatch, Snowflake ingestion metrics, dbt tests and CI/CD; configured alerts to Slack/PagerDuty.
* Implemented Terraform for repeatable provisioning and GitHub Actions for CI:dbt and infra deployment.

---

## Next steps / optional enhancements

* Replace Lambda-based Snowpipe notification with SQS + Snowflake Notification Integration for robust scale.
* Use AWS DMS for complex CDC (LOBs, multi-table ordering) if needed.
* Add data quality monitoring using Great Expectations (integrate with dbt tests).
* Build a small dashboard in Looker/PowerBI/Mode connected to Snowflake to demo BI queries.

---

## License

MIT — adapt and use for interviews and proofs-of-concept. Remove any company-identifying data if public.

---

## Where to look inside this repo

Open the text files in the `glue/`, `snowflake/`, `dbt/`, `terraform/`, and `.github/` folders to copy/paste into your real GitHub repo. All sensitive values are placeholders in `{{ }}` syntax.

*** End of README ***
