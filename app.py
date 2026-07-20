# app.py
import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from functools import wraps
import uuid
import hashlib

# Configuration
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///movies.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Admin credentials
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'password123'

# Image upload configuration
UPLOAD_FOLDER = 'static/posters'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Coupon codes storage (in production use database)
VALID_COUPONS = {
    'promo1234': {'valid': True, 'expires': None},  # Never expires
    # Add more coupons as needed
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

db = SQLAlchemy(app)

# Database Model
class Movie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    movie_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    poster_filename = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def get_embed_url(self):
        return f"https://streamimdb.ru/embed/movie/{self.movie_id}"

    def to_dict(self):
        return {
            'id': self.id,
            'movie_id': self.movie_id,
            'name': self.name,
            'description': self.description,
            'poster_url': self.poster_path(),
            'embed_url': self.get_embed_url()
        }

    def poster_path(self):
        if self.poster_filename:
            return url_for('static', filename=f'posters/{self.poster_filename}', _external=True)
        return url_for('static', filename='default-poster.jpg', _external=True)

# Admin login decorator
def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# Create tables
with app.app_context():
    db.create_all()

# Helper: Save uploaded poster
def save_poster(file):
    if file and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return filename
    return None

# ------------------- API ROUTES (for Android App) -------------------
@app.route('/api/movies', methods=['GET'])
def api_get_movies():
    """Get all movies list"""
    movies = Movie.query.order_by(Movie.created_at.desc()).all()
    return jsonify({
        'success': True,
        'movies': [m.to_dict() for m in movies]
    })

@app.route('/api/movie/<string:movie_id>', methods=['POST'])
def api_get_movie_with_coupon(movie_id):
    """Get movie details - requires coupon code in request body"""
    data = request.get_json()
    coupon_code = data.get('coupon_code', '').strip()
    
    # Validate coupon
    if not validate_coupon(coupon_code):
        return jsonify({
            'success': False,
            'error': 'Invalid or expired coupon code'
        }), 401
    
    movie = Movie.query.filter_by(movie_id=movie_id).first()
    if not movie:
        return jsonify({
            'success': False,
            'error': 'Movie not found'
        }), 404
    
    return jsonify({
        'success': True,
        'movie': movie.to_dict()
    })

@app.route('/api/validate-coupon', methods=['POST'])
def api_validate_coupon():
    """Validate coupon code only"""
    data = request.get_json()
    coupon_code = data.get('coupon_code', '').strip()
    
    if validate_coupon(coupon_code):
        return jsonify({'success': True, 'valid': True})
    return jsonify({'success': False, 'valid': False}), 401

def validate_coupon(coupon_code):
    """Validate coupon code"""
    if not coupon_code:
        return False
    coupon = VALID_COUPONS.get(coupon_code)
    if not coupon or not coupon.get('valid', False):
        return False
    # Check expiration if set
    if coupon.get('expires'):
        from datetime import datetime
        if datetime.now() > coupon['expires']:
            return False
    return True

# ------------------- ADMIN ROUTES -------------------
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            flash('Logged in successfully!', 'success')
            return redirect(url_for('admin'))
        else:
            flash('Invalid credentials!', 'danger')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    flash('Logged out successfully!', 'success')
    return redirect(url_for('admin_login'))

@app.route('/admin/coupons', methods=['GET', 'POST'])
@admin_login_required
def admin_coupons():
    if request.method == 'POST':
        coupon_code = request.form.get('coupon_code', '').strip().upper()
        action = request.form.get('action')
        
        if action == 'add':
            if coupon_code and coupon_code not in VALID_COUPONS:
                VALID_COUPONS[coupon_code] = {'valid': True, 'expires': None}
                flash(f'Coupon "{coupon_code}" added!', 'success')
            else:
                flash('Coupon already exists or invalid!', 'danger')
        elif action == 'remove':
            if coupon_code in VALID_COUPONS:
                del VALID_COUPONS[coupon_code]
                flash(f'Coupon "{coupon_code}" removed!', 'success')
            else:
                flash('Coupon not found!', 'danger')
    
    return render_template('admin_coupons.html', coupons=VALID_COUPONS)

@app.route('/admin', methods=['GET', 'POST'])
@admin_login_required
def admin():
    if request.method == 'POST':
        movie_id = request.form.get('movie_id', '').strip()
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        poster = request.files.get('poster')

        if not movie_id or not name:
            flash('Movie ID and Name are required!', 'danger')
            return redirect(url_for('admin'))

        existing = Movie.query.filter_by(movie_id=movie_id).first()
        if existing:
            flash(f'Movie ID {movie_id} already exists!', 'danger')
            return redirect(url_for('admin'))

        poster_filename = save_poster(poster) if poster else None

        new_movie = Movie(
            movie_id=movie_id,
            name=name,
            description=description,
            poster_filename=poster_filename
        )
        db.session.add(new_movie)
        db.session.commit()
        flash(f'Movie "{name}" added successfully!', 'success')
        return redirect(url_for('admin'))

    movies = Movie.query.order_by(Movie.created_at.desc()).all()
    return render_template('admin.html', movies=movies)

@app.route('/admin/edit/<int:movie_id>', methods=['GET', 'POST'])
@admin_login_required
def edit_movie(movie_id):
    movie = Movie.query.get_or_404(movie_id)
    if request.method == 'POST':
        movie.name = request.form.get('name', '').strip()
        movie.description = request.form.get('description', '').strip()
        new_movie_id = request.form.get('movie_id', '').strip()
        if new_movie_id and new_movie_id != movie.movie_id:
            if Movie.query.filter_by(movie_id=new_movie_id).first():
                flash('Movie ID already exists!', 'danger')
                return redirect(url_for('edit_movie', movie_id=movie_id))
            movie.movie_id = new_movie_id

        if 'poster' in request.files:
            poster = request.files['poster']
            if poster and poster.filename:
                if movie.poster_filename:
                    old_path = os.path.join(app.config['UPLOAD_FOLDER'], movie.poster_filename)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                new_filename = save_poster(poster)
                if new_filename:
                    movie.poster_filename = new_filename

        db.session.commit()
        flash('Movie updated!', 'success')
        return redirect(url_for('admin'))

    return render_template('edit_movie.html', movie=movie)

@app.route('/admin/delete/<int:movie_id>')
@admin_login_required
def delete_movie(movie_id):
    movie = Movie.query.get_or_404(movie_id)
    if movie.poster_filename:
        poster_path = os.path.join(app.config['UPLOAD_FOLDER'], movie.poster_filename)
        if os.path.exists(poster_path):
            os.remove(poster_path)
    db.session.delete(movie)
    db.session.commit()
    flash('Movie deleted!', 'success')
    return redirect(url_for('admin'))

# ------------------- PUBLIC ROUTES -------------------
@app.route('/')
def home():
    movies = Movie.query.order_by(Movie.created_at.desc()).all()
    return render_template('home.html', movies=movies)

@app.route('/watch/<string:movie_id>')
def watch(movie_id):
    movie = Movie.query.filter_by(movie_id=movie_id).first_or_404()
    embed_url = movie.get_embed_url()
    return render_template('watch.html', movie=movie, embed_url=embed_url)

# ------------------- TEMPLATES -------------------
os.makedirs('templates', exist_ok=True)

templates = {
    'base.html': '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}MovieStream{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        body { background: #0f0f0f; color: #fff; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .navbar-dark { background: #1a1a1a !important; }
        .movie-card { transition: transform 0.2s; cursor: pointer; background: #1a1a1a; border-radius: 8px; overflow: hidden; }
        .movie-card:hover { transform: scale(1.02); }
        .poster-img { width: 100%; height: 300px; object-fit: cover; }
        .movie-title { font-size: 1.1rem; font-weight: bold; margin: 10px; }
        .embed-container { position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; max-width: 100%; background: #000; }
        .embed-container iframe { position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: 0; }
        .flash-message { position: fixed; top: 20px; right: 20px; z-index: 9999; }
        .coupon-modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.9); z-index: 10000; justify-content: center; align-items: center; }
        .coupon-modal.active { display: flex; }
        .coupon-box { background: #1a1a1a; padding: 30px; border-radius: 10px; text-align: center; max-width: 400px; }
    </style>
</head>
<body>
    <nav class="navbar navbar-dark bg-dark mb-4">
        <div class="container">
            <a class="navbar-brand" href="{{ url_for('home') }}">🍿 MovieStream</a>
            <div>
                <a href="{{ url_for('home') }}" class="btn btn-outline-light btn-sm me-2">Home</a>
                
            </div>
        </div>
    </nav>
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }} alert-dismissible fade show flash-message" role="alert">
                        {{ message }}
                        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>''',

    'admin_login.html': '''{% extends "base.html" %}
{% block title %}Admin Login{% endblock %}
{% block content %}
<div class="row justify-content-center">
    <div class="col-md-4">
        <div class="card bg-dark">
            <div class="card-header text-center">
                <h3>Admin Login</h3>
            </div>
            <div class="card-body">
                <form method="POST">
                    <div class="mb-3">
                        <label>Username</label>
                        <input type="text" name="username" class="form-control" required>
                    </div>
                    <div class="mb-3">
                        <label>Password</label>
                        <input type="password" name="password" class="form-control" required>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Login</button>
                </form>
            </div>
        </div>
    </div>
</div>
{% endblock %}''',

    'admin_coupons.html': '''{% extends "base.html" %}
{% block title %}Manage Coupons{% endblock %}
{% block content %}
<h1>🎫 Manage Coupon Codes</h1>
<div class="row mt-4">
    <div class="col-md-5">
        <div class="card bg-dark">
            <div class="card-header">Add New Coupon</div>
            <div class="card-body">
                <form method="POST">
                    <input type="hidden" name="action" value="add">
                    <div class="mb-3">
                        <label>Coupon Code</label>
                        <input type="text" name="coupon_code" class="form-control" placeholder="e.g., PROMO2024" required>
                    </div>
                    <button type="submit" class="btn btn-success">Add Coupon</button>
                </form>
            </div>
        </div>
    </div>
    <div class="col-md-7">
        <div class="card bg-dark">
            <div class="card-header">Active Coupons</div>
            <div class="card-body">
                <div class="row">
                    {% for code, info in coupons.items() %}
                    <div class="col-md-6 mb-2">
                        <div class="d-flex justify-content-between align-items-center bg-secondary p-2 rounded">
                            <code class="text-white">{{ code }}</code>
                            <form method="POST" style="display:inline">
                                <input type="hidden" name="action" value="remove">
                                <input type="hidden" name="coupon_code" value="{{ code }}">
                                <button type="submit" class="btn btn-sm btn-danger">Remove</button>
                            </form>
                        </div>
                    </div>
                    {% else %}
                    <p class="text-muted">No coupons added yet.</p>
                    {% endfor %}
                </div>
            </div>
        </div>
    </div>
</div>
<div class="mt-3">
    <a href="{{ url_for('admin') }}" class="btn btn-secondary">&larr; Back to Admin</a>
</div>
{% endblock %}''',

    'home.html': '''{% extends "base.html" %}
{% block title %}Home - MovieStream{% endblock %}
{% block content %}
<h1 class="mb-4">🎬 Latest Movies</h1>
<div class="row">
    {% for movie in movies %}
    <div class="col-md-3 col-sm-6 mb-4">
        <div class="movie-card" onclick="showCouponModal('{{ movie.movie_id }}')">
            <div class="position-relative">
                <img src="{{ movie.poster_path() }}" class="poster-img" alt="{{ movie.name }}">
                <div class="play-overlay position-absolute top-50 start-50 translate-middle text-white">
                    <i class="fas fa-play-circle fa-4x" style="opacity: 0.9; text-shadow: 2px 2px 10px black;"></i>
                </div>
            </div>
            <div class="movie-title">{{ movie.name }}</div>
            <div class="px-3 pb-3 small text-secondary">{{ movie.description[:80] }}{% if movie.description|length > 80 %}...{% endif %}</div>
        </div>
    </div>
    {% else %}
    <div class="col-12">
        <div class="alert alert-info">No movies added yet. Go to Admin Panel to add some!</div>
    </div>
    {% endfor %}
</div>

<div id="couponModal" class="coupon-modal">
    <div class="coupon-box">
        <h3>Enter Coupon Code</h3>
        <input type="text" id="couponCode" class="form-control mb-3" placeholder="Enter coupon code">
        <input type="hidden" id="selectedMovieId">
        <button onclick="validateCoupon()" class="btn btn-primary">Watch Now</button>
        <button onclick="closeCouponModal()" class="btn btn-secondary mt-2">Cancel</button>
        <p id="couponError" class="text-danger mt-2" style="display:none;">Invalid coupon code!</p>
    </div>
</div>

<script>
let pendingMovieId = null;

function showCouponModal(movieId) {
    pendingMovieId = movieId;
    document.getElementById('couponModal').classList.add('active');
    document.getElementById('couponCode').value = '';
    document.getElementById('couponError').style.display = 'none';
}

function closeCouponModal() {
    document.getElementById('couponModal').classList.remove('active');
    pendingMovieId = null;
}

function validateCoupon() {
    const couponCode = document.getElementById('couponCode').value;
    if (!couponCode) {
        document.getElementById('couponError').style.display = 'block';
        return;
    }
    
    fetch('/api/validate-coupon', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({coupon_code: couponCode})
    })
    .then(res => res.json())
    .then(data => {
        if (data.success && data.valid) {
            window.location.href = '/watch/' + pendingMovieId + '?coupon=' + encodeURIComponent(couponCode);
        } else {
            document.getElementById('couponError').style.display = 'block';
        }
    })
    .catch(() => {
        document.getElementById('couponError').style.display = 'block';
    });
}
</script>
{% endblock %}''',

    'watch.html': '''{% extends "base.html" %}
{% block title %}Watch {{ movie.name }}{% endblock %}
{% block content %}
<div class="row">
    <div class="col-lg-8 mx-auto">
        <div class="mb-3">
            <a href="{{ url_for('home') }}" class="btn btn-secondary">&larr; Back to Home</a>
        </div>
        <h2>{{ movie.name }}</h2>
        <div class="embed-container my-3">
            <iframe src="{{ embed_url }}" frameborder="0" allowfullscreen></iframe>
        </div>
        <div class="card bg-dark mt-3">
            <div class="card-body">
                <h5>Description</h5>
                <p>{{ movie.description or 'No description provided.' }}</p>
            </div>
        </div>
    </div>
