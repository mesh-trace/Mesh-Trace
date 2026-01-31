"""
AWS Lambda function for processing crash data from mesh network
Receives MQTT messages from IoT Core and processes crash events
"""

import json
import os
import boto3
from datetime import datetime
from typing import Dict, Any
from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]

# Load environment variables from .env file
load_dotenv()

# Initialize AWS clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
sns_client = boto3.client('sns')

# Configuration from environment variables
S3_BUCKET = os.getenv('S3_BUCKET', 'mesh-trace-crash-archive-et8')
DYNAMODB_TABLE = os.getenv('DYNAMODB_TABLE', 'MeshTraceCrashTable')
SNS_TOPIC_ARN = os.getenv('SNS_TOPIC_ARN')


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for processing crash data
    
    Args:
        event: Lambda event containing MQTT message
        context: Lambda context object
        
    Returns:
        dict: Response with status code and message
    """
    try:
        # Extract MQTT message payload
        if 'Records' in event:
            # SQS trigger (from IoT Rule action)
            record = event['Records'][0]
            payload = json.loads(record['body'])
        elif 'topic' in event:
            # Direct MQTT trigger
            payload = json.loads(event.get('payload', '{}'))
        else:
            payload = event
        
        # Validate payload structure
        if 'type' not in payload:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Invalid payload: missing type field'})
            }
        
        # Process based on message type
        if payload['type'] == 'crash_alert':
            result = process_crash_alert(payload)
        elif payload['type'] == 'health_report':
            result = process_health_report(payload)
        else:
            result = {
                'statusCode': 400,
                'body': json.dumps({'error': f'Unknown message type: {payload["type"]}'})
            }
        
        return result
    
    except Exception as e:
        print(f"Error processing message: {str(e)}")
        import traceback
        traceback.print_exc()
        
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
        
        # Store in S3 (no hash/encryption; sensor testing + cloud hopping only)
        s3_key = f"crashes/{node_id}/{timestamp}.json"
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
        
        # Store metadata in DynamoDB
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
        
        # Send alert notification
        location = payload.get("location")
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
        
        print(f"Crash alert processed: Node {node_id} at {timestamp}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Crash alert processed successfully',
                'node_id': node_id,
                's3_key': s3_key
            })
        }
    
    except Exception as e:
        print(f"Error processing crash alert: {e}")
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
        
        # Store health report in S3
        s3_key = f"health/{node_id}/{timestamp}.json"
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(health_data, indent=2),
            ContentType='application/json'
        )
        
        # Check for critical issues
        overall_status = health_data.get('overall_status', 'unknown')
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
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Health report processed',
                'node_id': node_id
            })
        }
    
    except Exception as e:
        print(f"Error processing health report: {e}")
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
        print(f"Table {DYNAMODB_TABLE} created")
        return table
    except Exception as e:
        if 'ResourceInUseException' in str(e):
            print(f"Table {DYNAMODB_TABLE} already exists")
        else:
            raise
