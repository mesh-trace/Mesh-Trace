"""
AWS Lambda function for processing crash data from mesh network
Receives MQTT messages from IoT Core and processes crash events
"""

import json
import logging
import os
import boto3  # pyright: ignore[reportMissingImports]
from datetime import datetime, timezone, timedelta
from typing import Dict, Any
from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]

# Load environment variables from .env file
load_dotenv()

# Configure logging for Lambda (CloudWatch)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Initialize AWS clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
sns_client = boto3.client('sns')

# Configuration from environment variables
S3_BUCKET = os.getenv('S3_BUCKET', 'mesh-trace-crash-archive-et8-sav')
DYNAMODB_TABLE = os.getenv('DYNAMODB_TABLE', 'MeshTraceCrashTable')
SNS_TOPIC_ARN = os.getenv('SNS_TOPIC_ARN')


def format_timestamp(iso_str: str) -> str:
    """
    Convert ISO 8601 timestamp from edge node into a clean, readable string.

    Input  : "2026-03-24T22:07:33.740697+05:30"
    Output : "Tuesday, 24 March 2026  10:07:33 PM IST"
    """
    try:
        dt = datetime.fromisoformat(iso_str)
        # If timestamp has no timezone info, assume IST
        if dt.tzinfo is None:
            IST = timezone(timedelta(hours=5, minutes=30))
            dt = dt.replace(tzinfo=IST)
        return dt.strftime("%A, %d %B %Y  %I:%M:%S %p %Z").replace("UTC+0530", "IST")
    except Exception:
        return iso_str  # fall back to raw string if parsing fails


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for processing crash data
    
    Args:
        event: Lambda event containing MQTT message
        context: Lambda context object
        
    Returns:
        dict: Response with status code and message
    """
    logger.info("lambda_handler invoked: request_id=%s", getattr(context, 'aws_request_id', 'N/A'))
    logger.debug("Event keys: %s", list(event.keys()))

    try:
        # Extract MQTT message payload
        if 'Records' in event:
            # SQS trigger (from IoT Rule action)
            record = event['Records'][0]
            logger.debug("SQS trigger: record_id=%s", record.get('messageId'))
            payload = json.loads(record['body'])
        elif 'topic' in event:
            # Direct MQTT trigger
            logger.debug("Direct MQTT trigger: topic=%s", event.get('topic'))
            payload = json.loads(event.get('payload', '{}'))
        else:
            payload = event
            logger.debug("Direct payload (no Records/topic)")

        logger.debug("Payload type=%s keys=%s", payload.get('type'), list(payload.keys()))

        # Validate payload structure
        if 'type' not in payload:
            logger.warning("Invalid payload: missing type field")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Invalid payload: missing type field'})
            }

        # Process based on message type
        if payload['type'] == 'crash_alert':
            logger.info("Processing crash_alert")
            result = process_crash_alert(payload)
        elif payload['type'] == 'health_report':
            logger.info("Processing health_report")
            result = process_health_report(payload)
        else:
            logger.warning("Unknown message type: %s", payload['type'])
            result = {
                'statusCode': 400,
                'body': json.dumps({'error': f'Unknown message type: {payload["type"]}'})
            }

        logger.info("lambda_handler completed: status=%s", result.get('statusCode'))
        return result

    except Exception as e:
        logger.error("Error processing message: %s", str(e), exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


def process_crash_alert(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process crash alert message
    
    Args:
        payload: Crash alert payload
        
    Returns:
        dict: Processing result
    """
    try:
        crash_data = payload.get('data', {})           # FIX 1: was 'data' all along — edge now sends correct key
        node_id = payload.get('node_id', 'unknown')
        timestamp = payload.get('timestamp', datetime.now().isoformat())
        severity = payload.get('severity', 'UNKNOWN')  # FIX 2: read severity from top-level payload
        logger.info("process_crash_alert: node_id=%s timestamp=%s severity=%s", node_id, timestamp, severity)

        # Store in S3 (no hash/encryption; sensor testing + cloud hopping only)
        s3_key = f"crashes/{node_id}/{timestamp}.json"
        logger.debug("Uploading to S3: bucket=%s key=%s", S3_BUCKET, s3_key)
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(crash_data, indent=2),
            ContentType='application/json',
            Metadata={
                'node_id': node_id,
                'timestamp': timestamp
            }
        )
        logger.debug("S3 upload complete")

        # Store metadata in DynamoDB
        logger.debug("Writing to DynamoDB: table=%s", DYNAMODB_TABLE)
        table = dynamodb.Table(DYNAMODB_TABLE)
        table.put_item(
            Item={
                'node_id': node_id,
                'timestamp': timestamp,
                's3_key': s3_key,
                'severity': severity,                  # FIX 3: was crash_data.get('confidence') — always 0
                'acceleration_magnitude': str(payload.get('acceleration_magnitude', 0.0)),
                'location': json.dumps(payload.get('location')),
                'processed_at': datetime.now().isoformat(),
                'status': 'processed'
            }
        )
        logger.debug("DynamoDB put complete")

        # Send alert notification
        location = payload.get("location")
        if not SNS_TOPIC_ARN:
            logger.warning("SNS_TOPIC_ARN not set — skipping notification")
        else:
            logger.debug("Sending SNS notification: topic=%s", SNS_TOPIC_ARN)

            readable_time = format_timestamp(timestamp)

            if location and location.get("latitude") is not None:
                lat = location["latitude"]
                lon = location["longitude"]
                maps_url = f"https://maps.google.com/?q={lat},{lon}"
                location_str = f"{lat:.6f}, {lon:.6f}\n   Maps : {maps_url}"
            else:
                location_str = "Not available (no GPS fix at time of crash)"

            accel_mag = payload.get("acceleration_magnitude", 0.0)

            severity_desc = {
                "LOW":    "Low    (8-15 m/s2)  — minor impact",
                "MEDIUM": "Medium (15-25 m/s2) — significant impact",
                "HIGH":   "High   (>25 m/s2)   — severe impact",
            }.get(severity, severity)

            email_body = (
                "MESH-TRACE CRASH ALERT\n"
                "==============================================\n\n"
                f"  Node      : {node_id}\n"
                f"  Time      : {readable_time}\n"
                f"  Severity  : {severity_desc}\n"
                f"  Impact    : {accel_mag} m/s2\n"
                f"  Location  : {location_str}\n\n"
                "----------------------------------------------\n"
                f"  S3 Record : s3://{S3_BUCKET}/{s3_key}\n"
                "==============================================\n\n"
                "This alert was generated automatically by the\n"
                "Mesh-Trace crash detection system."
            )

            sns_client.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=f"[Mesh-Trace] Crash Alert — {severity} — {node_id}",
                Message=email_body
            )
            logger.info("SNS notification sent")
        logger.info("Crash alert processed: Node %s at %s s3_key=%s", node_id, timestamp, s3_key)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Crash alert processed successfully',
                'node_id': node_id,
                's3_key': s3_key
            })
        }
    
    except Exception as e:
        logger.error("Error processing crash alert: %s", e, exc_info=True)
        raise


