# Model API egress gateway: a strict reverse proxy to one upstream host.
#
# The harness container runs on an internal Docker network with no external
# egress and points its model base_url at this gateway, so the agent can reach
# the model and nothing else.
FROM python:3.11-slim

RUN pip install --no-cache-dir aiohttp

COPY scripts/model_gateway.py /usr/local/bin/model_gateway.py

ENTRYPOINT ["python", "/usr/local/bin/model_gateway.py"]
