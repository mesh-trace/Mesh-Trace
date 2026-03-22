"""
AWS Lambda function for processing crash data from mesh network
Receives MQTT messages from IoT Core and processes crash events
"""

import json
import logging
import os
from decimal import Decimal
import boto3  # pyright: ignore[reportMissingImports]
from datetime import datetime
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
TELEMETRY_DYNAMODB_TABLE = os.getenv('TELEMETRY_DYNAMODB_TABLE', 'mesh-trace-telemetry')
CRASHES_DYNAMODB_TABLE = os.getenv('CRASHES_DYNAMODB_TABLE', 'mesh-trace-crashes')
SNS_TOPIC_ARN = os.getenv('SNS_TOPIC_ARN')


def _to_dynamo_numbers(value: Any) -> Any:
    """Recursively convert floats to Decimal for DynamoDB put_item compatibility."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamo_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_dynamo_numbers(v) for v in value]
    return value


def _omit_none(mapping: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in mapping.items() if v is not None}


def store_live_telemetry_record(payload: Dict[str, Any]) -> None:
    """Persist LIVE_TELEMETRY to mesh-trace-telemetry (node_id + timestamp keys)."""
    table = dynamodb.Table(TELEMETRY_DYNAMODB_TABLE)
    item = _omit_none({
        'node_id': str(payload.get('node_id', 'unknown')),
        'timestamp': str(payload.get('timestamp', datetime.now().isoformat())),
        'type': payload.get('type'),
        'temperature': _to_dynamo_numbers(payload.get('temperature')) if payload.get('temperature') is not None else None,
        'accelerometer': _to_dynamo_numbers(payload.get('accelerometer')),
        'gyroscope': _to_dynamo_numbers(payload.get('gyroscope')),
        'gps': _to_dynamo_numbers(payload.get('gps')),
        'received_at': datetime.now().isoformat(),
    })
    table.put_item(Item=item)
    logger.info(
        "Telemetry stored: table=%s node_id=%s timestamp=%s",
        TELEMETRY_DYNAMODB_TABLE, item.get('node_id'), item.get('timestamp'),
    )


def store_vehicle_crash_record(payload: Dict[str, Any]) -> None:
    """Persist VEHICLE_CRASH_DETECTED to mesh-trace-crashes without oversized pre_crash_buffer."""
    table = dynamodb.Table(CRASHES_DYNAMODB_TABLE)
    node_id = str(payload.get('node_id', 'unknown'))
    timestamp = str(payload.get('timestamp', datetime.now().isoformat()))
    buffer = payload.get('pre_crash_buffer')
    buffer_len = len(buffer) if isinstance(buffer, list) else 0
    summary = {k: v for k, v in payload.items() if k != 'pre_crash_buffer'}
    summary['pre_crash_buffer_sample_count'] = buffer_len

    item = _omit_none({
        'node_id': node_id,
        'timestamp': timestamp,
        'alert': payload.get('alert'),
        'severity': payload.get('severity'),
        'acceleration_magnitude': _to_dynamo_numbers(payload.get('acceleration_magnitude'))
        if payload.get('acceleration_magnitude') is not None else None,
        'location': _to_dynamo_numbers(payload.get('location')),
        'summary_json': json.dumps(summary, default=str),
        'received_at': datetime.now().isoformat(),
    })
    table.put_item(Item=item)
    logger.info(
        "Crash record stored: table=%s node_id=%s timestamp=%s buffer_samples=%d",
        CRASHES_DYNAMODB_TABLE, node_id, timestamp, buffer_len,
    )


def process_live_telemetry(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        store_live_telemetry_record(payload)
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Telemetry stored', 'node_id': payload.get('node_id')}),
        }
    except Exception as e:
        logger.error("process_live_telemetry failed: %s", e, exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Failed to store telemetry'}),
        }


def process_vehicle_crash_ddb(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        store_vehicle_crash_record(payload)
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Crash record stored', 'node_id': payload.get('node_id')}),
        }
    except Exception as e:
        logger.error("process_vehicle_crash_ddb failed: %s", e, exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Failed to store crash record'}),
        }


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

        logger.debug("Payload type=%s alert=%s keys=%s", payload.get('type'), payload.get('alert'), list(payload.keys()))

        # Route by explicit telemetry / crash markers, then legacy types
        if payload.get('type') == 'LIVE_TELEMETRY':
            logger.info("Routing LIVE_TELEMETRY to DynamoDB table %s", TELEMETRY_DYNAMODB_TABLE)
            result = process_live_telemetry(payload)
        elif payload.get('alert') == 'VEHICLE_CRASH_DETECTED':
            logger.info("Routing VEHICLE_CRASH_DETECTED to DynamoDB table %s", CRASHES_DYNAMODB_TABLE)
            result = process_vehicle_crash_ddb(payload)
        elif payload.get('type') == 'crash_alert':
            logger.info("Processing crash_alert (legacy)")
            result = process_crash_alert(payload)
        elif payload.get('type') == 'health_report':
            logger.info("Processing health_report")
            result = process_health_report(payload)
        else:
            logger.warning("Unrecognized payload: type=%s alert=%s", payload.get('type'), payload.get('alert'))
            result = {
                'statusCode': 400,
                'body': json.dumps({'error': 'Unrecognized payload: expected LIVE_TELEMETRY, VEHICLE_CRASH_DETECTED, or legacy type'}),
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
        crash_data = payload.get('data', {})
        node_id = payload.get('node_id', 'unknown')
        timestamp = payload.get('timestamp', datetime.now().isoformat())
        logger.info("process_crash_alert: node_id=%s timestamp=%s", node_id, timestamp)

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
                'severity': crash_data.get('confidence', 0.0),
                'processed_at': datetime.now().isoformat(),
                'status': 'processed'
            }
        )
        logger.debug("DynamoDB put complete")

        # Send alert notification
        location = payload.get("location")
        logger.debug("Sending SNS notification: topic=%s", SNS_TOPIC_ARN)
        sns_message = {
            'alert_type': 'crash_detected',
            'node_id': node_id,
            'timestamp': timestamp,
            'confidence': crash_data.get('confidence', 0.0),
            'location': location,
            's3_location': f"s3://{S3_BUCKET}/{s3_key}"
        }
        
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"Crash Alert: Node {node_id}",
            Message=json.dumps(sns_message, indent=2)
        )
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
            sns_message = {
                'alert_type': 'sensor_health_issue',
                'node_id': node_id,
                'status': overall_status,
                'timestamp': timestamp,
                'issues': health_data.get('errors', [])
            }
            
            sns_client.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=f"Sensor Health Alert: Node {node_id}",
                Message=json.dumps(sns_message, indent=2)
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