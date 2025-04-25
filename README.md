def generate():
        for ev in stream:
            chunk = ev.get("chunk", {})
            if "bytes" in chunk:
                yield chunk["bytes"]

    return {
        "statusCode": 200,
        "isBase64Encoded": True,
        "headers": {
            "Content-Type": "text/plain; charset=utf-8",
            "Transfer-Encoding": "chunked",
            "Access-Control-Allow-Origin": "*"  # if you need CORS
        },
        "body": generate()
    }
