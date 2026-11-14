"""Run the new viewer independently, without starting database or inference jobs."""
from flask import Flask, redirect
import secrets
from discrepancy_explorer import bp

app = Flask(__name__)
app.secret_key=secrets.token_hex(32)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.register_blueprint(bp)

@app.get('/')
def home():
    return redirect('/explore')

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8020, debug=False)
