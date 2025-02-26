import os
import json
import numpy as np
import pandas as pd
from flask import Flask, request, render_template, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from web3 import Web3

# -------------------------------
# Flask App & Database Setup
# -------------------------------
app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this to a strong secret key
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///students.db'
db = SQLAlchemy(app)

# Student model to store user registration info and scholarship status
class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(100), unique=True, nullable=False)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    wallet_address = db.Column(db.String(100), nullable=False)
    scholarship_status = db.Column(db.String(50))  # e.g., "Selected" or "Not Selected"

# Global variable to store the training feature columns
model_feature_columns = None

# -------------------------------
# Data Loading and ML Model Setup
# -------------------------------
def load_and_prepare_data():
    """
    Load the student CSV dataset (student_dataset.csv) and prepare the data.
    Mapping:
        - 'Overall' corresponds to the overall score (replacing GPA)
        - 'Income' corresponds to the income data (replacing income)
        - 'Extra' corresponds to extracurricular activities (replacing extracurricular)
        - 'Department' corresponds to application history (replacing application_history)
    
    Eligibility Criteria:
        - Low income: Income below a certain threshold (e.g., lower 30%).
        - High overall score: Overall above a threshold (e.g., upper 30%).
        - High extracurricular participation: Extra above a threshold (e.g., upper 30%).
    """
    df = pd.read_csv('student_dataset.csv')
    df.ffill(inplace=True)

    # Convert columns to numeric
    df['Income'] = pd.to_numeric(df['Income'], errors='coerce')
    df['Overall'] = pd.to_numeric(df['Overall'], errors='coerce')
    df['Extra'] = pd.to_numeric(df['Extra'], errors='coerce')

    print("Columns in CSV:", df.columns)
    
    # Define thresholds based on quantiles
    income_threshold = df['Income'].quantile(0.3)
    overall_threshold = df['Overall'].quantile(0.7)
    extra_threshold = df['Extra'].quantile(0.7)
    
    # Create the 'eligible' column based on your criteria
    df['eligible'] = ((df['Income'] < income_threshold) &
                        (df['Overall'] > overall_threshold) &
                        (df['Extra'] > extra_threshold)).astype(int)
    
    # One-hot encode the 'Department' column to convert it to numeric
    department_dummies = pd.get_dummies(df['Department'], prefix='dept')
    
    # Concatenate the one-hot encoded columns with the numeric features
    features = pd.concat([df[['Overall', 'Income', 'Extra']], department_dummies], axis=1)
    target = df['eligible']
    
    return features, target

def train_model():
    """
    Train a Random Forest Classifier using the preprocessed data.
    """
    global model_feature_columns
    features, target = load_and_prepare_data()
    # Save the training feature columns for later use
    model_feature_columns = features.columns  
    X_train, X_test, y_train, y_test = train_test_split(features, target, test_size=0.3, random_state=42)
    
    model = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)
    model.fit(X_train, y_train)
    
    predictions = model.predict(X_test)
    acc = accuracy_score(y_test, predictions)
    print("Model Accuracy: ", acc)
    return model

ml_model = train_model()

# -------------------------------
# Blockchain Integration Setup
# -------------------------------
w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:7545"))
if not w3.is_connected():
    raise Exception("Web3 is not connected. Please ensure Ganache (or your Ethereum node) is running.")

contract_address = Web3.to_checksum_address("0xd8b934580fcE35a11B58C6D73aDeE468a2833fa8")
with open('scholarship_manager_abi.json', 'r') as abi_file:
    contract_abi = json.load(abi_file)

scholarship_contract = w3.eth.contract(address=contract_address, abi=contract_abi)
w3.eth.default_account = w3.eth.accounts[0]

# -------------------------------
# Web Routes for DApp Functionality
# -------------------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        wallet_address = request.form['wallet_address']
        unique_id = "UID" + str(np.random.randint(100000, 999999))
        new_student = Student(unique_id=unique_id, username=username, password=password,
                                wallet_address=wallet_address, scholarship_status="Pending")
        db.session.add(new_student)
        db.session.commit()
        flash("Registration successful! Please login.", "success")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        student = Student.query.filter_by(username=username, password=password).first()
        if student:
            session['student_id'] = student.id
            flash("Login successful!", "success")
            # Redirect to the scholarship application form after login
            return redirect(url_for('apply'))
        else:
            flash("Invalid credentials. Please try again.", "error")
            return redirect(url_for('login'))
    return render_template('login.html')

# Scholarship Application Route
@app.route('/apply', methods=['GET', 'POST'])
def apply():
    if 'student_id' not in session:
        flash("Please login to apply for the scholarship.", "warning")
        return redirect(url_for('login'))
    student = Student.query.get(session['student_id'])
    if request.method == 'POST':
        try:
            overall = float(request.form['overall'])
            income = float(request.form['income'])
            extra = float(request.form['extra'])
            department = request.form['department']
        except ValueError:
            flash("Invalid input. Please enter valid numeric values for Overall, Income, and Extra.", "error")
            return redirect(url_for('apply'))
        
        # Create a DataFrame with the same structure as the training features
        input_data = pd.DataFrame({
            'Overall': [overall],
            'Income': [income],
            'Extra': [extra],
            'Department': [department]
        })
        # One-hot encode the department column
        department_dummies = pd.get_dummies(input_data['Department'], prefix='dept')
        input_features = pd.concat([input_data[['Overall', 'Income', 'Extra']], department_dummies], axis=1)
        
        # Ensure the input features DataFrame has the same columns as the training set
        for col in model_feature_columns:
            if col not in input_features.columns:
                input_features[col] = 0
        input_features = input_features[model_feature_columns]
        
        # Make prediction using the trained model
        prediction = ml_model.predict(input_features)[0]
        if prediction == 1:
            student.scholarship_status = "Selected"
            is_eligible = True
            flash("Congratulations! You are eligible for the scholarship.", "success")
        else:
            student.scholarship_status = "Not Selected"
            is_eligible = False
            flash("Unfortunately, you are not eligible for the scholarship.", "error")
        
        db.session.commit()
        
        # Record the decision on the blockchain using the smart contract call
        tx_hash = scholarship_contract.functions.recordScholarship(student.unique_id, is_eligible).transact()
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        print("Blockchain transaction receipt:", receipt)
        
        return redirect(url_for('dashboard'))
    return render_template('apply.html')

@app.route('/dashboard')
def dashboard():
    if 'student_id' not in session:
        flash("Please login to access your dashboard.", "warning")
        return redirect(url_for('login'))
    student = Student.query.get(session['student_id'])
    return render_template('dashboard.html', student=student)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5001)
