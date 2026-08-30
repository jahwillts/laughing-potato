import os
from datetime import datetime, date, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///school.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class School(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, default="My School")
    motto = db.Column(db.String(200), default="Excellence in Education")
    logo = db.Column(db.String(200))
    address = db.Column(db.String(250))
    phone = db.Column(db.String(50))

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(50))
    role = db.Column(db.String(20), nullable=False)  # admin, teacher, student, parent
    password_hash = db.Column(db.String(256), nullable=False)
    photo = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    children = db.relationship('User', backref=db.backref('parent', remote_side=[id]))

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

class Class(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    section = db.Column(db.String(20))
    students = db.relationship('User', backref='class_', foreign_keys='User.class_id')

class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    code = db.Column(db.String(20))

class ClassSubject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    class_ = db.relationship('Class', backref='class_subjects')
    subject = db.relationship('Subject', backref='class_subjects')
    teacher = db.relationship('User', backref='assigned_subjects')

class Timetable(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    day = db.Column(db.String(10), nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    class_ = db.relationship('Class', backref='timetable_entries')
    subject = db.relationship('Subject', backref='timetable_entries')
    teacher = db.relationship('User', backref='timetable_entries')

class Mark(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(30), nullable=False)  # homework, assignment, exam
    title = db.Column(db.String(120))
    score = db.Column(db.Float, nullable=False)
    total = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, default=date.today)
    student = db.relationship('User', foreign_keys=[student_id], backref='marks_received')
    subject = db.relationship('Subject', backref='marks')
    teacher = db.relationship('User', foreign_keys=[teacher_id], backref='marks_given')

class Exam(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    duration = db.Column(db.Integer, default=30)  # minutes
    is_published = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    questions = db.relationship('Question', backref='exam', lazy=True, cascade='all, delete-orphan')
    subject = db.relationship('Subject', backref='exams')
    class_ = db.relationship('Class', backref='exams')
    teacher = db.relationship('User', backref='exams_created')

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(255), nullable=False)
    option_b = db.Column(db.String(255), nullable=False)
    option_c = db.Column(db.String(255), nullable=False)
    option_d = db.Column(db.String(255), nullable=False)
    correct_option = db.Column(db.String(1), nullable=False)  # A, B, C, D

class StudentAnswer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    selected_option = db.Column(db.String(1))
    exam = db.relationship('Exam', backref='student_answers')
    question = db.relationship('Question', backref='student_answers')
    student = db.relationship('User', backref='student_answers')

class ExamAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    score = db.Column(db.Float, default=0)
    total = db.Column(db.Float, default=0)
    completed_at = db.Column(db.DateTime)
    exam = db.relationship('Exam', backref='attempts')
    student = db.relationship('User', backref='exam_attempts')

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    method = db.Column(db.String(30), nullable=False)  # mobile_money, bank_transfer
    transaction_ref = db.Column(db.String(100), unique=True)
    status = db.Column(db.String(20), default='pending')  # pending, success, failed
    date = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='payments')

class Renewal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    school = db.relationship('School', backref='renewals')

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)
    sender = db.relationship('User', foreign_keys=[sender_id], backref='messages_sent')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='messages_received')

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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

def get_school():
    school = School.query.first()
    if not school:
        school = School(name="My School")
        db.session.add(school)
        db.session.commit()
    return school

def save_photo(file):
    if file and allowed_file(file.filename):
        filename = secure_filename(f"{datetime.utcnow().timestamp()}_{file.filename}")
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(path)
        return f"uploads/{filename}"
    return None

def can_chat(sender, receiver):
    """Enforce role-based chat rules."""
    if sender.id == receiver.id:
        return False
    if sender.role == 'admin':
        return receiver.role == 'teacher'
    if sender.role == 'teacher':
        return receiver.role in ('admin', 'student', 'parent')
    if sender.role == 'student':
        return receiver.role in ('student', 'teacher')
    if sender.role == 'parent':
        return receiver.role == 'teacher'
    return False

