# Option 1: ASGI with Hypercorn (recommended for production)
web: hypercorn asgi_app:asgi_app --bind 0.0.0.0:$PORT

# Option 2: WSGI with Gunicorn (alternative)
# web: gunicorn wsgi_app:wsgi_app --bind 0.0.0.0:$PORT --workers 1

# Option 3: Original Flask development server (not recommended for production)
# web: python run.py
