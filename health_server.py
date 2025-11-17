#!/usr/bin/env python3
"""
Minimal HTTP server for worker healthcheck
Runs alongside RQ worker to satisfy Railway's healthcheck requirement
"""
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health' or self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK - Worker Running')
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Suppress logs to keep worker logs clean
        pass

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"💚 Health server running on port {port}")
    server.serve_forever()

