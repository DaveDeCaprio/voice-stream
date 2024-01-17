import logging
import multiprocessing
import os
import subprocess

import requests
from pyngrok import ngrok

logger = logging.getLogger(__name__)


def run_quart_ngrok(app):
    """Ensures ngrok is running, then starts Quart app."""
    if is_ngrok_running():
        logger.info("ngrok is running")
    else:
        logger.info("starting ngrok")
        start_ngrok(app.config["HTTP_SERVER_PORT"])
    os.makedirs("target", exist_ok=True)
    with open("target/ngrok.txt", "r") as f:
        app.config["DOMAIN"] = f.read().strip()
    # app.config["DOMAIN"] = domain
    logger.info(f"ngrok tunnel domain: {app.config['DOMAIN']}")
    app.run(port=app.config["HTTP_SERVER_PORT"])


def is_ngrok_running():
    command = "ps x"
    result = subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True
    )
    return "ngrok start" in result.stdout


def start_ngrok(port):
    def run_ngrok():
        os.makedirs("target", exist_ok=True)
        url = ngrok.connect(port).public_url
        domain = url.replace("https://", "")
        with open("target/ngrok.txt", "w") as f:
            f.write(domain)
        resp = requests.get(url, headers={"ngrok-skip-browser-warning": "true"})
        assert resp.status_code == 200, ""
        logger.debug(f"Ngrok response: {resp.text}")
        while True:
            import time

            time.sleep(10000)

    process = multiprocessing.Process(target=run_ngrok)
    process.start()
