# ET Slack Alerts

### A serverless Azure Function for Application Insights monitoring and alerts

## Overview

This is a timer-trigger based Azure Function App written in Python to monitor an Azure-based application for any given event (in our case, we focused on exceptions). If events have occurred, it will send alerts to a given slack channel. 

It was *deliberately designed* to be easily reusable and extendable by other teams. The code should be extremely easy to read and work with, even with little or no Python understanding.

### Functionality
The function is scheduled to run every 5 minutes (customisable) and performs the following tasks:
- Authenticates with an Azure Key Vault to retrieve relevant environment variables.
- Queries application insights to capture all log entries returned for a given query and timescale (both customisable).
- Filters unique operations (some log entries cover multiple operations, which can clutter up the returned logs.)
- Sends a second query to application insights to get the entire log history of a given operation.
- Builds a slack message containing a formatted table of unique event triggering operations in the given timeframe, with generated inline links to the relevant log histories.
- Sends a slack alert (via an environment variable-defined webhook url)


<figure>
  <img width="520" alt="image" src="https://github.com/hmcts/et-slack-alerts/assets/18507008/7f0790ae-b49a-42e5-b704-2c0411e149ad">
  <br/><figcaption>Example Slack alert</figcaption>
</figure>


## Justifications
### Why Python?
The reason for choosing Python in this specific instance was to address the ["cold start"](https://mikhail.io/serverless/coldstarts/azure/) problem. It has the lowest execution time variability of all language options, and is second only to C# in median cold start duration.

<img width="689" alt="image" src="https://github.com/hmcts/et-slack-alerts/assets/18507008/ede8fc2a-3e2f-49ac-adb8-e1bcfbc096d8">


### Costs
This particular Azure function is [essentially free](https://azure.microsoft.com/en-gb/pricing/details/functions/#pricing) in terms of both executions (8640 per month, comfortably within the free tier limit of 1 million) and resource consumption (again, easily within the 400k GB-s free tier range).

Alternatives to this approach generally use [Azure Monitor Alerts](https://azure.microsoft.com/en-gb/pricing/details/monitor/#pricing) which are more expensive ($1.50 per alert per month).

### Prerequisites
- [Azure Functions Core Tools](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local?tabs=macos%2Cisolated-process%2Cnode-v4%2Cpython-v2%2Chttp-trigger%2Ccontainer-apps&pivots=programming-language-csharp#install-the-azure-functions-core-tools)
- [Python 3.7+](https://www.python.org/downloads/)
- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
- An Azure account/subscription
- An [Azure Key Vault](https://azure.microsoft.com/en-gb/products/key-vault)
- An [Application Insights](https://learn.microsoft.com/en-us/azure/azure-monitor/app/app-insights-overview?tabs=net) instance you want to monitor

## Environment Variables
This function requires several environment variables (defined within the given keyvault)
- `api-key` - An API key for your given app insights instance. You can obtain one of these via the `API Access` section in the left hand side navigation of your Application Insights instance.
- `app-id` - The 'Instrumentation Key' of the Application Insights instance. This can be found in the top part of the Overview section.
- `slack-webhook-url` - A slack webhook URL for you to send messages to. For this part you will likely need to contact myself (@Danny on Slack) or a Slack administrator to get a custom slack 'app' set up. This is much more trivial than it sounds, a few clicks at most.
- `tenant-id` - Standard for the entire organisation.
- `resource-group-name` - The resource group name that the Application Insights instance is stored within.
- `app-insights-resource-name` - The name of the Application Insights instance.
- `subscription-id` - The subscription id that the Application Insights instance is stored within.

## Installation
1. Clone the repository
```
git clone https://github.com/hmcts/et-slack-alerts.git
```
2. Open the folder and install dependencies
```
cd [wherever you cloned it]
<optionally install a virtual environment using e.g. venv>
pip install -r requirements.txt
```
3. Follow the [instructions here](https://learn.microsoft.com/en-us/azure/azure-functions/functions-get-started?pivots=programming-language-python) to get it running locally and published to a given resource group. If you need any help, feel free to reach out.
4. You will also need to ensure that the Function App has access to the Key Vault.
- Assign a managed identity to your Function App.
- Navigate to `Key Vault` -> `Access Policies` -> `Add Access Policy`. Select `Get`.
- For `Select principal`, choose your Function App's identity.

## Deployment

To deploy the function to Azure:

```bash
# From the alerts directory
cd alerts
func azure functionapp publish <your-function-app-name>
```

### Todo
- Investigate whether it's worth adding a slight delay on log checking to compensate for [Azure's logging latency](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/data-ingestion-time).
- Use the same link generation approach for [Azure Monitor Transaction Logs](https://learn.microsoft.com/en-us/azure/azure-monitor/app/transaction-diagnostics).

### Contributing

Feel free to send a PR with any possible improvements.
