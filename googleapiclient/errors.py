class HttpError(Exception):
    def __init__(self, resp=None, content=None):
        self.resp = resp or type('obj',(object,),{'status':None})()
        self.content = content
