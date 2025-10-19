"""
Page Routes
Handles all HTML page rendering routes
"""
from flask import Blueprint, render_template

# Create blueprint for page routes
page_routes = Blueprint('page_routes', __name__)


@page_routes.route('/')
def index():
    return render_template('index.html')


@page_routes.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')


@page_routes.route('/history')
def history():
    return render_template('history.html')


@page_routes.route('/config')
def config():
    return render_template('config.html')


@page_routes.route('/nsn-test')
def nsn_test():
    return render_template('nsn_test.html')


@page_routes.route('/c-client-test')
def c_client_test():
    """C-Client WebSocket test page"""
    return render_template('c_client_test.html')

