"""Bound upload request bodies before multipart parsing, including chunked requests."""
from starlette.responses import JSONResponse


class UploadLimitMiddleware:
    def __init__(self, app, max_bytes=10*1024*1024):
        self.app,self.max_bytes=app,max_bytes

    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope.get('path')!='/documents/upload':
            return await self.app(scope,receive,send)
        size=0;parts=[]
        while True:
            message=await receive()
            if message['type']=='http.disconnect':
                return
            body=message.get('body',b'');size+=len(body)
            if size>self.max_bytes:
                return await JSONResponse({'detail':'upload_too_large'},status_code=413)(scope,receive,send)
            parts.append(body)
            if not message.get('more_body',False):
                break
        delivered=False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered=True
                return {'type':'http.request','body':b''.join(parts),'more_body':False}
            return await receive()
        await self.app(scope,replay,send)
