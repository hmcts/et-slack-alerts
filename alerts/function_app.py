import azure.functions as func
import logging

app = func.FunctionApp()

@app.function_name(name="AzureTrigger")
@app.route(route="hello")
def test_function(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse("AzureTrigger function processed a request!")