import os

import azure.functions as func
import logging
import requests
import os
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient


# Replace with your Azure Key Vault URL and secret name
key_vault_url = "https://et-aat.vault.azure.net/"
secret_name = "slack-webhook-url"

# Create a DefaultAzureCredential instance to authenticate
# using the managed identity of the Azure Function
credential = DefaultAzureCredential()

# Create a SecretClient to interact with the Azure Key Vault
secret_client = SecretClient(vault_url=key_vault_url, credential=credential)

app = func.FunctionApp()


@app.function_name(name="AzureTrigger")
@app.route(route="hello")
def test_function(req: func.HttpRequest) -> func.HttpResponse:
    requests.post(secret_client.get_secret(secret_name), json={"text": "Hello from Azure!"})
    return func.HttpResponse("AzureTrigger function processed a request!")

# Function to construct the link to the log entry in Azure portal
def construct_log_link(subscription_id, resource_group_name, app_insights_resource_name, operation_id):
    # Construct the URL
    base_url = "https://portal.azure.com/#@"
    resource_id = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}/providers/Microsoft" \
                  f".Insights/components/{app_insights_resource_name}"
    logs_query = "/logs?query=traces"
    log_link = f"{base_url}{subscription_id}{resource_id}{logs_query} | where operation_Id == '{operation_id}'"

    return log_link