</div>
{% endblock %}''',

    'admin.html': '''{% extends "base.html" %}
{% block title %}Admin Panel{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1>🎥 Admin Panel</h1>
    <div>
        <a href="{{ url_for('admin_coupons') }}" class="btn btn-info me-2">Manage Coupons</a>
        <a href="{{ url_for('admin_logout') }}" class="btn btn-danger">Logout</a>
    </div>
</div>

<div class="card bg-dark mb-5">
    <div class="card-body">
        <h3>Add New Movie</h3>
        <form method="POST" enctype="multipart/form-data">
            <div class="row">
                <div class="col-md-6 mb-3">
                    <label>Movie ID</label>
                    <input type="text" name="movie_id" class="form-control" required>
                </div>
                <div class="col-md-6 mb-3">
                    <label>Movie Name</label>
                    <input type="text" name="name" class="form-control" required>
                </div>
                <div class="col-12 mb-3">
                    <label>Description</label>
                    <textarea name="description" class="form-control" rows="3"></textarea>
                </div>
                <div class="col-12 mb-3">
                    <label>Poster Image</label>
                    <input type="file" name="poster" class="form-control" accept="image/*">
                </div>
                <div class="col-12">
                    <button type="submit" class="btn btn-primary">Add Movie</button>
                </div>
            </div>
        </form>
    </div>
</div>

<h2>Existing Movies</h2>
<table class="table table-dark table-hover">
    <thead>
        <tr><th>ID</th><th>Movie ID</th><th>Name</th><th>Poster</th><th>Actions</th></tr>
    </thead>
    <tbody>
        {% for movie in movies %}
        <tr>
            <td>{{ movie.id }}</td>
            <td>{{ movie.movie_id }}</td>
            <td>{{ movie.name }}</td>
            <td><img src="{{ movie.poster_path() }}" height="50"></td>
            <td>
                <a href="{{ url_for('edit_movie', movie_id=movie.id) }}" class="btn btn-sm btn-warning">Edit</a>
                <a href="{{ url_for('delete_movie', movie_id=movie.id) }}" class="btn btn-sm btn-danger" onclick="return confirm('Delete?')">Delete</a>
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endblock %}''',

    'edit_movie.html': '''{% extends "base.html" %}
{% block title %}Edit Movie{% endblock %}
{% block content %}
<h1>✏️ Edit Movie: {{ movie.name }}</h1>
<div class="card bg-dark mt-3">
    <div class="card-body">
        <form method="POST" enctype="multipart/form-data">
            <div class="mb-3">
                <label>Movie ID</label>
                <input type="text" name="movie_id" class="form-control" value="{{ movie.movie_id }}" required>
            </div>
            <div class="mb-3">
                <label>Movie Name</label>
                <input type="text" name="name" class="form-control" value="{{ movie.name }}" required>
            </div>
            <div class="mb-3">
                <label>Description</label>
                <textarea name="description" class="form-control" rows="3">{{ movie.description or '' }}</textarea>
            </div>
            <div class="mb-3">
                <label>Current Poster</label><br>
                <img src="{{ movie.poster_path() }}" height="150">
            </div>
            <div class="mb-3">
                <label>Change Poster (optional)</label>
                <input type="file" name="poster" class="form-control" accept="image/*">
            </div>
            <button type="submit" class="btn btn-success">Save Changes</button>
            <a href="{{ url_for('admin') }}" class="btn btn-secondary">Cancel</a>
        </form>
    </div>
</div>
{% endblock %}'''
}

for filename, content in templates.items():
    with open(os.path.join('templates', filename), 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
