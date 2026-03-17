import json

def handler(request):
    return Response(
        json.dumps({'status': 'ok', 'message': 'MatTrack API is running'}),
        200,
        headers={
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        }
    )
