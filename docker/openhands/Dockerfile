FROM python:3.12-slim

RUN pip install --no-cache-dir openhands==1.16.0

COPY docker/openhands/openhands-mounted /usr/local/bin/openhands-mounted
RUN chmod 755 /usr/local/bin/openhands-mounted
