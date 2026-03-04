import json
import azure.functions as func
import logging
from urllib.parse import quote
from dataclasses import dataclass
from datetime import datetime, timedelta
import base64
import gzip
from io import BytesIO
import requests
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.monitor.query import LogsQueryClient, LogsQueryStatus

# Replace with your Azure Key Vault URL
key_vault_url = "https://etslackalertkv.vault.azure.net/"

# Authenticates using azure
credential = DefaultAzureCredential()

# Create a SecretClient to interact with the Azure Key Vault
secret_client = SecretClient(vault_url=key_vault_url, credential=credential)

# Create a LogsQueryClient for Application Insights queries using Azure AD auth
logs_client = LogsQueryClient(credential)

# Get secrets from Azure Key Vault
try:
    workspace_id = secret_client.get_secret('app-insights-workspace-id').value
    slack_webhook_url = secret_client.get_secret('slack-webhook-url').value.strip()
    tenant_id = secret_client.get_secret('tenant-id').value
    resource_group_name = secret_client.get_secret('resource-group-name').value
    app_insights_resource_name = secret_client.get_secret('app-insights-resource-name').value
    subscription_id = secret_client.get_secret('subscription-id').value
    
    # Validate webhook URL format
    if not slack_webhook_url.startswith('https://hooks.slack.com/services/'):
        logging.error(f"Invalid Slack webhook URL format: {slack_webhook_url[:50]}...")
    logging.info(f"Loaded webhook URL: {slack_webhook_url[:40]}...")
except Exception as e:
    logging.error(f"Issue communicating with keyvault: {e}")
    exit(1)


# Define a dataclass to store the error logs
@dataclass
class ErrorLog:
    timestamp: str
    error_type: str
    error_message: str
    operation_id: str
    azure_link: str

    def to_dict(self):
        return {
            "timestamp": self.timestamp,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "operation_id": self.operation_id,
            "azure_link": self.azure_link
        }


# Function to query Application Insights using Azure AD authentication
def query_application_insights():
    query = """union(
    app('et-prod').exceptions
    | where timestamp > ago(5min)
    | where not (outerMessage has 'invalid csrf token' and operation_Name == 'POST /dynatraceSyntheticBeaconEndpoint')
    | project timestamp, errorType = type, errorMessage = outerMessage, operation_Id),
(
    app('et-prod').traces
    | where timestamp > ago(5min) and severityLevel == 3
    | where not (message has 'invalid csrf token' and operation_Name == 'POST /dynatraceSyntheticBeaconEndpoint')
    | project timestamp, errorType = message, errorMessage = message, operation_Id 
)
| order by timestamp desc"""
    
    try:
        response = logs_client.query_workspace(
            workspace_id=workspace_id,
            query=query,
            timespan=timedelta(minutes=5)
        )
        
        if response.status == LogsQueryStatus.SUCCESS:
            # Convert the response to match the old format
            result = {
                'tables': [{
                    'rows': []
                }]
            }
            
            # Extract rows from the response
            if response.tables:
                table = response.tables[0]
                for row in table.rows:
                    result['tables'][0]['rows'].append(list(row))
            
            logging.info(result)
            return result
        else:
            logging.error(f"Query failed with status: {response.status}")
            return {'tables': [{'rows': []}]}
    except Exception as e:
        logging.error(f"Error querying Application Insights: {e}")
        return {'tables': [{'rows': []}]}


# Function to get the table rows from the raw JSON response
def get_rows_from_json(rows_as_json):
    list_of_rows = rows_as_json['tables'][0]['rows']
    logging.info(list_of_rows)
    error_logs = [ErrorLog(*row + ['']) for row in list_of_rows]
    return error_logs


# Function to get the unique operation IDs from the table rows (operations often raise several exceptions)
def unique_exceptions(all_exceptions):
    # Sort by timestamp to ensure we get the first exception for each operation
    all_exceptions.sort(key=lambda x: x.timestamp)
    unique_logs = []
    unique_operations_read = []

    # Get the first error-causing operation
    for log in all_exceptions:
        logging.info(log.operation_id)
        if log.operation_id not in unique_operations_read:
            unique_operations_read.append(log.operation_id)
            unique_logs.append(log)

    # Add the Azure link to each unique error-causing operation
    for i in unique_logs:
        azure_link = generate_azure_link(tenant_id, subscription_id, app_insights_resource_name, 'microsoft.insights',
                                         app_insights_resource_name, i.operation_id)
        i.azure_link = azure_link
    return unique_logs


# Function to get the unique operation IDs from the table rows (operations often raise several exceptions)
def get_unique_operation_ids(list_of_errors):
    return list(set([row.operation_id for row in list_of_errors]))


# Function to get the number of errors and unique operations
def get_counts(rows, operation_ids):
    return len(rows), len(operation_ids)


