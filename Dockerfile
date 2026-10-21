FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY driver_demo/ driver_demo/
# Scenarios are owned by the hub repo (hub/schema/demo); scenarios/ is a committed copy
# refreshed by scripts/sync-scenarios.sh so this image builds self-contained.
COPY scenarios/ /app/scenarios/

ENV DEMO_SCENARIO_DIR=/app/scenarios

ENTRYPOINT ["python", "-m", "driver_demo.main"]
