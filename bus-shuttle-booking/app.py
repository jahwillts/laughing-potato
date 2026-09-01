import os, random, string, json, io, base64
from datetime import datetime, date, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify, send_file, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, or_, and_
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'bus-shuttle-secret-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///bus.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
app.config['QR_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'qrcodes')
app.config['TICKET_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'tickets')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024

for folder in (app.config['UPLOAD_FOLDER'], app.config['QR_FOLDER'], app.config['TICKET_FOLDER']):
    os.makedirs(folder, exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

LUGGAGE_INCLUDED_KG = 15
LUGGAGE_PRICE_PER_KG = 1.0
SEAT_MULTIPLIERS = {'premium': 1.25, 'window': 1.05, 'aisle': 1.0}

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(50))
    role = db.Column(db.String(20), nullable=False)  # passenger, driver, operator, admin, station_admin
    station_id = db.Column(db.Integer, db.ForeignKey('station.id'), nullable=True)
    station = db.relationship('Station', backref='users')
    password_hash = db.Column(db.String(256), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    license_number = db.Column(db.String(80))
    vehicle_info = db.Column(db.String(255))
    background_status = db.Column(db.String(30), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

class Station(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    city = db.Column(db.String(120), nullable=False)
    country = db.Column(db.String(120), default='')
    address = db.Column(db.Text)
    phone = db.Column(db.String(50))
    email = db.Column(db.String(120))
    is_approved = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Terminal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    city = db.Column(db.String(120), nullable=False)
    country = db.Column(db.String(120), default='')
    code = db.Column(db.String(20), unique=True)
    station_id = db.Column(db.Integer, db.ForeignKey('station.id'), nullable=True)
    station = db.relationship('Station', backref='terminals')
    is_active = db.Column(db.Boolean, default=True)

class Route(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    origin_id = db.Column(db.Integer, db.ForeignKey('terminal.id'), nullable=False)
    destination_id = db.Column(db.Integer, db.ForeignKey('terminal.id'), nullable=False)
    name = db.Column(db.String(120))
    distance_km = db.Column(db.Float, default=0)
    duration_min = db.Column(db.Integer, default=0)
    base_price = db.Column(db.Float, nullable=False)
    station_id = db.Column(db.Integer, db.ForeignKey('station.id'), nullable=True)
    station = db.relationship('Station', backref='routes')
    is_active = db.Column(db.Boolean, default=True)
    origin = db.relationship('Terminal', foreign_keys=[origin_id], backref='routes_origin')
    destination = db.relationship('Terminal', foreign_keys=[destination_id], backref='routes_destination')

class RouteStop(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    route_id = db.Column(db.Integer, db.ForeignKey('route.id'), nullable=False)
    terminal_id = db.Column(db.Integer, db.ForeignKey('terminal.id'), nullable=False)
    stop_order = db.Column(db.Integer, nullable=False)
    distance_from_origin = db.Column(db.Float, default=0)
    scheduled_offset_min = db.Column(db.Integer, default=0)
    route = db.relationship('Route', backref='stops')
    terminal = db.relationship('Terminal', backref='route_stops')

class Bus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    registration = db.Column(db.String(80), unique=True, nullable=False)
    model = db.Column(db.String(120))
    seat_columns = db.Column(db.Integer, default=4)
    total_seats = db.Column(db.Integer, nullable=False)
    station_id = db.Column(db.Integer, db.ForeignKey('station.id'), nullable=True)
    station = db.relationship('Station', backref='buses')
    status = db.Column(db.String(20), default='active')  # active, maintenance, retired

class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    route_id = db.Column(db.Integer, db.ForeignKey('route.id'), nullable=False)
    bus_id = db.Column(db.Integer, db.ForeignKey('bus.id'), nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    station_id = db.Column(db.Integer, db.ForeignKey('station.id'), nullable=True)
    station = db.relationship('Station', backref='schedules')
    departure = db.Column(db.DateTime, nullable=False)
    arrival = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='scheduled')  # scheduled, delayed, cancelled, completed
    route = db.relationship('Route', backref='schedules')
    bus = db.relationship('Bus', backref='schedules')
    driver = db.relationship('User', backref='driven_schedules')

class Seat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey('schedule.id'), nullable=False)
    seat_number = db.Column(db.String(10), nullable=False)
    seat_type = db.Column(db.String(20), default='aisle')  # window, aisle, premium
    status = db.Column(db.String(20), default='available')  # available, booked
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=True)
    schedule = db.relationship('Schedule', backref='seats')
    booking = db.relationship('Booking', backref='seats')

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    schedule_id = db.Column(db.Integer, db.ForeignKey('schedule.id'), nullable=False)
    status = db.Column(db.String(20), default='confirmed')  # confirmed, cancelled
    total_amount = db.Column(db.Float, nullable=False)
    contact_email = db.Column(db.String(120))
    contact_phone = db.Column(db.String(50))
    booked_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='bookings')
    schedule = db.relationship('Schedule', backref='bookings')

class Passenger(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    seat_id = db.Column(db.Integer, db.ForeignKey('seat.id'), nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    luggage_kg = db.Column(db.Float, default=0)
    fare = db.Column(db.Float, nullable=False)
    checked_in = db.Column(db.Boolean, default=False)
    checked_in_at = db.Column(db.DateTime)
    booking = db.relationship('Booking', backref='passengers')
    seat = db.relationship('Seat', backref='passenger')

class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    passenger_id = db.Column(db.Integer, db.ForeignKey('passenger.id'), nullable=False)
    ticket_number = db.Column(db.String(80), unique=True, nullable=False)
    qr_path = db.Column(db.String(200))
    pdf_path = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    booking = db.relationship('Booking', backref='tickets')
    passenger = db.relationship('Passenger', backref='ticket', uselist=False)

class PricingRule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    route_id = db.Column(db.Integer, db.ForeignKey('route.id'), nullable=True)
    station_id = db.Column(db.Integer, db.ForeignKey('station.id'), nullable=True)
    station = db.relationship('Station', backref='pricing_rules')
    rule_type = db.Column(db.String(30), nullable=False)  # date_range, weekend, holiday, capacity, peak
    adjustment_type = db.Column(db.String(20), nullable=False)  # percent, flat
    value = db.Column(db.Float, nullable=False)
    threshold = db.Column(db.Float, default=0)  # for capacity
    start_hour = db.Column(db.Integer, nullable=True)  # for peak
    end_hour = db.Column(db.Integer, nullable=True)  # for peak
    active_from = db.Column(db.Date, nullable=False)
    active_to = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    route = db.relationship('Route', backref='pricing_rules')

class FleetMaintenance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bus_id = db.Column(db.Integer, db.ForeignKey('bus.id'), nullable=False)
    maintenance_type = db.Column(db.String(80))
    scheduled_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='scheduled')
    notes = db.Column(db.Text)
    bus = db.relationship('Bus', backref='maintenance')

class SupportTicket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='open')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='support_tickets')

class DriverEarning(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    schedule_id = db.Column(db.Integer, db.ForeignKey('schedule.id'), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    driver = db.relationship('User', backref='earnings')
    schedule = db.relationship('Schedule', backref='earnings')

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                flash('Access denied.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return wrapped
    return decorator

def user_station_id():
    """Return the station ID for non-global admin users, or None for global admins."""
    if current_user.is_authenticated and current_user.station_id and current_user.role != 'admin':
        return current_user.station_id
    return None

def filter_by_station(query):
    station_id = user_station_id()
    if station_id:
        return query.filter_by(station_id=station_id)
    return query

def random_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def generate_seats(schedule):
    bus = schedule.bus
    if not bus.total_seats or not bus.seat_columns:
        return
    rows = bus.total_seats // bus.seat_columns
    cols = bus.seat_columns
    letters = [chr(ord('A') + i) for i in range(cols)]
    for r in range(1, rows + 1):
        for c, letter in enumerate(letters):
            if r <= 2:
                seat_type = 'premium'
            elif c == 0 or c == cols - 1:
                seat_type = 'window'
            else:
                seat_type = 'aisle'
            number = f"{r}{letter}"
            s = Seat(schedule_id=schedule.id, seat_number=number, seat_type=seat_type, status='available')
            db.session.add(s)

def occupancy(schedule):
    total = Seat.query.filter_by(schedule_id=schedule.id).count()
    booked = Seat.query.filter_by(schedule_id=schedule.id, status='booked').count()
    return booked / total if total else 0

def is_rule_applicable(rule, schedule):
    dep = schedule.departure
    today = dep.date()
    if today < rule.active_from or today > rule.active_to or not rule.is_active:
        return False
    if rule.rule_type == 'date_range':
        return True
    if rule.rule_type == 'weekend':
        return today.weekday() >= 5
    if rule.rule_type == 'holiday':
        return True
    if rule.rule_type == 'capacity':
        return occupancy(schedule) >= rule.threshold
    if rule.rule_type == 'peak':
        if rule.start_hour is None or rule.end_hour is None:
            return False
        return rule.start_hour <= dep.hour < rule.end_hour
    return False

def calculate_fare(schedule, seat, luggage_kg=0):
    base = schedule.route.base_price
    seat_mult = SEAT_MULTIPLIERS.get(seat.seat_type, 1.0)
    subtotal = base * seat_mult
    luggage_price = max(0, luggage_kg - LUGGAGE_INCLUDED_KG) * LUGGAGE_PRICE_PER_KG
    subtotal += luggage_price
    rules = PricingRule.query.filter(or_(PricingRule.route_id == None, PricingRule.route_id == schedule.route_id)).all()
    pct = 0
    flat = 0
    for rule in rules:
        if is_rule_applicable(rule, schedule):
            if rule.adjustment_type == 'percent':
                pct += rule.value
            else:
                flat += rule.value
    subtotal = subtotal * (1 + pct / 100) + flat
    return round(max(0, subtotal), 2)

def make_ticket_number():
    return f"TKT{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{random.randint(1000,9999)}"

def generate_qr(ticket):
    import qrcode
    data = ticket.ticket_number
    filename = f"qr_{ticket.ticket_number}.png"
    path = os.path.join(app.config['QR_FOLDER'], filename)
    qrcode.make(data).save(path)
    return os.path.join('qrcodes', filename)

def generate_pdf(ticket):
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
    except Exception:
        return None
    filename = f"ticket_{ticket.ticket_number}.pdf"
    path = os.path.join(app.config['TICKET_FOLDER'], filename)
    c = canvas.Canvas(path, pagesize=letter)
    p = ticket.passenger
    b = ticket.booking
    s = b.schedule
    r = s.route
    width, height = letter
    c.setFont('Helvetica-Bold', 18)
    c.drawString(72, height - 72, 'Bus Ticket')
    c.setFont('Helvetica', 12)
    y = height - 110
    details = [
        f"Ticket Number: {ticket.ticket_number}",
        f"Passenger: {p.first_name} {p.last_name}",
        f"Route: {r.origin.name} -> {r.destination.name}",
        f"Departure: {s.departure.strftime('%Y-%m-%d %H:%M')}",
        f"Seat: {p.seat.seat_number} ({p.seat.seat_type})",
        f"Fare: ${p.fare:.2f}",
    ]
    for line in details:
        c.drawString(72, y, line)
        y -= 20
    qr_path = os.path.join(os.path.dirname(__file__), 'static', ticket.qr_path or '')
    if qr_path and os.path.exists(qr_path):
        c.drawImage(qr_path, 72, y - 160, width=2*inch, height=2*inch)
    c.save()
    return os.path.join('tickets', filename)

def build_manifest(schedule):
    passengers = Passenger.query.join(Seat).filter(Seat.schedule_id == schedule.id).all()
    return passengers

# -----------------------------------------------------------------------------
# Public routes
# -----------------------------------------------------------------------------

@app.context_processor
def inject_globals():
    return {
        'now': datetime.utcnow,
        'terminals': Terminal.query.filter_by(is_active=True).order_by(Terminal.city, Terminal.name).all()
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        first = request.form.get('first_name', '').strip()
        last = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        role = request.form.get('role', 'passenger')
        password = request.form.get('password', '')
        if not all([first, last, email, password]):
            flash('Please fill all required fields.', 'warning')
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return redirect(url_for('register'))
        user = User(
            first_name=first, last_name=last, email=email, phone=phone,
            role=role, password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()
        flash('Registration successful. Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash(f'Welcome, {user.full_name}!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/station/register', methods=['GET', 'POST'])
def station_register():
    if request.method == 'POST':
        station_name = request.form.get('station_name', '').strip()
        city = request.form.get('city', '').strip()
        country = request.form.get('country', '').strip()
        address = request.form.get('address', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('station_email', '').strip().lower()
        admin_first = request.form.get('admin_first_name', '').strip()
        admin_last = request.form.get('admin_last_name', '').strip()
        admin_email = request.form.get('admin_email', '').strip().lower()
        admin_phone = request.form.get('admin_phone', '').strip()
        admin_password = request.form.get('admin_password', '')
        if not all([station_name, city, admin_first, admin_last, admin_email, admin_password]):
            flash('Please fill all required fields.', 'warning')
            return redirect(url_for('station_register'))
        if User.query.filter_by(email=admin_email).first():
            flash('Admin email already registered.', 'danger')
            return redirect(url_for('station_register'))
        if email and Station.query.filter(func.lower(Station.email) == email).first():
            flash('Station email already registered.', 'danger')
            return redirect(url_for('station_register'))
        station = Station(name=station_name, city=city, country=country, address=address, phone=phone, email=email, is_approved=True, is_active=True)
        db.session.add(station)
        db.session.flush()
        admin = User(first_name=admin_first, last_name=admin_last, email=admin_email, phone=admin_phone,
                     role='station_admin', station_id=station.id,
                     password_hash=generate_password_hash(admin_password))
        db.session.add(admin)
        db.session.commit()
        flash('Station registered successfully. Log in as the station admin.', 'success')
        return redirect(url_for('login'))
    return render_template('station_register.html')

@app.route('/search')
def search():
    origin_id = request.args.get('origin_id', type=int)
    destination_id = request.args.get('destination_id', type=int)
    travel_date = request.args.get('travel_date')
    schedules = []
    if origin_id and destination_id and travel_date:
        try:
            qdate = datetime.strptime(travel_date, '%Y-%m-%d').date()
        except ValueError:
            qdate = None
        if qdate:
            start = datetime.combine(qdate, datetime.min.time())
            end = start + timedelta(days=1)
            schedules = Schedule.query.join(Route).join(Station).filter(
                Schedule.departure >= start,
                Schedule.departure < end,
                Station.is_active == True,
                Station.is_approved == True,
                or_(
                    and_(Route.origin_id == origin_id, Route.destination_id == destination_id),
                    and_(
                        Route.origin_id == origin_id,
                        Route.id.in_(
                            db.session.query(RouteStop.route_id).filter(RouteStop.terminal_id == destination_id)
                        )
                    ),
                    and_(
                        Route.destination_id == destination_id,
                        Route.id.in_(
                            db.session.query(RouteStop.route_id).filter(RouteStop.terminal_id == origin_id)
                        )
                    )
                )
            ).order_by(Schedule.departure).all()
    return render_template('search.html', schedules=schedules, origin_id=origin_id, destination_id=destination_id, travel_date=travel_date)

@app.route('/schedule/<int:schedule_id>')
def schedule_detail(schedule_id):
    schedule = Schedule.query.get_or_404(schedule_id)
    seats = Seat.query.filter_by(schedule_id=schedule_id).order_by(Seat.seat_number).all()
    rows = {}
    for s in seats:
        row = ''.join(filter(str.isdigit, s.seat_number))
        rows.setdefault(row, []).append(s)
    return render_template('schedule.html', schedule=schedule, seats=seats, rows=rows)

# -----------------------------------------------------------------------------
# Passenger booking
# -----------------------------------------------------------------------------

@app.route('/book/<int:schedule_id>', methods=['GET', 'POST'])
@login_required
def book(schedule_id):
    schedule = Schedule.query.get_or_404(schedule_id)
    if request.method == 'POST':
        seat_ids = request.form.getlist('seat_ids', type=int)
        if not seat_ids:
            flash('Please select at least one seat.', 'warning')
            return redirect(url_for('schedule_detail', schedule_id=schedule_id))
        return redirect(url_for('booking_form', schedule_id=schedule_id, seat_ids=','.join(map(str, seat_ids))))
    return redirect(url_for('schedule_detail', schedule_id=schedule_id))

@app.route('/booking/form/<int:schedule_id>')
@login_required
def booking_form(schedule_id):
    schedule = Schedule.query.get_or_404(schedule_id)
    seat_ids = [int(x) for x in request.args.get('seat_ids', '').split(',') if x]
    seats = Seat.query.filter(Seat.id.in_(seat_ids), Seat.schedule_id == schedule_id, Seat.status == 'available').all()
    if len(seats) != len(seat_ids):
        flash('Some seats are no longer available. Please select again.', 'warning')
        return redirect(url_for('schedule_detail', schedule_id=schedule_id))
    prices = {s.id: calculate_fare(schedule, s) for s in seats}
    return render_template('booking_form.html', schedule=schedule, seats=seats, prices=prices)

@app.route('/booking/create/<int:schedule_id>', methods=['POST'])
@login_required
def create_booking(schedule_id):
    schedule = Schedule.query.get_or_404(schedule_id)
    seat_ids = [int(x) for x in request.form.get('seat_ids', '').split(',') if x]
    seats = Seat.query.filter(Seat.id.in_(seat_ids), Seat.schedule_id == schedule_id, Seat.status == 'available').all()
    if len(seats) != len(seat_ids):
        flash('Some seats are no longer available.', 'warning')
        return redirect(url_for('schedule_detail', schedule_id=schedule_id))
    contact_email = request.form.get('contact_email', current_user.email).strip()
    contact_phone = request.form.get('contact_phone', current_user.phone or '').strip()
    booking = Booking(user_id=current_user.id, schedule_id=schedule_id, contact_email=contact_email, contact_phone=contact_phone, total_amount=0)
    db.session.add(booking)
    db.session.flush()
    total = 0
    for i, seat in enumerate(seats):
        prefix = f"passenger_{seat.id}_"
        first = request.form.get(prefix + 'first_name', '').strip()
        last = request.form.get(prefix + 'last_name', '').strip()
        luggage = request.form.get(prefix + 'luggage_kg', 0, type=float)
        if not first or not last:
            db.session.rollback()
            flash('Please enter all passenger names.', 'warning')
            return redirect(url_for('booking_form', schedule_id=schedule_id, seat_ids=','.join(map(str, seat_ids))))
        fare = calculate_fare(schedule, seat, luggage)
        passenger = Passenger(booking_id=booking.id, seat_id=seat.id, first_name=first, last_name=last, luggage_kg=luggage, fare=fare)
        db.session.add(passenger)
        db.session.flush()
        seat.status = 'booked'
        seat.booking_id = booking.id
        ticket_number = make_ticket_number()
        ticket = Ticket(booking_id=booking.id, passenger_id=passenger.id, ticket_number=ticket_number)
        db.session.add(ticket)
        db.session.flush()
        ticket.qr_path = generate_qr(ticket)
        ticket.pdf_path = generate_pdf(ticket)
        total += fare
    booking.total_amount = total
    db.session.commit()
    flash('Booking confirmed!', 'success')
    return redirect(url_for('booking_detail', booking_id=booking.id))

@app.route('/booking/<int:booking_id>')
@login_required
def booking_detail(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != current_user.id:
        if current_user.role == 'station_admin' and booking.schedule.station_id != current_user.station_id:
            abort(403)
        if current_user.role not in ('admin', 'operator', 'station_admin'):
            abort(403)
    return render_template('booking_detail.html', booking=booking)

@app.route('/bookings')
@login_required
def bookings_history():
    bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.booked_at.desc()).all()
    return render_template('bookings.html', bookings=bookings)

@app.route('/ticket/<int:ticket_id>/qr')
def ticket_qr(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    path = os.path.join(app.config['QR_FOLDER'], os.path.basename(ticket.qr_path or '')) if ticket.qr_path else None
    if path and os.path.exists(path):
        return send_file(path, mimetype='image/png')
    abort(404)

@app.route('/ticket/<int:ticket_id>/pdf')
def ticket_pdf(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    path = os.path.join(app.config['TICKET_FOLDER'], os.path.basename(ticket.pdf_path or '')) if ticket.pdf_path else None
    if path and os.path.exists(path):
        return send_file(path, mimetype='application/pdf')
    # regenerate
    ticket.pdf_path = generate_pdf(ticket)
    db.session.commit()
    path = os.path.join(app.config['TICKET_FOLDER'], os.path.basename(ticket.pdf_path))
    if os.path.exists(path):
        return send_file(path, mimetype='application/pdf')
    abort(404)

# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    if current_user.role == 'station_admin':
        return redirect(url_for('station_dashboard'))
    if current_user.role == 'operator':
        return redirect(url_for('operator_dashboard'))
    if current_user.role == 'driver':
        return redirect(url_for('driver_assignments'))
    return redirect(url_for('bookings_history'))

# -----------------------------------------------------------------------------
# Admin / operator
# -----------------------------------------------------------------------------

@app.route('/station/dashboard')
@role_required('station_admin')
def station_dashboard():
    station = current_user.station
    if not station:
        flash('No station linked to this account.', 'danger')
        return redirect(url_for('logout'))
    station_id = station.id
    total_bookings = Booking.query.join(Schedule).filter(Schedule.station_id == station_id).count()
    revenue = db.session.query(func.sum(Booking.total_amount)).join(Schedule).filter(Schedule.station_id == station_id).scalar() or 0
    upcoming = Schedule.query.filter_by(station_id=station_id).filter(Schedule.departure >= datetime.utcnow()).count()
    buses = Bus.query.filter_by(station_id=station_id).count()
    routes = Route.query.filter_by(station_id=station_id).count()
    return render_template('station_dashboard.html', station=station, total_bookings=total_bookings, revenue=revenue, upcoming=upcoming, buses=buses, routes=routes)

@app.route('/admin')
@role_required('admin', 'operator', 'station_admin')
def admin_dashboard():
    station_id = user_station_id()
    if station_id:
        total_bookings = Booking.query.join(Schedule).filter(Schedule.station_id == station_id).count()
        revenue = db.session.query(func.sum(Booking.total_amount)).join(Schedule).filter(Schedule.station_id == station_id).scalar() or 0
        upcoming = Schedule.query.filter_by(station_id=station_id).filter(Schedule.departure >= datetime.utcnow()).count()
        buses = Bus.query.filter_by(station_id=station_id).count()
        active_buses = Bus.query.filter_by(station_id=station_id, status='active').count()
    else:
        total_bookings = Booking.query.count()
        revenue = db.session.query(func.sum(Booking.total_amount)).scalar() or 0
        upcoming = Schedule.query.filter(Schedule.departure >= datetime.utcnow()).count()
        buses = Bus.query.count()
        active_buses = Bus.query.filter_by(status='active').count()
    tickets_open = SupportTicket.query.filter_by(status='open').count()
    return render_template('admin_dashboard.html', total_bookings=total_bookings, revenue=revenue, upcoming=upcoming, buses=buses, active_buses=active_buses, tickets_open=tickets_open)

@app.route('/admin/terminals', methods=['GET', 'POST'])
@role_required('admin', 'operator', 'station_admin')
def admin_terminals():
    station_id = user_station_id()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        city = request.form.get('city', '').strip()
        country = request.form.get('country', '').strip()
        code = request.form.get('code', '').strip().upper() or None
        if name and city:
            db.session.add(Terminal(name=name, city=city, country=country, code=code, station_id=station_id))
            db.session.commit()
            flash('Terminal added.', 'success')
        return redirect(url_for('admin_terminals'))
    terminals = filter_by_station(Terminal.query).order_by(Terminal.city, Terminal.name).all()
    return render_template('admin_terminals.html', terminals=terminals)

@app.route('/admin/routes', methods=['GET', 'POST'])
@role_required('admin', 'operator', 'station_admin')
def admin_routes():
    station_id = user_station_id()
    if request.method == 'POST':
        origin_id = request.form.get('origin_id', type=int)
        destination_id = request.form.get('destination_id', type=int)
        name = request.form.get('name', '').strip()
        distance = request.form.get('distance_km', 0, type=float)
        duration = request.form.get('duration_min', 0, type=int)
        base = request.form.get('base_price', 0, type=float)
        if origin_id and destination_id and base:
            db.session.add(Route(origin_id=origin_id, destination_id=destination_id, name=name, distance_km=distance, duration_min=duration, base_price=base, station_id=station_id))
            db.session.commit()
            flash('Route added.', 'success')
        return redirect(url_for('admin_routes'))
    routes = filter_by_station(Route.query).all()
    terminals = filter_by_station(Terminal.query).order_by(Terminal.city, Terminal.name).all()
    return render_template('admin_routes.html', routes=routes, terminals=terminals)

@app.route('/admin/route/<int:route_id>/stops', methods=['GET', 'POST'])
@role_required('admin', 'operator', 'station_admin')
def admin_route_stops(route_id):
    route = Route.query.get_or_404(route_id)
    if user_station_id() and route.station_id != user_station_id():
        abort(403)
    if request.method == 'POST':
        terminal_id = request.form.get('terminal_id', type=int)
        order = request.form.get('stop_order', 1, type=int)
        offset = request.form.get('scheduled_offset_min', 0, type=int)
        if terminal_id:
            db.session.add(RouteStop(route_id=route_id, terminal_id=terminal_id, stop_order=order, scheduled_offset_min=offset))
            db.session.commit()
        return redirect(url_for('admin_route_stops', route_id=route_id))
    stops = RouteStop.query.filter_by(route_id=route_id).order_by(RouteStop.stop_order).all()
    terminals = filter_by_station(Terminal.query).order_by(Terminal.city, Terminal.name).all()
    return render_template('admin_route_stops.html', route=route, stops=stops, terminals=terminals)

@app.route('/admin/buses', methods=['GET', 'POST'])
@role_required('admin', 'operator', 'station_admin')
def admin_buses():
    station_id = user_station_id()
    if request.method == 'POST':
        reg = request.form.get('registration', '').strip().upper()
        model = request.form.get('model', '').strip()
        cols = request.form.get('seat_columns', 4, type=int)
        seats = request.form.get('total_seats', cols * 10, type=int)
        if reg and seats:
            db.session.add(Bus(registration=reg, model=model, seat_columns=cols, total_seats=seats, station_id=station_id))
            db.session.commit()
            flash('Bus added.', 'success')
        return redirect(url_for('admin_buses'))
    buses = filter_by_station(Bus.query).order_by(Bus.registration).all()
    return render_template('admin_buses.html', buses=buses)

@app.route('/admin/fleet')
@role_required('admin', 'operator', 'station_admin')
def admin_fleet():
    buses = filter_by_station(Bus.query).order_by(Bus.registration).all()
    return render_template('admin_fleet.html', buses=buses)

@app.route('/admin/fleet/maintenance', methods=['POST'])
@role_required('admin', 'operator', 'station_admin')
def admin_fleet_maintenance():
    bus_id = request.form.get('bus_id', type=int)
    mtype = request.form.get('maintenance_type', '').strip()
    mdate = request.form.get('scheduled_date')
    notes = request.form.get('notes', '')
    if bus_id and mtype and mdate:
        try:
            bus = filter_by_station(Bus.query).filter_by(id=bus_id).first()
            if bus:
                d = datetime.strptime(mdate, '%Y-%m-%d').date()
                db.session.add(FleetMaintenance(bus_id=bus.id, maintenance_type=mtype, scheduled_date=d, notes=notes))
                db.session.commit()
                flash('Maintenance scheduled.', 'success')
            else:
                flash('Bus not found.', 'warning')
        except ValueError:
            flash('Invalid date.', 'warning')
    return redirect(url_for('admin_fleet'))

@app.route('/admin/schedules', methods=['GET', 'POST'])
@role_required('admin', 'operator', 'station_admin')
def admin_schedules():
    station_id = user_station_id()
    if request.method == 'POST':
        route_id = request.form.get('route_id', type=int)
        bus_id = request.form.get('bus_id', type=int)
        driver_id = request.form.get('driver_id', type=int) or None
        dep_date = request.form.get('departure_date')
        dep_time = request.form.get('departure_time')
        recurrence = request.form.get('recurrence', '')
        occurrences = request.form.get('occurrences', 1, type=int)
        if route_id and bus_id and dep_date and dep_time:
            try:
                route = filter_by_station(Route.query).filter_by(id=route_id).first()
                bus = filter_by_station(Bus.query).filter_by(id=bus_id).first()
                driver = User.query.filter_by(id=driver_id, role='driver').first() if driver_id else None
                if not route or not bus:
                    flash('Invalid route or bus for this station.', 'danger')
                    return redirect(url_for('admin_schedules'))
                base_dep = datetime.strptime(f"{dep_date} {dep_time}", '%Y-%m-%d %H:%M')
                for i in range(occurrences):
                    dep = base_dep + timedelta(days=i)
                    if recurrence == 'weekdays' and dep.weekday() >= 5:
                        continue
                    if recurrence == 'weekends' and dep.weekday() < 5:
                        continue
                    if recurrence == 'weekly':
                        dep = base_dep + timedelta(weeks=i)
                    arr = dep + timedelta(minutes=route.duration_min or 0)
                    sched = Schedule(route_id=route.id, bus_id=bus.id, driver_id=driver.id if driver else None, station_id=station_id, departure=dep, arrival=arr)
                    db.session.add(sched)
                    db.session.flush()
                    generate_seats(sched)
                db.session.commit()
                flash('Schedule(s) added.', 'success')
            except ValueError as e:
                flash(f'Error: {e}', 'danger')
        return redirect(url_for('admin_schedules'))
    schedules = filter_by_station(Schedule.query).order_by(Schedule.departure.desc()).all()
    routes = filter_by_station(Route.query).all()
    buses = filter_by_station(Bus.query).filter_by(status='active').all()
    if station_id:
        drivers = User.query.filter_by(role='driver', station_id=station_id).all()
    else:
        drivers = User.query.filter_by(role='driver').all()
    return render_template('admin_schedules.html', schedules=schedules, routes=routes, buses=buses, drivers=drivers)

@app.route('/admin/pricing', methods=['GET', 'POST'])
@role_required('admin', 'operator', 'station_admin')
def admin_pricing():
    station_id = user_station_id()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        route_id = request.form.get('route_id', type=int) or None
        if route_id:
            route = filter_by_station(Route.query).filter_by(id=route_id).first()
            if not route:
                flash('Invalid route.', 'danger')
                return redirect(url_for('admin_pricing'))
        rule_type = request.form.get('rule_type')
        adj_type = request.form.get('adjustment_type')
        value = request.form.get('value', 0, type=float)
        threshold = request.form.get('threshold', 0, type=float)
        start_hour = request.form.get('start_hour', None, type=int)
        end_hour = request.form.get('end_hour', None, type=int)
        active_from = request.form.get('active_from')
        active_to = request.form.get('active_to')
        if name and rule_type and adj_type and active_from and active_to:
            try:
                af = datetime.strptime(active_from, '%Y-%m-%d').date()
                at = datetime.strptime(active_to, '%Y-%m-%d').date()
                db.session.add(PricingRule(name=name, route_id=route_id, station_id=station_id, rule_type=rule_type, adjustment_type=adj_type, value=value, threshold=threshold, start_hour=start_hour, end_hour=end_hour, active_from=af, active_to=at))
                db.session.commit()
                flash('Pricing rule added.', 'success')
            except ValueError:
                flash('Invalid date.', 'warning')
        return redirect(url_for('admin_pricing'))
    rules = filter_by_station(PricingRule.query).order_by(PricingRule.active_from.desc()).all()
    routes = filter_by_station(Route.query).all()
    return render_template('admin_pricing.html', rules=rules, routes=routes)

@app.route('/admin/analytics')
@role_required('admin', 'operator', 'station_admin')
def admin_analytics():
    station_id = user_station_id()
    base_query = Booking.query.join(Schedule)
    if station_id:
        base_query = base_query.filter(Schedule.station_id == station_id)
    total_trips = base_query.filter(Booking.status == 'confirmed').count()
    revenue_query = db.session.query(func.sum(Booking.total_amount)).select_from(Booking).join(Schedule).filter(Booking.status == 'confirmed')
    peak_query = db.session.query(func.strftime('%H', Booking.booked_at).label('hour'), func.count(Booking.id)).select_from(Booking).join(Schedule).filter(Booking.status == 'confirmed')
    daily_query = db.session.query(func.strftime('%Y-%m-%d', Booking.booked_at).label('day'), func.sum(Booking.total_amount)).select_from(Booking).join(Schedule).filter(Booking.status == 'confirmed')
    if station_id:
        revenue_query = revenue_query.filter(Schedule.station_id == station_id)
        peak_query = peak_query.filter(Schedule.station_id == station_id)
        daily_query = daily_query.filter(Schedule.station_id == station_id)
    total_revenue = revenue_query.scalar() or 0
    peak_hours = peak_query.group_by('hour').order_by('hour').all()
    daily_revenue = daily_query.group_by('day').order_by('day').all()
    return render_template('admin_analytics.html', total_trips=total_trips, total_revenue=total_revenue, peak_hours=peak_hours, daily_revenue=daily_revenue)

@app.route('/admin/support')
@role_required('admin')
def admin_support():
    tickets = SupportTicket.query.order_by(SupportTicket.created_at.desc()).all()
    return render_template('admin_support.html', tickets=tickets)

@app.route('/admin/support/<int:ticket_id>/resolve', methods=['POST'])
@role_required('admin')
def admin_support_resolve(ticket_id):
    t = SupportTicket.query.get_or_404(ticket_id)
    t.status = 'resolved'
    db.session.commit()
    flash('Ticket resolved.', 'success')
    return redirect(url_for('admin_support'))

# -----------------------------------------------------------------------------
# Operator dashboard (alias)
# -----------------------------------------------------------------------------

@app.route('/operator')
@role_required('operator')
def operator_dashboard():
    return redirect(url_for('admin_dashboard'))

# -----------------------------------------------------------------------------
# Driver routes
# -----------------------------------------------------------------------------

@app.route('/driver/assignments')
@role_required('driver')
def driver_assignments():
    assignments = Schedule.query.filter_by(driver_id=current_user.id).filter(Schedule.departure >= datetime.utcnow()).order_by(Schedule.departure).all()
    return render_template('driver_assignments.html', assignments=assignments)

@app.route('/driver/assignment/<int:schedule_id>')
@role_required('driver')
def driver_assignment(schedule_id):
    schedule = Schedule.query.get_or_404(schedule_id)
    passengers = build_manifest(schedule)
    return render_template('driver_manifest.html', schedule=schedule, passengers=passengers)

@app.route('/driver/scan/<int:schedule_id>')
@role_required('driver')
def driver_scan(schedule_id):
    schedule = Schedule.query.get_or_404(schedule_id)
    return render_template('driver_scan.html', schedule=schedule)

@app.route('/driver/earnings')
@role_required('driver')
def driver_earnings():
    earnings = DriverEarning.query.filter_by(driver_id=current_user.id).order_by(DriverEarning.period_start.desc()).all()
    daily = db.session.query(func.sum(DriverEarning.amount)).filter(DriverEarning.driver_id == current_user.id, DriverEarning.period_start == date.today()).scalar() or 0
    week_start = date.today() - timedelta(days=date.today().weekday())
    weekly = db.session.query(func.sum(DriverEarning.amount)).filter(DriverEarning.driver_id == current_user.id, DriverEarning.period_start >= week_start).scalar() or 0
    month_start = date.today().replace(day=1)
    monthly = db.session.query(func.sum(DriverEarning.amount)).filter(DriverEarning.driver_id == current_user.id, DriverEarning.period_start >= month_start).scalar() or 0
    return render_template('driver_earnings.html', earnings=earnings, daily=daily, weekly=weekly, monthly=monthly)

# -----------------------------------------------------------------------------
# API / scanning
# -----------------------------------------------------------------------------

@app.route('/api/ticket/<ticket_number>')
def api_ticket(ticket_number):
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first()
    if not ticket:
        return jsonify({'ok': False, 'message': 'Ticket not found'}), 404
    p = ticket.passenger
    return jsonify({
        'ok': True,
        'ticket_number': ticket.ticket_number,
        'passenger': f"{p.first_name} {p.last_name}",
        'seat': p.seat.seat_number,
        'route': f"{ticket.booking.schedule.route.origin.name} -> {ticket.booking.schedule.route.destination.name}",
        'departure': ticket.booking.schedule.departure.isoformat(),
        'checked_in': p.checked_in
    })

@app.route('/api/scan', methods=['POST'])
def api_scan():
    ticket_number = request.form.get('ticket_number', '').strip()
    schedule_id = request.form.get('schedule_id', type=int)
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first()
    if not ticket:
        return jsonify({'ok': False, 'message': 'Ticket not found'}), 404
    p = ticket.passenger
    if schedule_id and ticket.booking.schedule_id != schedule_id:
        return jsonify({'ok': False, 'message': 'Ticket not for this schedule'}), 400
    if p.checked_in:
        return jsonify({'ok': True, 'message': 'Already checked in', 'passenger': p.full_name if hasattr(p, 'full_name') else f"{p.first_name} {p.last_name}", 'checked_in': True})
    p.checked_in = True
    p.checked_in_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True, 'message': 'Checked in', 'passenger': f"{p.first_name} {p.last_name}", 'checked_in': True})

# -----------------------------------------------------------------------------
# Seed data
# -----------------------------------------------------------------------------

def seed_demo_data():
    if User.query.first():
        return
    station = Station(name='Central Bus Services', city='Kigali', country='Rwanda', address='Kigali City Center', phone='', email='info@centralbus.example', is_approved=True, is_active=True)
    db.session.add(station)
    db.session.flush()

    admin = User(first_name='Admin', last_name='User', email='admin@bus.com', phone='', role='admin', station_id=station.id, password_hash=generate_password_hash('admin123'))
    driver = User(first_name='John', last_name='Doe', email='driver@bus.com', phone='1234567890', role='driver', station_id=station.id, password_hash=generate_password_hash('driver123'), license_number='DL123456', vehicle_info='Bus A', background_status='approved')
    passenger = User(first_name='Jane', last_name='Doe', email='passenger@bus.com', phone='0987654321', role='passenger', password_hash=generate_password_hash('pass123'))
    db.session.add_all([admin, driver, passenger])
    db.session.commit()

    t1 = Terminal(name='Central Station', city='Kigali', code='KGL', station_id=station.id)
    t2 = Terminal(name='Northern Terminal', city='Musanze', code='MSZ', station_id=station.id)
    t3 = Terminal(name='Eastern Stop', city='Rwamagana', code='RWM', station_id=station.id)
    db.session.add_all([t1, t2, t3])
    db.session.commit()

    route = Route(origin_id=t1.id, destination_id=t2.id, name='Kigali - Musanze Express', distance_km=90, duration_min=120, base_price=15.0, station_id=station.id)
    db.session.add(route)
    db.session.commit()
    db.session.add(RouteStop(route_id=route.id, terminal_id=t3.id, stop_order=1, scheduled_offset_min=45, distance_from_origin=40))
    db.session.commit()

    bus = Bus(registration='RAE123A', model='Yutong 45', seat_columns=4, total_seats=40, status='active', station_id=station.id)
    db.session.add(bus)
    db.session.commit()

    for day in range(7):
        dep = datetime.now() + timedelta(days=day)
        dep = dep.replace(hour=8, minute=0, second=0, microsecond=0)
        arr = dep + timedelta(minutes=route.duration_min)
        sched = Schedule(route_id=route.id, bus_id=bus.id, driver_id=driver.id, station_id=station.id, departure=dep, arrival=arr)
        db.session.add(sched)
        db.session.flush()
        generate_seats(sched)
    db.session.commit()

    # seed a pricing rule
    db.session.add(PricingRule(name='Weekend Surcharge', route_id=route.id, station_id=station.id, rule_type='weekend', adjustment_type='percent', value=10, active_from=date.today(), active_to=date.today()+timedelta(days=365)))
    db.session.commit()

# -----------------------------------------------------------------------------
# Init
# -----------------------------------------------------------------------------

with app.app_context():
    db.create_all()
    seed_demo_data()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
