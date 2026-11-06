FROM apify/actor-python:3.13

COPY --chown=myuser:myuser connector/requirements.txt ./connector/requirements.txt
RUN pip install --no-cache-dir -r connector/requirements.txt

COPY --chown=myuser:myuser scripts/ ./scripts/
COPY --chown=myuser:myuser skills/ ./skills/
COPY --chown=myuser:myuser references/ ./references/
COPY --chown=myuser:myuser connector/ ./connector/

CMD ["python3", "connector/main.py"]
