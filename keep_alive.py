from threading import Thread
from flask import Flask


app = Flask("keep_alive")


@app.route("/")
def home():
return "OK"


def keep_alive(host="0.0.0.0", port=8080):
def run():
app.run(host=host, port=port)
thread = Thread(target=run, daemon=True)
thread.start()
