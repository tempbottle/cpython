import os
import sys
import ssl
import pprint
import socket
import threading
import urllib.parse
# Rename HTTPServer to _HTTPServer so as to avoid confusion with HTTPSServer.
from http.server import (HTTPServer as _HTTPServer,
    SimpleHTTPRequestHandler, BaseHTTPRequestHandler)

from test import support

here = os.path.dirname(__file__)

HOST = support.HOST
CERTFILE = os.path.join(here, 'keycert.pem')

# This one's based on HTTPServer, which is based on SocketServer

class HTTPSServer(_HTTPServer):

    def __init__(self, server_address, handler_class, context):
        _HTTPServer.__init__(self, server_address, handler_class)
        self.context = context

    def __str__(self):
        return ('<%s %s:%s>' %
                (self.__class__.__name__,
                 self.server_name,
                 self.server_port))

    def get_request(self):
        # override this to wrap socket with SSL
        try:
            sock, addr = self.socket.accept()
            sslconn = self.context.wrap_socket(sock, server_side=True)
        except socket.error as e:
            # socket errors are silenced by the caller, print them here
            if support.verbose:
                sys.stderr.write("Got an error:\n%s\n" % e)
            raise
        return sslconn, addr

class RootedHTTPRequestHandler(SimpleHTTPRequestHandler):
    # need to override translate_path to get a known root,
    # instead of using os.curdir, since the test could be
    # run from anywhere

    server_version = "TestHTTPS/1.0"
    root = here
    # Avoid hanging when a request gets interrupted by the client
    timeout = 5

    def translate_path(self, path):
        """Translate a /-separated PATH to the local filename syntax.

        Components that mean special things to the local file system
        (e.g. drive or directory names) are ignored.  (XXX They should
        probably be diagnosed.)

        """
        # abandon query parameters
        path = urllib.parse.urlparse(path)[2]
        path = os.path.normpath(urllib.parse.unquote(path))
        words = path.split('/')
        words = filter(None, words)
        path = self.root
        for word in words:
            drive, word = os.path.splitdrive(word)
            head, word = os.path.split(word)
            path = os.path.join(path, word)
        return path

    def log_message(self, format, *args):
        # we override this to suppress logging unless "verbose"
        if support.verbose:
            sys.stdout.write(" server (%s:%d %s):\n   [%s] %s\n" %
                             (self.server.server_address,
                              self.server.server_port,
                              self.request.cipher(),
                              self.log_date_time_string(),
                              format%args))


class StatsRequestHandler(BaseHTTPRequestHandler):
    """Example HTTP request handler which returns SSL statistics on GET
    requests.
    """

    server_version = "StatsHTTPS/1.0"

    def do_GET(self, send_body=True):
        """Serve a GET request."""
        sock = self.rfile.raw._sock
        context = sock.context
        body = pprint.pformat(context.session_stats())
        body = body.encode('utf-8')
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def do_HEAD(self):
        """Serve a HEAD request."""
        self.do_GET(send_body=False)

    def log_request(self, format, *args):
        if support.verbose:
            BaseHTTPRequestHandler.log_request(self, format, *args)


class HTTPSServerThread(threading.Thread):

    def __init__(self, context, host=HOST, handler_class=None):
        self.flag = None
        self.server = HTTPSServer((host, 0),
                                  handler_class or RootedHTTPRequestHandler,
                                  context)
        self.port = self.server.server_port
        threading.Thread.__init__(self)
        self.daemon = True

    def __str__(self):
        return "<%s %s>" % (self.__class__.__name__, self.server)

    def start(self, flag=None):
        self.flag = flag
        threading.Thread.start(self)

    def run(self):
        if self.flag:
            self.flag.set()
        self.server.serve_forever(0.05)

    def stop(self):
        self.server.shutdown()


def make_https_server(case, certfile=CERTFILE, host=HOST, handler_class=None):
    # we assume the certfile contains both private key and certificate
    context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
    context.load_cert_chain(certfile)
    server = HTTPSServerThread(context, host, handler_class)
    flag = threading.Event()
    server.start(flag)
    flag.wait()
    def cleanup():
        if support.verbose:
            sys.stdout.write('stopping HTTPS server\n')
        server.stop()
        if support.verbose:
            sys.stdout.write('joining HTTPS thread\n')
        server.join()
    case.addCleanup(cleanup)
    return server


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description='Run a test HTTPS server. '
                    'By default, the current directory is served.')
    parser.add_argument('-p', '--port', type=int, default=4433,
                        help='port to listen on (default: %(default)s)')
    parser.add_argument('-q', '--quiet', dest='verbose', default=True,
                        action='store_false', help='be less verbose')
    parser.add_argument('-s', '--stats', dest='use_stats_handler', default=False,
                        action='store_true', help='always return stats page')
    args = parser.parse_args()

    support.verbose = args.verbose
    if args.use_stats_handler:
        handler_class = StatsRequestHandler
    else:
        handler_class = RootedHTTPRequestHandler
        handler_class.root = os.getcwd()
    context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
    context.load_cert_chain(CERTFILE)

    server = HTTPSServer(("", args.port), handler_class, context)
    server.serve_forever(0.1)
