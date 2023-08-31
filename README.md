# ET Slack Alerts

### A serverless Azure Function for Application Insights monitoring and alerts

## Overview

This is a timer-trigger based Azure Function App written in Python to monitor an Azure-based application for any given event (in our case, we focused on exceptions). If events have occurred, send alerts to a given slack channel. 

It was deliberately designed to be easily reusable and extendable by other teams. 

The function is scheduled to run every 5 minutes and performs the following tasks:
- Authenticates with an Azure Key Vault to retrieve relevant environment variables.
- Queries application insights for a given query.
- Filters unique operations (some log entries cover multiple operations, which can clutter up the returned logs.)
- Builds a slack message containing error summaries and link to both the exception itself and the traces leading up to and following it.
- Sends a slack alert (via an environment variable-defined webhook url)

<img width="520" alt="image" src="https://github.com/hmcts/et-slack-alerts/assets/18507008/7f0790ae-b49a-42e5-b704-2c0411e149ad">


## Justifications
### Why Python?
As you all know, the HMCTS tech stack nowadays is mostly Java and NodeJS. The reason for choosing Python in this specific instance was to address the ["cold start"](https://mikhail.io/serverless/coldstarts/azure/) problem. It has the lowest execution time variability of all language options, and is second only to C# in median cold start duration.
<img width="689" alt="image" src="https://github.com/hmcts/et-slack-alerts/assets/18507008/ede8fc2a-3e2f-49ac-adb8-e1bcfbc096d8">


### Costs
This particular Azure function is [essentially free](https://azure.microsoft.com/en-gb/pricing/details/functions/#pricing) in terms of both executions (8640 per month, comfortably within the free tier limit of 1 million) and resource consumption (again, within the 40k GB-s free tier range).

Alternatives to this approach generally use [Azure Monitor Alerts](https://azure.microsoft.com/en-gb/pricing/details/monitor/#pricing) which are more expensive ($1.50 per alert per month).

### Prerequisites
- Azure Functions Core Tools
- Python 3.7+
- Azure CLI
- An Azure account/subscription
- An Application Insights instance you want to monitor

## Environment Variables
This function requires several environment variables (defined within the given keyvault)
- `api-key` - An API key for your given app insights instance. You can obtain one of these via the `API Access` section in the left hand side navigation of your Application Insights instance.
- `app-id` - The 'Instrumentation Key' of the Application Insights instance. This can be found in the top part of the Overview section.
- `slack-webhook-url` - A slack webhook URL for you to send messages to. For this part you will likely need to contact myself (@Danny on Slack) or a Slack administrator.
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
3. Follow the [instructions here](https://learn.microsoft.com/en-us/azure/azure-functions/functions-get-started?pivots=programming-language-python) to get it running locally and published to a given resource group. If you need any help feel free to reach out.

### Contributing

Feel free to send a PR for any possible improvements.