def aggregate_student_marks(student_id):
    from sqlalchemy import func
    rows = db.session.query(
        Subject.id, Subject.name,
        func.avg(Mark.score / Mark.total * 100).label('avg_pct'),
        func.count(Mark.id).label('count')
    ).join(Mark, Mark.subject_id == Subject.id)\
     .filter(Mark.student_id == student_id)\
     .group_by(Subject.id, Subject.name).all()
    result = []
    total = 0
    for r in rows:
        pct = round(r.avg_pct or 0, 2)
        total += pct
        result.append({'subject': r.name, 'average': pct, 'count': r.count})
    overall = round(total / len(result), 2) if result else 0
    return result, overall

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.context_processor
def inject_school():
    return dict(school=get_school())

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    classes = Class.query.all()
    if request.method == 'POST':
        first = request.form.get('first_name', '').strip()
        last = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        role = request.form.get('role')
        password = request.form.get('password')
        class_id = request.form.get('class_id') or None
        parent_email = request.form.get('parent_email', '').strip().lower()
        admin_code = request.form.get('admin_code', '').strip()

        if not all([first, last, email, role, password]):
            flash('Please fill all required fields.', 'warning')
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return redirect(url_for('register'))
        if role == 'admin' and admin_code != os.environ.get('ADMIN_CODE', 'admin123'):
            flash('Invalid admin registration code.', 'danger')
            return redirect(url_for('register'))

        parent = None
        if parent_email:
            parent = User.query.filter_by(email=parent_email, role='parent').first()
            if not parent:
                flash('Parent email not found.', 'warning')

        user = User(
            first_name=first, last_name=last, email=email, phone=phone,
            role=role, password_hash=generate_password_hash(password),
            class_id=class_id, parent_id=parent.id if parent else None
        )
        if 'photo' in request.files:
            user.photo = save_photo(request.files['photo'])
        db.session.add(user)
        db.session.commit()
        flash('Registration successful. Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', classes=classes)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')
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
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        counts = {
            'students': User.query.filter_by(role='student').count(),
            'teachers': User.query.filter_by(role='teacher').count(),
            'parents': User.query.filter_by(role='parent').count(),
            'classes': Class.query.count(),
            'subjects': Subject.query.count(),
            'payments': Payment.query.count(),
        }
        return render_template('dashboard.html', counts=counts)
    if current_user.role == 'teacher':
        classes = Class.query.all()
        subjects = Subject.query.join(ClassSubject, ClassSubject.subject_id == Subject.id)\
            .filter(ClassSubject.teacher_id == current_user.id).all()
        return render_template('dashboard.html', classes=classes, subjects=subjects)
    if current_user.role == 'student':
        courses = ClassSubject.query.filter_by(class_id=current_user.class_id).all()
        timetable = Timetable.query.filter_by(class_id=current_user.class_id).all()
        marks, overall = aggregate_student_marks(current_user.id)
        attempts = ExamAttempt.query.filter_by(student_id=current_user.id).all()
        return render_template('dashboard.html', courses=courses, timetable=timetable,
                               marks=marks, overall=overall, attempts=attempts)
    if current_user.role == 'parent':
        children = User.query.filter_by(parent_id=current_user.id, role='student').all()
        data = []
        for child in children:
            marks, overall = aggregate_student_marks(child.id)
            attempts = ExamAttempt.query.filter_by(student_id=child.id).all()
            data.append({'child': child, 'marks': marks, 'overall': overall, 'attempts': attempts})
        return render_template('dashboard.html', children_data=data)
    return redirect(url_for('index'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.first_name = request.form.get('first_name', current_user.first_name)
        current_user.last_name = request.form.get('last_name', current_user.last_name)
        current_user.phone = request.form.get('phone', current_user.phone)
        if 'photo' in request.files:
            current_user.photo = save_photo(request.files['photo']) or current_user.photo
        if request.form.get('password'):
            current_user.password_hash = generate_password_hash(request.form.get('password'))
        db.session.commit()
        flash('Profile updated.', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html')

# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

@app.route('/school/settings', methods=['GET', 'POST'])
@role_required('admin')
def school_settings():
    school = get_school()
    if request.method == 'POST':
        school.name = request.form.get('name', school.name)
        school.motto = request.form.get('motto', school.motto)
        school.address = request.form.get('address', school.address)
        school.phone = request.form.get('phone', school.phone)
        if 'logo' in request.files:
            school.logo = save_photo(request.files['logo']) or school.logo
        db.session.commit()
        flash('School settings updated.', 'success')
        return redirect(url_for('school_settings'))
    return render_template('school_settings.html', school=school)

@app.route('/classes', methods=['GET', 'POST'])
@login_required
def classes_view():
    if current_user.role not in ('admin', 'teacher'):
        abort(403)
    if request.method == 'POST' and current_user.role == 'admin':
        name = request.form.get('name', '').strip()
        section = request.form.get('section', '').strip()
        if name:
            db.session.add(Class(name=name, section=section))
            db.session.commit()
            flash('Class added.', 'success')
        return redirect(url_for('classes_view'))
    classes = Class.query.all()
    return render_template('classes.html', classes=classes)

@app.route('/subjects', methods=['GET', 'POST'])
@role_required('admin')
def subjects_view():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        code = request.form.get('code', '').strip()
        if name:
            db.session.add(Subject(name=name, code=code))
            db.session.commit()
            flash('Subject added.', 'success')
        return redirect(url_for('subjects_view'))
    subjects = Subject.query.all()
    return render_template('subjects.html', subjects=subjects)

@app.route('/class-subjects', methods=['GET', 'POST'])
@role_required('admin')
def class_subjects():
    if request.method == 'POST':
        class_id = request.form.get('class_id')
        subject_id = request.form.get('subject_id')
        teacher_id = request.form.get('teacher_id')
        existing = ClassSubject.query.filter_by(class_id=class_id, subject_id=subject_id).first()
        if not existing:
            db.session.add(ClassSubject(class_id=class_id, subject_id=subject_id, teacher_id=teacher_id))
            db.session.commit()
            flash('Subject assigned to class.', 'success')
        return redirect(url_for('class_subjects'))
    data = ClassSubject.query.all()
    classes = Class.query.all()
    subjects = Subject.query.all()
    teachers = User.query.filter_by(role='teacher').all()
    return render_template('class_subjects.html', data=data, classes=classes, subjects=subjects, teachers=teachers)

@app.route('/users')
@role_required('admin')
def users_view():
    role = request.args.get('role')
    q = User.query
    if role:
        q = q.filter_by(role=role)
    users = q.order_by(User.role, User.last_name).all()
    return render_template('users.html', users=users)

@app.route('/timetable', methods=['GET', 'POST'])
@login_required
def timetable_view():
    if current_user.role not in ('admin', 'teacher'):
        abort(403)
    if request.method == 'POST':
        class_id = request.form.get('class_id')
        subject_id = request.form.get('subject_id')
        teacher_id = request.form.get('teacher_id')
        day = request.form.get('day')
        start = datetime.strptime(request.form.get('start_time'), '%H:%M').time()
        end = datetime.strptime(request.form.get('end_time'), '%H:%M').time()
        db.session.add(Timetable(class_id=class_id, subject_id=subject_id, teacher_id=teacher_id,
                                 day=day, start_time=start, end_time=end))
        db.session.commit()
        flash('Timetable entry added.', 'success')
        return redirect(url_for('timetable_view'))
    entries = Timetable.query.order_by(Timetable.day, Timetable.start_time).all()
    classes = Class.query.all()
    subjects = Subject.query.all()
    teachers = User.query.filter_by(role='teacher').all()
    return render_template('timetable.html', entries=entries, classes=classes, subjects=subjects, teachers=teachers)

# ---------------------------------------------------------------------------
# Marks
# ---------------------------------------------------------------------------

@app.route('/marks', methods=['GET', 'POST'])
@login_required
def marks_view():
    if current_user.role == 'teacher':
        if request.method == 'POST':
            student_id = request.form.get('student_id')
            subject_id = request.form.get('subject_id')
            type_ = request.form.get('type')
            title = request.form.get('title', '').strip()
            score = float(request.form.get('score', 0))
            total = float(request.form.get('total', 100))
            db.session.add(Mark(student_id=student_id, subject_id=subject_id, teacher_id=current_user.id,
                                type=type_, title=title, score=score, total=total))
            db.session.commit()
            flash('Mark recorded.', 'success')
            return redirect(url_for('marks_view'))
        students = User.query.filter_by(role='student').all()
        subjects = Subject.query.join(ClassSubject, ClassSubject.subject_id == Subject.id)\
            .filter(ClassSubject.teacher_id == current_user.id).all()
        marks = Mark.query.filter_by(teacher_id=current_user.id).order_by(Mark.date.desc()).all()
        return render_template('marks.html', students=students, subjects=subjects, marks=marks)
    if current_user.role in ('student', 'parent'):
        if current_user.role == 'student':
            student_id = current_user.id
        else:
            student_id = request.args.get('student_id', type=int)
            if not student_id:
                children = User.query.filter_by(parent_id=current_user.id, role='student').all()
                return render_template('marks.html', children=children, report=False)
        marks, overall = aggregate_student_marks(student_id)
        return render_template('marks.html', marks=marks, overall=overall, report=True)
    abort(403)

# ---------------------------------------------------------------------------
# Exams
# ---------------------------------------------------------------------------

@app.route('/exams', methods=['GET', 'POST'])
@login_required
def exams_view():
    if current_user.role == 'teacher':
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            subject_id = request.form.get('subject_id')
            class_id = request.form.get('class_id')
            duration = request.form.get('duration', 30, type=int) or 30
            exam = Exam(title=title, subject_id=subject_id, class_id=class_id,
                        teacher_id=current_user.id, duration=duration)
            db.session.add(exam)
            db.session.commit()
            return redirect(url_for('exam_questions', exam_id=exam.id))
        exams = Exam.query.filter_by(teacher_id=current_user.id).all()
        subjects = Subject.query.join(ClassSubject, ClassSubject.subject_id == Subject.id)\
            .filter(ClassSubject.teacher_id == current_user.id).all()
        classes = Class.query.all()
        return render_template('exams.html', exams=exams, subjects=subjects, classes=classes)
    if current_user.role == 'student':
        exams = Exam.query.filter_by(class_id=current_user.class_id, is_published=True).all()
        return render_template('exams.html', exams=exams, mode='student')
    if current_user.role == 'parent':
        children = User.query.filter_by(parent_id=current_user.id, role='student').all()
        return render_template('exams.html', children=children, mode='parent')
    if current_user.role == 'admin':
        exams = Exam.query.all()
        return render_template('exams.html', exams=exams, mode='admin')
    abort(403)

@app.route('/exams/<int:exam_id>/questions', methods=['GET', 'POST'])
@role_required('teacher')
def exam_questions(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    if request.method == 'POST':
        text = request.form.get('text', '').strip()
        a = request.form.get('option_a', '').strip()
        b = request.form.get('option_b', '').strip()
        c = request.form.get('option_c', '').strip()
        d = request.form.get('option_d', '').strip()
        correct = request.form.get('correct_option')
        db.session.add(Question(exam_id=exam.id, text=text, option_a=a, option_b=b, option_c=c, option_d=d,
                                correct_option=correct))
        db.session.commit()
        flash('Question added.', 'success')
        return redirect(url_for('exam_questions', exam_id=exam.id))
    return render_template('exam_questions.html', exam=exam)

@app.route('/exams/<int:exam_id>/publish')
@role_required('teacher')
def publish_exam(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    exam.is_published = True
    db.session.commit()
    flash('Exam published.', 'success')
    return redirect(url_for('exams_view'))

@app.route('/exams/<int:exam_id>/take', methods=['GET', 'POST'])
@role_required('student')
def take_exam(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    if exam.class_id != current_user.class_id or not exam.is_published:
        abort(403)
    attempt = ExamAttempt.query.filter_by(exam_id=exam.id, student_id=current_user.id).first()
    if attempt:
        return redirect(url_for('exam_result', exam_id=exam.id))
    if request.method == 'POST':
        correct = 0
        total = len(exam.questions)
        for q in exam.questions:
            selected = request.form.get(f'q_{q.id}')
            db.session.add(StudentAnswer(exam_id=exam.id, question_id=q.id,
                                         student_id=current_user.id, selected_option=selected))
            if selected == q.correct_option:
                correct += 1
        score = correct
        db.session.add(ExamAttempt(exam_id=exam.id, student_id=current_user.id,
                                   score=score, total=total, completed_at=datetime.utcnow()))
        db.session.commit()
        flash('Exam submitted.', 'success')
        return redirect(url_for('exam_result', exam_id=exam.id))
    return render_template('take_exam.html', exam=exam)

@app.route('/exams/<int:exam_id>/result')
@login_required
def exam_result(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    student_id = request.args.get('student_id', type=int) or current_user.id
    if current_user.role == 'parent':
        child = User.query.filter_by(id=student_id, parent_id=current_user.id, role='student').first()
        if not child:
            abort(403)
    if current_user.role == 'student' and student_id != current_user.id:
        abort(403)
    if current_user.role == 'teacher' and exam.teacher_id != current_user.id:
        abort(403)
    attempt = ExamAttempt.query.filter_by(exam_id=exam.id, student_id=student_id).first_or_404()
    answers = StudentAnswer.query.filter_by(exam_id=exam.id, student_id=student_id).all()
    return render_template('exam_result.html', exam=exam, attempt=attempt, answers=answers)

@app.route('/exams/<int:exam_id>/report')
@login_required
def exam_report(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    if current_user.role not in ('admin', 'teacher') and not (current_user.role == 'parent' and request.args.get('student_id')):
        abort(403)
    attempts = ExamAttempt.query.filter_by(exam_id=exam.id).all()
    return render_template('exam_report.html', exam=exam, attempts=attempts)

# ---------------------------------------------------------------------------
# Payments and renewals
# ---------------------------------------------------------------------------

@app.route('/payments', methods=['GET', 'POST'])
@login_required
def payments_view():
    if current_user.role == 'admin':
        payments = Payment.query.order_by(Payment.date.desc()).all()
        if request.method == 'POST':
            p = Payment.query.get_or_404(request.form.get('payment_id'))
            p.status = request.form.get('status')
            db.session.commit()
            flash('Payment status updated.', 'success')
            return redirect(url_for('payments_view'))
        return render_template('payments.html', payments=payments, admin=True)
    if request.method == 'POST':
        amount = float(request.form.get('amount', 0))
        method = request.form.get('method')
        ref = request.form.get('transaction_ref', '').strip()
        if amount <= 0 or not method:
            flash('Invalid payment details.', 'warning')
            return redirect(url_for('payments_view'))
        db.session.add(Payment(user_id=current_user.id, amount=amount, method=method,
                               transaction_ref=ref, status='pending'))
        db.session.commit()
        flash('Payment submitted. Pending approval.', 'info')
        return redirect(url_for('payments_view'))
    payments = Payment.query.filter_by(user_id=current_user.id).order_by(Payment.date.desc()).all()
    return render_template('payments.html', payments=payments)

@app.route('/renewals', methods=['GET', 'POST'])
@role_required('admin')
def renewals_view():
    school = get_school()
    if request.method == 'POST':
        start = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
        end = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d').date()
        amount = float(request.form.get('amount', 0))
        delta = (end - start).days
        if not (180 <= delta <= 183):
            flash('Renewal period must be 6 months (180-183 days).', 'danger')
            return redirect(url_for('renewals_view'))
        db.session.add(Renewal(school_id=school.id, start_date=start, end_date=end, amount=amount))
        db.session.commit()
        flash('Renewal recorded.', 'success')
        return redirect(url_for('renewals_view'))
    renewals = Renewal.query.filter_by(school_id=school.id).order_by(Renewal.start_date.desc()).all()
    return render_template('renewals.html', renewals=renewals)

# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@app.route('/chat', methods=['GET', 'POST'])
@login_required
def chat_view():
    receiver_id = request.args.get('user', type=int)
    receiver = None
    messages = []
    if receiver_id:
        receiver = User.query.get_or_404(receiver_id)
        if not can_chat(current_user, receiver):
            abort(403)
        messages = ChatMessage.query.filter(
            ((ChatMessage.sender_id == current_user.id) & (ChatMessage.receiver_id == receiver_id)) |
            ((ChatMessage.sender_id == receiver_id) & (ChatMessage.receiver_id == current_user.id))
        ).order_by(ChatMessage.timestamp).all()
        ChatMessage.query.filter_by(sender_id=receiver_id, receiver_id=current_user.id, is_read=False)\
            .update({'is_read': True})
        db.session.commit()
    if request.method == 'POST':
        receiver_id = request.form.get('receiver_id', type=int)
        text = request.form.get('message', '').strip()
        receiver = User.query.get_or_404(receiver_id)
        if text and can_chat(current_user, receiver):
            db.session.add(ChatMessage(sender_id=current_user.id, receiver_id=receiver_id, message=text))
            db.session.commit()
        return redirect(url_for('chat_view', user=receiver_id))

    # Determine allowed chat partners
    role_filter = []
    if current_user.role == 'admin':
        role_filter.append('teacher')
    elif current_user.role == 'teacher':
        role_filter = ['admin', 'student', 'parent']
    elif current_user.role == 'student':
        role_filter = ['student', 'teacher']
    elif current_user.role == 'parent':
        role_filter = ['teacher']
    users = User.query.filter(User.role.in_(role_filter), User.id != current_user.id).all()
    return render_template('chat.html', users=users, receiver=receiver, messages=messages)

# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

with app.app_context():
    db.create_all()
    school = School.query.first()
    if not school:
        school = School(name="My School", motto="Excellence in Education")
        db.session.add(school)
        db.session.commit()
    if not User.query.filter_by(role='admin').first():
        admin = User(first_name='System', last_name='Admin', email='admin@school.com',
                     role='admin', password_hash=generate_password_hash('admin123'))
        db.session.add(admin)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
