
import logging
from typing import Dict, Any
from http import HTTPStatus

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3_BUCKET = "pocbotai"
S3_KEY    = "DBcheck.csv"

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler for processing Bedrock agent requests.
    
    Args:
        event (Dict[str, Any]): The Lambda event containing action details
        context (Any): The Lambda context object
    
    Returns:
        Dict[str, Any]: Response containing the action execution results
    
    Raises:
        KeyError: If required fields are missing from the event
    """
    try:
        action_group = event['actionGroup']
        function = event['function']
        message_version = event.get('messageVersion',1)
        parameters = event.get('parameters', [])

        try:
    s3 = boto3.client('s3')
    obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
    df  = pd.read_csv(StringIO(obj['Body'].read().decode('utf-8')))
    df["Data Point Name"] = df["Data Point Name"].str.strip().str.lower()
except Exception as e:
    print("Failed to load CSV:", str(e))
    df = pd.DataFrame()

RESPONSE_COLUMNS = ["P119","P143","P3021","P3089","P3368","P3019","P3090","P3373"]

def get_medication(name, selected_columns, display_mode):
    name = name.strip().lower()
    esc  = re.escape(name)
    matched = df[df["Data Point Name"].str.contains(esc, case=False, na=False, regex=True)]

    if matched.empty:
        return {"error": f"No records found for '{name}'"}

    if display_mode == "row-wise":
        rows = matched.replace({pd.NaT: None}).to_dict(orient="records")
        return {
            "response_type": "row_wise",
            "data": rows,
            "message": f"Found {len(rows)} row(s) for '{name}'"
        }

    # Column-wise
    cols = RESPONSE_COLUMNS if selected_columns.lower() == "all" else [
        c for c in selected_columns.split(",") if c.strip() in RESPONSE_COLUMNS
    ]
    out = []
    for _, r in matched.iterrows():
        avail = {c: r[c] for c in cols if pd.notna(r[c])}
        if avail:
            out.append({"data_point": r["Data Point Name"], "columns": avail})
    return {
        "response_type": "column_wise",
        "data": out,
        "message": f"Found {len(out)} column-wise result(s) for '{name}'"
    }
        params = {p.get("name"): p.get("value") for p in event.get("parameters", [])}
        cond  = (params.get("condition")         or "").strip()
        mode  = (params.get("display_mode")      or "row-wise").strip().lower()
        cols  = (params.get("selected_column")   or "all").strip()

        if not cond:
            raise ValueError("Missing required parameter: condition")

        result = get_medication(cond, cols, mode)
        action_response = {
            'actionGroup': action_group,
            'function': function,
            'functionResponse': {
                'responseBody': result
            }
        }
        response = {
            'response': action_response,
            'messageVersion': message_version
        }

        logger.info('Response: %s', response)
        return response

    except KeyError as e:
        logger.error('Missing required field: %s', str(e))
        return {
            'statusCode': HTTPStatus.BAD_REQUEST,
            'body': f'Error: {str(e)}'
        }
    except Exception as e:
        logger.error('Unexpected error: %s', str(e))
        return {
            'statusCode': HTTPStatus.INTERNAL_SERVER_ERROR,
            'body': 'Internal server error'
        }
