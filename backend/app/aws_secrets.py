"""Optional loader: fills environment variables from AWS Secrets Manager BEFORE config.py reads them.

OFF unless AWS_SECRETS_ID is set as a real environment variable (not in .env).
The secret must hold a JSON object: {"SECRET_KEY": "...", "DATABASE_URL": "...", ...}.
Variables that are already set in the environment are never overwritten.
Region and credentials come from the normal AWS environment / instance role (no keys in code).
Secret values and names are never logged.
"""
import json
import logging
import os


def load_aws_secrets() -> int:
    secret_id = os.environ.get("AWS_SECRETS_ID", "").strip()
    if not secret_id:
        return 0
    log = logging.getLogger("medscribe")
    try:
        import boto3
    except ImportError:
        log.error("AWS_SECRETS_ID is set but boto3 is not installed: secrets were NOT loaded.")
        return 0
    try:
        client = boto3.client("secretsmanager")
        raw = client.get_secret_value(SecretId=secret_id).get("SecretString") or ""
        data = json.loads(raw)
    except Exception as e:
        log.error("Could not load secrets from AWS Secrets Manager (%s): continuing with the environment only.", type(e).__name__)
        return 0
    if not isinstance(data, dict):
        log.error("The AWS secret is not a JSON object: nothing was loaded.")
        return 0
    loaded = 0
    for key, value in data.items():
        key = str(key)
        if key == "AWS_SECRETS_ID" or not key.replace("_", "").isalnum():
            continue
        if key in os.environ:
            continue
        os.environ[key] = "" if value is None else str(value)
        loaded += 1
    log.info("Loaded %d setting(s) from AWS Secrets Manager.", loaded)
    return loaded