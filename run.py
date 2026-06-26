"""Entry point for the autotester web application.

Runs the Flask development server on port 6444 on all interfaces.
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6444, debug=True)