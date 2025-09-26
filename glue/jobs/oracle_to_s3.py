# glue/jobs/oracle_to_s3.py
# PySpark Glue job to extract incremental data from Oracle and write Parquet to S3.
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

# JDBC URL and credentials should be provided via Glue Connection and Secrets Manager.
jdbc_url = "jdbc:oracle:thin:@//{ORACLE_HOST}:{ORACLE_PORT}/{ORACLE_SID}"
connection_properties = {
    'user': '{ORACLE_USER}',
    'password': '{ORACLE_PASSWORD}',
    'driver': 'oracle.jdbc.OracleDriver'
}

# Parameterized query for incremental extract using watermark/timestamp column
query = f"(SELECT * FROM {table} WHERE {watermark_col} > TO_TIMESTAMP('{last_watermark}', 'YYYY-MM-DD HH24:MI:SS')) tmp"

df = spark.read.jdbc(url=jdbc_url, table=query, properties=connection_properties)

# Add ingestion_date column for partitioning
df = df.withColumn('ingestion_date', current_date())

s3_path = f"s3://upcrewpro-raw/{table}/ingestion_date={{}}/".format(df.select("ingestion_date").first()[0] if df.head(1) else 'unknown')
# Write as parquet partitioned by date
(df.write
   .mode('append')
   .parquet(s3_path))

job.commit()