# Function to perform further queries to get specific logs relating to a given operation ID
def parametrise_query(operation_id):
    return f'union traces, exceptions, requests | where operation_Id == "{operation_id}"'


# Extremely ugly function to generate the Azure link to the logs for a given operation ID
def generate_azure_link(tenant_id, subscription_id, resource_group, provider, component, operation_id):
    base_url = "https://portal.azure.com#@" + tenant_id
    print(operation_id)
    resource_path = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/{provider}/components/{component}"
    compressed_query = compress_and_encode_query(parametrise_query(operation_id))

    # Calculate timespan for time surrounding the error
    end_time = datetime.utcnow().isoformat() + "Z"
    start_time = (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z"
    timespan = f"{start_time}/{end_time}"

    return f"{base_url}/blade/Microsoft_OperationsManagementSuite_Workspace/Logs.ReactView/resourceId/{quote(resource_path, safe='')}/source/LogsBlade.AnalyticsShareLinkToQuery/q/{quote(compressed_query, safe='')}/timespan/{quote(timespan, safe='')}"


# Function to compress and encode the query string - needed for the Azure link
def compress_and_encode_query(query_str):
    compressed = BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode='wb') as f:
        f.write(query_str.encode('utf-8'))
    return base64.b64encode(compressed.getvalue()).decode('utf-8')


# Function to generate the Slack message
def generate_message(errors, error_counts, truncated=False, total_errors=0):
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "New Exception Alert"
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": "*Number of errors*"},
                {"type": "mrkdwn", "text": f"{error_counts[0]}"},
                {"type": "mrkdwn", "text": "*Number of unique operations*"},
                {"type": "mrkdwn", "text": f"{error_counts[1]}"}
            ]
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": "*Initial Exception Type*"},
                {"type": "mrkdwn", "text": "*Operation*"}
            ]
        }
    ]
    blocks.extend(errors)
    
    if truncated:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":warning: *Message truncated* - Showing {len(errors)} of {total_errors} unique operations due to Slack's 50 block limit. Check Application Insights for full details."
            }
        })
    
    message = {"blocks": blocks}

    return message


# Function to build the Slack table of errors
def build_error_table(rows):
    output = []
    for i, j in enumerate(rows):
        # Truncate long URLs and validate
        azure_link = j.azure_link[:2000] if len(j.azure_link) > 2000 else j.azure_link
        operation_id_display = j.operation_id[:50] if len(j.operation_id) > 50 else j.operation_id
        error_type_display = j.error_type[:100] if j.error_type and len(j.error_type) > 100 else (j.error_type or 'Unknown')
        
        logging.info(f"Azure link length: {len(j.azure_link)}, Operation ID: {j.operation_id}")
        
        output.append({"type": "section",
                       "fields": [{"type": "mrkdwn", "text": error_type_display},
                                  {"type": "mrkdwn", "text": f'<{azure_link}|{operation_id_display}>'}]
                       })
    return output


app = func.FunctionApp()


@app.function_name(name="AzureTrigger")
@app.schedule(schedule="0 */5 * * * *", arg_name="AzureTrigger", run_on_startup=True)
def trigger_function(AzureTrigger: func.TimerRequest) -> None:
    query_data = query_application_insights()
    rows = get_rows_from_json(query_data)
    operation_ids = get_unique_operation_ids(rows)
    logging.info(query_data)
    if len(operation_ids) == 0:
        logging.info("no events found")
        return
    all_classes = unique_exceptions(rows)
    counts = get_counts(rows, operation_ids)
    
    # Slack has a limit of 50 blocks per message
    # Header (1) + divider (1) + counts section (1) + divider (1) + header row (1) = 5 blocks
    # Each error takes 1 block, so max errors = 50 - 5 - 1 (for truncation notice) = 44
    MAX_ERRORS = 44
    truncated = len(all_classes) > MAX_ERRORS
    errors_to_show = all_classes[:MAX_ERRORS] if truncated else all_classes
    
    error_data = build_error_table(errors_to_show)
    built_message = generate_message(error_data, counts, truncated, len(all_classes))
    
    # Log message size for debugging
    message_json = json.dumps(built_message)
    logging.info(f"Message size: {len(message_json)} bytes, blocks: {len(built_message.get('blocks', []))}")
    
    try:
        response_from_slack = requests.post(slack_webhook_url, json=built_message, timeout=10)
        response_from_slack.raise_for_status()
        logging.info(f"Successfully posted to Slack: {response_from_slack.status_code}")
    except requests.exceptions.HTTPError as e:
        logging.error(f"Slack API rejected request: {e.response.status_code} - {e.response.text}")
        logging.error(f"Message preview: {message_json[:500]}...")
        raise
    except Exception as e:
        logging.error(f"Failed to post to Slack: {e}")
        raise
    return
