# CloudWatch Alarms - examples

- Glue Job Failures: Alarm when Glue job errors > 0 in 5 minutes.
- Lambda Errors: Alarm on Errors > 0 for the snowpipe notifier.
- Snowpipe Lag: Query Snowflake LOAD_HISTORY to monitor latency; create alert if ingestion lag > threshold.
- dbt CI failures: GitHub Action failing should notify Slack/PagerDuty via webhook.
