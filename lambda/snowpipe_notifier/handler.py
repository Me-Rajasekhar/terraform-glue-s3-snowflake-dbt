# lambda/snowpipe_notifier/handler.py
# Example Lambda to notify Snowpipe of newly created S3 objects.
import json
import os
import requests

SNOWFLAKE_ACCOUNT = os.environ.get('SNOWFLAKE_ACCOUNT')
PIPE_NAME = os.environ.get('PIPE_NAME', 'UPCREWPRO.PUB.PIPE_LOAD_STG_ORDERS')

def lambda_handler(event, context):
    print('Event:', json.dumps(event))
    for record in event.get('Records', []):
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        file_path = f"s3://{bucket}/{key}"
        url = f"https://{SNOWFLAKE_ACCOUNT}.snowflakecomputing.com/v1/data/pipes/{PIPE_NAME}/insertFiles"
        payload = {"files": [{"path": file_path}]}
        headers = {'Content-Type': 'application/json'}
        # Note: In production, authenticate using JWT/OAuth. This is a placeholder.
        r = requests.post(url, json=payload, headers=headers)
        print('Snowpipe response', r.status_code, r.text)
    return {'status': 'ok'}
