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

# Replace with your Azure Key Vault URL
key_vault_url = "https://etslackalertkv.vault.azure.net/"

# Authenticates using azure
credential = DefaultAzureCredential()

# Create a SecretClient to interact with the Azure Key Vault
secret_client = SecretClient(vault_url=key_vault_url, credential=credential)

# Get secrets from Azure Key Vault
try:
    api_key = secret_client.get_secret('api-key').value
    app_id = secret_client.get_secret('app-id').value
    slack_webhook_url = secret_client.get_secret('slack-webhook-url').value
    tenant_id = secret_client.get_secret('tenant-id').value
    resource_group_name = secret_client.get_secret('resource-group-name').value
    app_insights_resource_name = secret_client.get_secret('app-insights-resource-name').value
    subscription_id = secret_client.get_secret('subscription-id').value
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


# Function to query Application Insights
def query_application_insights():
    url = f"https://api.applicationinsights.io/v1/apps/{app_id}/query"
    headers = {'x-api-key': api_key}
    data = {
        "query": """union(
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
    }
    response = requests.post(url, headers=headers, json=data)
    logging.info(response.json())
    return response.json()


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
def generate_message(errors, error_counts):
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
    message = {"blocks": blocks}

    return message


# Function to build the Slack table of errors
def build_error_table(rows):
    output = []
    for i, j in enumerate(rows):
        output.append({"type": "section",
                       "fields": [{"type": "mrkdwn", "text": f'{j.error_type}'},
                                  {"type": "mrkdwn", "text": f'<{j.azure_link}|{j.operation_id}>'}]
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
    error_data = build_error_table(all_classes)
    built_message = generate_message(error_data, counts)
    response_from_slack = requests.post(slack_webhook_url, json=built_message)
    if response_from_slack.raise_for_status() is not None:
        logging.error(response_from_slack.raise_for_status())
    logging.info(func.HttpResponse(f"{response_from_slack.status_code}, {response_from_slack.text}"))
    return
