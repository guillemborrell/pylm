from wsgiref.simple_server import make_server
from collections import namedtuple
from pylm.parts.messages_pb2 import PalmMessage, BrokerMessage

Request = namedtuple('Request', 'method data')


class RequestHandler(object):
    def __init__(self, environ, worker):
        self.environ = environ
        self.worker = worker
        length = int(environ.get('CONTENT_LENGTH'), 0)
        self.request = Request(method=environ.get('REQUEST_METHOD'),
                               data=environ.get('wsgi.input').read(length))
        self.message = None

    def handle(self):
        if self.request.method == 'POST':
            try:
                if self.worker:
                    message = BrokerMessage()
                else:
                    message = PalmMessage()

                message.ParseFromString(self.request.data)

                # This exports the message information
                self.message = message
                instruction = message.function.split('.')[1]
                result = getattr(self, instruction)(message.payload)
                message.payload = result
                response_body = message.SerializeToString()
                status = '200 OK'

            except Exception as exc:
                status = '500 Internal Server Error'
                response_body = b''
        else:
            status = '405 Method not allowed'
            response_body = b''

        return status, response_body


class WSGIApplication(object):
    def __init__(self, handler, worker=False):
        self.handler = handler
        self.worker = worker

    def __call__(self, environ, start_response):
        my_handler = self.handler(environ, self.worker)
        status, response = my_handler.handle()
        response_headers = [
            ('Content-Type', 'application/octet-stream'),
            ('Content-Length', str(len(response)))
        ]

        start_response(status, response_headers)
        yield response


class DebugServer(object):
    def __init__(self, host, port, handler):
        my_application = WSGIApplication(handler)
        self.httpd = make_server(host, port, my_application)

    def serve_forever(self):
        self.httpd.serve_forever()

    def handle_request(self):
        self.httpd.handle_request()