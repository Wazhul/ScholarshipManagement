import os
import json
import pandas as pd
from datetime import datetime
from sqlalchemy import Enum
from flask import Flask, request, render_template, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from web3 import Web3
from werkzeug.security import generate_password_hash, check_password_hash

# -------------------------------
# Flask App & Database Setup
# -------------------------------
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///students.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Monkey-patch create_all to ensure app context
_orig_create_all = db.create_all

def create_all_with_context(*args, **kwargs):
    with app.app_context():
        _orig_create_all(*args, **kwargs)

# Override method
db.create_all = create_all_with_context
ROLE_ENUM = ('student', 'institution', 'donor', 'admin')


# -------------------------------
# Database Models
# -------------------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(
        Enum(*ROLE_ENUM, name='user_roles'),
        nullable=False,
        default='student'
    )
    wallet_address = db.Column(db.String(100))
    institution_name = db.Column(db.String(100))
    balance = db.Column(db.Float, default=0.0)

class Scholarship(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    institution_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    deadline = db.Column(db.DateTime)
    criteria = db.Column(db.Text)
    department = db.Column(db.String(50))

    # Relationships
    institution = db.relationship('User', backref='created_scholarships')
    applications = db.relationship('Application', backref='scholarship', cascade='all, delete-orphan')

class Application(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    scholarship_id = db.Column(db.Integer, db.ForeignKey('scholarship.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')
    overall_score = db.Column(db.Float)
    hsc_score = db.Column(db.Float)
    ssc_score = db.Column(db.Float)
    preparation = db.Column(db.Float)
    attendance = db.Column(db.Float)
    income = db.Column(db.Float)
    extracurricular = db.Column(db.Float)
    tx_hash = db.Column(db.String(66))
    rejection_reason = db.Column(db.Text, nullable=True)
    apply_date = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship('User', backref='applications')

# -------------------------------
# ML Predictor
# -------------------------------
class ScholarshipPredictor:
    def __init__(self):
        self.model = RandomForestClassifier(n_estimators=100, random_state=42)
        self.feature_columns = []
        self.trained = False

    def train_model(self, dataset_path='student_dataset.csv'):
        df = pd.read_csv(dataset_path)
        # Preprocessing
        def preprocess_income(val):
            m = {'Low (Below 15,000)':15000, 'Lower middle (15,000-30,000)':22500,
                 'Middle (15,000-30,000)':22500, 'Upper middle (30,000-50,000)':40000,
                 'High (Above 50,000)':60000}
            return m.get(str(val).strip(), pd.NA)
        def preprocess_preparation(val):
            m = {'0-1 Hour':0.5,'1-2 Hours':1.5,'2-3 Hours':2.5,'More than 3 Hours':4.0}
            return m.get(str(val).strip(), pd.NA)
        def preprocess_attendance(val):
            s = str(val).strip()
            if '-' in s:
                return float(s.split('-')[0].replace('%','')) + 5
            if 'Below' in s:
                return float(s.replace('Below','').replace('%','').strip()) - 5
            return float(s.replace('%',''))
        def preprocess_extra(val):
            return 1 if str(val).strip().lower()=='yes' else 0

        for col, fn in [('Income',preprocess_income), ('Preparation',preprocess_preparation),
                        ('Attendance',preprocess_attendance), ('Extra',preprocess_extra)]:
            df[col] = df[col].apply(fn)
        cols = ['HSC','SSC','Preparation','Attendance','Overall','Income','Extra']
        for c in cols:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df.dropna(subset=cols, inplace=True)

        if len(df) < 10:
            raise ValueError('Not enough valid rows after preprocessing')

        income_thr = df['Income'].quantile(0.3)
        overall_thr = df['Overall'].quantile(0.7)
        extra_thr = df['Extra'].quantile(0.7)
        df['eligible'] = ((df['Income']<income_thr) & (df['Overall']>overall_thr) & (df['Extra']>extra_thr)).astype(int)

        num = df[cols]
        cat = pd.get_dummies(df['Department'], prefix='dept')
        X = pd.concat([num,cat], axis=1)
        y = df['eligible']
        self.feature_columns = X.columns.tolist()

        X_train, X_test, y_train, y_test = train_test_split(X,y,test_size=0.2,random_state=42)
        self.model.fit(X_train, y_train)
        print(f"Model trained ({len(X_train)} samples), accuracy: {self.model.score(X_test,y_test):.2f}")
        self.trained = True

    def predict(self, df_in):
        if not self.trained:
            raise RuntimeError('Model not trained')
        for col in self.feature_columns:
            if col not in df_in.columns:
                df_in[col] = 0
        df_in = df_in[self.feature_columns]
        return self.model.predict(df_in)

predictor = ScholarshipPredictor()
contract = None

# -------------------------------
# Authentication & User Routes
# -------------------------------
@app.route('/')
def home():
    return redirect(url_for('dashboard'))

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='POST':
        uname = request.form['username']
        pwd = request.form['password']
        role = request.form['role']
        waddr = request.form.get('wallet_address')
        iname = request.form.get('institution_name')
        if User.query.filter_by(username=uname).first():
            flash('Username taken', 'error')
            return redirect(url_for('register'))
        user = User(
            username=uname,
            password=generate_password_hash(pwd),
            role=role,
            wallet_address=waddr,
            institution_name=iname
        )
        db.session.add(user)
        db.session.commit()
        flash('Registered! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        uname = request.form['username']
        pwd = request.form['password']
        user = User.query.filter_by(username=uname).first()
        if user and check_password_hash(user.password,pwd):
            session['user_id']=user.id
            session['role']=user.role
            flash('Logged in','success')
            return redirect(url_for('dashboard'))
        flash('Invalid credentials','error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out','success')
    return redirect(url_for('login'))
# -------------------------------
# Scholarship CRUD & Dashboard
# -------------------------------
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])

    if user.role == 'student':
        applied = Application.query.filter_by(student_id=user.id).all()
        available = Scholarship.query.all()
        stats = {
            'pending':  sum(1 for a in applied if a.status=='pending'),
            'approved': sum(1 for a in applied if a.status=='approved'),
            'rejected': sum(1 for a in applied if a.status=='rejected'),
        }
        return render_template('dashboard.html',
            current_user=user,
            applied_scholarships=applied,
            available_scholarships=available,
            application_stats=stats
        )

    elif user.role == 'institution':
        created = Scholarship.query.filter_by(institution_id=user.id).all()
        return render_template('dashboard.html',
            current_user=user,
            created_scholarships=created
        )

    else:
        all_users = User.query.all()
        return render_template('dashboard.html',
            current_user=user,
            all_users=all_users
        )

@app.route('/create_scholarship', methods=['POST'])
def create_scholarship():
    if session.get('role')!='institution':
        flash('Unauthorized','error')
        return redirect(url_for('login'))
    title      = request.form['name'].strip()
    amount     = float(request.form['amount'])
    deadline   = datetime.strptime(request.form['deadline'],'%Y-%m-%d')
    criteria   = request.form['criteria'].strip()
    department = request.form['department'].strip()
    new_sch = Scholarship(
        title=title,
        institution_id=session['user_id'],
        amount=amount,
        deadline=deadline,
        criteria=criteria,
        department=department
    )
    db.session.add(new_sch)
    db.session.commit()
    flash('Scholarship created','success')
    return redirect(url_for('dashboard'))

@app.route('/edit_scholarship/<int:id>', methods=['GET','POST'], endpoint='edit_scholarship')
def edit_scholarship(id):
    if session.get('role')!='institution':
        flash('Unauthorized','error')
        return redirect(url_for('login'))
    sch = Scholarship.query.get_or_404(id)
    if sch.institution_id != session['user_id']:
        flash('Cannot edit others','error')
        return redirect(url_for('dashboard'))

    if request.method=='POST':
        sch.title      = request.form['name'].strip()
        sch.amount     = float(request.form['amount'])
        sch.deadline   = datetime.strptime(request.form['deadline'],'%Y-%m-%d')
        sch.criteria   = request.form['criteria'].strip()
        sch.department = request.form['department'].strip()
        db.session.commit()
        flash('Scholarship updated','success')
        return redirect(url_for('dashboard'))

    return render_template('edit_scholarship.html', scholarship=sch)

@app.route('/delete-scholarship/<int:id>')
def delete_scholarship(id):
    if session.get('role')!='institution':
        flash('Unauthorized','error')
        return redirect(url_for('login'))
    sch = Scholarship.query.get_or_404(id)
    if sch.institution_id != session['user_id']:
        flash('Cannot delete others','error')
        return redirect(url_for('dashboard'))
    db.session.delete(sch)
    db.session.commit()
    flash('Scholarship deleted','success')
    return redirect(url_for('dashboard'))

@app.route('/apply/<int:scholarship_id>', methods=['GET','POST'])
def apply(scholarship_id):
    # only logged-in students
    if session.get('role') != 'student':
        return redirect(url_for('login'))

    sch = Scholarship.query.get_or_404(scholarship_id)

    if request.method == 'POST':
        # 1) Gather & validate inputs
        try:
            data = {k: float(request.form[k]) for k in
                    ['overall','hsc','ssc','preparation','attendance','income','extra']}
            dept = request.form['department']
        except (KeyError, ValueError):
            flash('All fields are required and must be numeric.', 'error')
            return redirect(request.url)

        for k in ['overall','hsc','ssc']:
            if not 0 <= data[k] <= 100:
                flash('Scores must be between 0 and 100.', 'error')
                return redirect(request.url)

        # 2) Build feature matrix
        import pandas as pd
        df_num = pd.DataFrame([{
            'HSC':         data['hsc'],
            'SSC':         data['ssc'],
            'Preparation': data['preparation'],
            'Attendance':  data['attendance'],
            'Overall':     data['overall'],
            'Income':      data['income'],
            'Extra':       data['extra']
        }])
        df_cat = pd.get_dummies(
            pd.DataFrame([{'Department': dept}]),
            prefix='dept'
        )
        feats = pd.concat([df_num, df_cat], axis=1)

        # 3) Predict & save
        pred   = predictor.predict(feats)[0]
        status = 'approved' if pred else 'rejected'
        appobj = Application(
            student_id      = session['user_id'],
            scholarship_id  = sch.id,
            overall_score   = data['overall'],
            hsc_score       = data['hsc'],
            ssc_score       = data['ssc'],
            preparation     = data['preparation'],
            attendance      = data['attendance'],
            income          = data['income'],
            extracurricular = data['extra'],
            status          = status
        )
        db.session.add(appobj)
        db.session.commit()

        flash(f'Application {status}!', 'success' if pred else 'error')
        return redirect(url_for('dashboard'))

    # GET → show form
    return render_template('apply.html', scholarship=sch)


# -------------------------------
# Main Entry
# -------------------------------
if __name__=='__main__':
    with app.app_context():
        #db.drop_all()
        db.create_all()
    try:
        predictor.train_model()
    except Exception:
        pass
    try:
        w3 = Web3(Web3.HTTPProvider('http://localhost:7545'))
        with open('ScholarshipManager.json') as f:
            abi = json.load(f).get('abi', [])
        contract = w3.eth.contract(address=Web3.to_checksum_address('0x471F8332f1E1249a351776E492330f54c7B04390'), abi=abi)
    except Exception:
        pass
    print("Starting Flask on http://127.0.0.1:5000")
    app.run(debug=True, host='127.0.0.1', port=5000)