def process_health_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process sensor health report
    
    Args:
        payload: Health report payload
        
    Returns:
        dict: Processing result
    """
    try:
        node_id = payload.get('node_id', 'unknown')
        health_data = payload.get('health_data', {})
        timestamp = payload.get('timestamp', datetime.now().isoformat())
        logger.info("process_health_report: node_id=%s timestamp=%s", node_id, timestamp)

        # Store health report in S3
        s3_key = f"health/{node_id}/{timestamp}.json"
        logger.debug("Uploading health report to S3: bucket=%s key=%s", S3_BUCKET, s3_key)
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(health_data, indent=2),
            ContentType='application/json'
        )
        logger.debug("Health report S3 upload complete")

        # Check for critical issues
        overall_status = health_data.get('overall_status', 'unknown')
        logger.debug("Health overall_status=%s", overall_status)
        if overall_status in ['error', 'critical']:
            # Send alert for critical sensor issues
            if not SNS_TOPIC_ARN:                      # FIX: guard — crashes Lambda if ARN is None
                logger.warning("SNS_TOPIC_ARN not set — skipping health alert notification")
            else:
                readable_time = format_timestamp(timestamp)
                issues = health_data.get("errors", [])
                issues_str = "\n".join(f"    - {i}" for i in issues) if issues else "    None reported"

                health_email = (
                    "MESH-TRACE SENSOR HEALTH ALERT\n"
                    "==============================================\n\n"
                    f"  Node      : {node_id}\n"
                    f"  Time      : {readable_time}\n"
                    f"  Status    : {overall_status.upper()}\n\n"
                    "  Issues detected:\n"
                    f"{issues_str}\n\n"
                    "----------------------------------------------\n"
                    f"  S3 Record : s3://{S3_BUCKET}/{s3_key}\n"
                    "==============================================\n\n"
                    "This alert was generated automatically by the\n"
                    "Mesh-Trace crash detection system."
                )
                sns_client.publish(
                    TopicArn=SNS_TOPIC_ARN,
                    Subject=f"[Mesh-Trace] Sensor Health Alert — {overall_status.upper()} — {node_id}",
                    Message=health_email
                )
                logger.info("SNS alert sent for critical health: node_id=%s status=%s", node_id, overall_status)

        logger.info("Health report processed: node_id=%s", node_id)
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Health report processed',
                'node_id': node_id
            })
        }

    except Exception as e:
        logger.error("Error processing health report: %s", e, exc_info=True)
        raise


def create_dynamodb_table_if_not_exists():
    """Create DynamoDB table if it doesn't exist (for setup)"""
    try:
        table = dynamodb.create_table(
            TableName=DYNAMODB_TABLE,
            KeySchema=[
                {'AttributeName': 'node_id', 'KeyType': 'HASH'},
                {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'node_id', 'AttributeType': 'S'},
                {'AttributeName': 'timestamp', 'AttributeType': 'S'}
            ],
            BillingMode='PAY_PER_REQUEST'
        )
        logger.info("Table %s created", DYNAMODB_TABLE)
        return table
    except Exception as e:
        if 'ResourceInUseException' in str(e):
            logger.info("Table %s already exists", DYNAMODB_TABLE)
        else:
            logger.error("Failed to create DynamoDB table: %s", e, exc_info=True)
            raise