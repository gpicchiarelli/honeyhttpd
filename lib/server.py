import sys
import threading
from string import Template
import ssl
import os
import hashlib

import lib.encode as encode


if sys.version_info.major == 2:
    from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
else:
    from http.server import HTTPServer, BaseHTTPRequestHandler

# Handler for HTTP requests
class HTTPHandler(BaseHTTPRequestHandler, object):

    def get_raw_request(self):
        if self.command is None or self.path is None or self.request_version is None:
            return ""

        raw_request = self.command + " " + self.path + " " + self.request_version + "\n" + str(self.headers)
        
        if "Content-Length" in self.headers:
            length = int(self.headers['Content-Length'])
            if sys.version_info.major == 2:
                raw_request += "\n" + self.rfile.read(length)
            else:
                raw_request += "\n" + self.rfile.read(length).decode('utf-8')

        return raw_request

    # For sending errors (Overwrite)
    def send_error(self, code, extra=""):
        
        message = self.responses[code][0]

        code, headers, message = self.on_error(self, code, message)

        desc_template = Template(self.responses[code][1])

        set_path = ""
        set_method = ""

        if hasattr(self, "path"):
            set_path = self.path
        else:
            set_path = path="/"

        if hasattr(self, "command"):
            set_method = self.command
        else:
            set_method = path="UNKNOWN"

        desc = desc_template.substitute(path=set_path, method=set_method, extra=extra)

        error_template = Template(self.error_message_format)
        error_message = error_template.substitute(description=desc, code=str(code), message=message)

        self.send_response(code, message)
        self.send_header("Content-Length", str(len(error_message)))
        if code == 302 or code == 301 or code == 307 or code == 308:
            self.send_header("Location", extra)
        elif code == 401:
            self.send_header("WWW-Authenticate", extra)
        for header in headers:
            self.send_header(header[0], header[1]) 
        self.end_headers()

        self.server.log(self.client_address[0], self.client_address[1], self.get_raw_request(), "Error code " + str(code))
        self.wfile.write(encode.get_plain(error_message))


    # For sending responses
    def send_success_response(self, data, headers):
        print(headers)
        headers, data = self.response_headers(headers, data)

        self.send_response(200)

        for header in headers:
            self.send_header(header[0], header[1]) 

        self.end_headers()

        data = encode.get_plain(data)
        self.server.log(self.client_address[0], self.client_address[1], self.get_raw_request(), data)
        self.wfile.write(data)

    # On GET requests
    def do_GET(self):
        
        code, extra = self.on_request(self)

        if code != None:
            self.send_error(code, extra)
            return

        code, headers, data = self.on_GET(self.path, self.headers)

        if code != 200:
            self.send_error(code, data)
        else:
            self.send_success_response(data, headers)

    # On POST requests
    def do_POST(self):

        code, extra = self.on_request(self)

        if code != None:
            self.send_error(code, extra)
            return

        code, headers, data = self.on_POST(self.path, self.headers)

        if code != 200:
            self.send_error(code, data)
        else:
            self.send_success_response(data, headers)
        
# Main server class. All other servers must inherit from this class
class Server(threading.Thread):

    def __init__(self, domain_name, port, timeout, queue, loggers, ssl_cert=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self._domain_name = domain_name
        self._port = port
        self._queue = queue
        self._timeout = timeout
        self._ssl_cert = ssl_cert
        self._loggers = loggers

    # Setup and start the handler
    def run(self):
        server_address = ('', int(self._port))

        httpd = HTTPServer(server_address, HTTPHandler)
        httpd.log = self.log
        HTTPHandler.server_version = self.server_version()
        HTTPHandler.sys_version = self.system()
        HTTPHandler.error_message_format = self.error_format(self._port)
        HTTPHandler.response_headers = self.response_headers
        HTTPHandler.timeout = self._timeout
        HTTPHandler.responses = self.responses()

        HTTPHandler.on_request = self.on_request
        HTTPHandler.on_GET = self.on_GET
        HTTPHandler.on_POST = self.on_POST
        HTTPHandler.on_error = self.on_error

        if self._ssl_cert is not None:
            httpd.socket = ssl.wrap_socket(httpd.socket, certfile=self._ssl_cert, server_side=True)

        self.ready()

        while os.geteuid() == 0 or os.getegid() == 0:
            pass

        while True:
            httpd.handle_request()

    # Set headers for the response
    def response_headers(self, headers, data):
        for header in headers:
            # Encode the response data if the Content-Encoding is set
            if header[0] == "Content-Encoding":
                if header[1] == "deflate":
                    data = encode.get_deflate(data)
                elif header[1] == "gzip":
                    data = encode.get_gzip(data)
            # Set the timeout 
            elif header[0] == "Connection" and header[1] == "Keep-Alive":
                headers.append(("Keep-Alive", "timeout=" + str(self._timeout) + ", max=100"))

        headers.insert(0, ("Content-Length", str(len(data))))

        return headers, data

    def log(self, remote_ip, remote_port, request, response):

        is_large = False
        if len(request) > 2048:
            large_file = self.save_large(remote_ip, self._port, request)
            request = "Output saved at " + large_file
            is_large = True

        for logger in self._loggers:
            logger.log(remote_ip, remote_port, self._ssl_cert is not None, self._port, request, response, is_large)

    def save_large(self, remote_ip, port, data):
        m = hashlib.md5()
        m.update(data)
        output_filename = "./large/" + remote_ip + "-" + str(port) +  "-" + str(time.time()) + "-" + m.hexdigest() + ".large"

        out_file = open(output_filename, "wb")
        out_file.write(data)
        out_file.close()

        return output_filename

    def ready(self):
        self._queue.put(True)

    def error_format(self):
        raise NotImplementedError

    def on_GET(self):
        raise NotImplementedError

    def on_POST(self):
        raise NotImplementedError