from flask import Flask, render_template, request, redirect, url_for, session, flash
from pymongo import MongoClient
from bson.objectid import ObjectId
import qrcode 
from io import BytesIO
import base64
import os
from dotenv import load_dotenv
import secrets
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)  # Generate a secure secret key

# MongoDB Atlas connection
# In production, use: os.environ.get("MONGODB_URI")
# For demonstration, using a placeholder connection string
MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb+srv://abhinav2003singh16:Abhi2003@cluster0.ircy7qr.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
client = MongoClient(MONGODB_URI)
db = client.clinic_db
patients_collection = db.patients
admin_collection = db.admin_credentials

# Add indexes for better performance
admin_collection.create_index([("user_id", 1)], unique=True)
admin_collection.create_index([("linked_users", 1)])

# Remove hardcoded credentials
# ADMIN_CREDENTIALS = {
#     "id1": "pass1",  # For /form access
#     "id2": "pass2"   # For /qrs access
# }

# Helper function to generate QR code
def generate_qr_code(data):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    img.save(buffered)
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return img_str

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login1', methods=['GET', 'POST'])
def login1():
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        password = request.form.get('password')
        
        admin = admin_collection.find_one({"user_id": user_id, "password": password, "access_type": "form"})
        if admin:
            session['user_id'] = user_id
            return redirect(url_for('form'))
        else:
            flash('Invalid credentials', 'danger')
    
    return render_template('login1.html')

@app.route('/login2', methods=['GET', 'POST'])
def login2():
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        password = request.form.get('password')
        
        admin = admin_collection.find_one({"user_id": user_id, "password": password, "access_type": "qrs"})
        if admin:
            session['user_id'] = user_id
            return redirect(url_for('qrs'))
        else:
            flash('Invalid credentials', 'danger')
    
    return render_template('login2.html')

@app.route('/form', methods=['GET', 'POST'])
def form():
    if 'user_id' not in session:
        return redirect(url_for('login1'))
    
    user = admin_collection.find_one({"user_id": session['user_id'], "access_type": "form"})
    if not user:
        session.clear()
        return redirect(url_for('login1'))
    
    if request.method == 'POST':
        try:
            # Get form data
            name = request.form.get('name')
            age = request.form.get('age')
            report_type = request.form.get('report_type')
            amount = request.form.get('amount')
            appointment_date_str = request.form.get('appointment_date')
            
            # Parse the appointment date with error handling
            try:
                appointment_date = datetime.strptime(appointment_date_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                # If the date format is invalid, use current date and time
                flash('Invalid date format. Using current date and time.', 'warning')
                appointment_date = datetime.now()
            
            # Create patient data with appointment timestamp
            patient_data = {
                'name': name,
                'age': age,
                'report_type': report_type,
                'amount': amount,
                'created_by': session['user_id'],  # Store user_id instead of _id
                'created_at': datetime.now(),
                'appointment_date': appointment_date,
                'report_status': 'Waiting'  # Default status
            }
            
            # First insert the patient data to get the ID
            result = patients_collection.insert_one(patient_data)
            patient_id = str(result.inserted_id)
            
            # Now generate QR code with the patient ID
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(f"http://{request.host}/patient/{patient_id}")
            qr.make(fit=True)
            qr_image = qr.make_image(fill_color="black", back_color="white")
            
            # Convert QR code to base64
            buffered = BytesIO()
            qr_image.save(buffered, format="PNG")
            qr_base64 = base64.b64encode(buffered.getvalue()).decode()
            
            # Update the patient record with the QR code
            patients_collection.update_one(
                {'_id': result.inserted_id},
                {'$set': {'qr_code': qr_base64}}
            )
            
            flash('Patient registered successfully!', 'success')
            return redirect(url_for('form'))
            
        except Exception as e:
            flash(f'Error registering patient: {str(e)}', 'danger')
    
    return render_template('form.html', now=datetime.now())

@app.route('/qrs')
def qrs():
    if 'user_id' not in session:
        return redirect(url_for('login2'))
    
    user = admin_collection.find_one({"user_id": session['user_id'], "access_type": "qrs"})
    if not user:
        session.clear()
        return redirect(url_for('login2'))
    
    date_filter = request.args.get('date_filter')
    status_filter = request.args.get('status_filter')
    query = {}

    if user.get('linked_users'):
        query['created_by'] = {'$in': user['linked_users']}

    if date_filter:
        try:
            filter_date = datetime.strptime(date_filter, '%Y-%m-%d')
            next_day = filter_date + timedelta(days=1)
            query['appointment_date'] = {
                '$gte': filter_date,
                '$lt': next_day
            }
        except ValueError:
            flash('Invalid date format', 'warning')
    if status_filter:
        query['report_status'] = status_filter

    patients = list(patients_collection.find(query).sort('appointment_date', -1))
    
    # Convert ObjectId to string and ensure dates are properly formatted
    for patient in patients:
        patient['_id'] = str(patient['_id'])
        
        # Ensure appointment_date is a datetime object
        if not patient.get('appointment_date'):
            if patient.get('created_at'):
                patient['appointment_date'] = patient['created_at']
            else:
                patient['appointment_date'] = datetime.now()
        
        # Convert to string format for display
        if isinstance(patient['appointment_date'], datetime):
            patient['formatted_date'] = patient['appointment_date'].strftime('%Y-%m-%d %H:%M')
        else:
            patient['formatted_date'] = 'N/A'
    
    return render_template('qrs.html', patients=patients)

@app.route('/patient/<id>')
def patient_detail(id):
    try:
        patient = patients_collection.find_one({'_id': ObjectId(id)})
        if patient:
            patient['_id'] = str(patient['_id'])
            return render_template('patient_detail.html', patient=patient)
        else:
            flash('Patient not found', 'danger')
            return redirect(url_for('index'))
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))

# New route to add admin credentials
@app.route('/add_admin', methods=['GET', 'POST'])
def add_admin():
    if request.method == 'POST':
        user_id = request.form.get('user_id').strip()
        password = request.form.get('password').strip()
        access_type = request.form.get('access_type').strip()
        linked_users = request.form.get('linked_users', '').strip()
        
        if not user_id or not password or not access_type:
            flash('All fields are required', 'danger')
            return render_template('add_admin.html')
        
        # Convert linked_users string to list
        linked_users_list = [user.strip() for user in linked_users.split(',')] if linked_users else []
        
        admin_data = {
            'user_id': user_id,
            'password': password,
            'access_type': access_type,
            'linked_users': linked_users_list
        }
        
        try:
            admin_collection.insert_one(admin_data)
            flash('Admin added successfully!', 'success')
        except Exception as e:
            flash('Error adding admin. User ID might already exist.', 'danger')
        
        return redirect(url_for('add_admin'))
    
    return render_template('add_admin.html')

@app.route('/update_status/<id>', methods=['POST'])
def update_status(id):
    if 'user_id' not in session:
        flash('Please login first', 'warning')
        return redirect(url_for('login2'))
    
    # Check if the logged-in user has QR access
    admin = admin_collection.find_one({"user_id": session['user_id'], "access_type": "qrs"})
    if not admin:
        flash('You do not have access to this page', 'danger')
        return redirect(url_for('login2'))
    
    try:
        new_status = request.form.get('report_status')
        if new_status not in ['Waiting', 'Reception', 'Done']:
            flash('Invalid status', 'danger')
            return redirect(url_for('qrs'))
        
        result = patients_collection.update_one(
            {'_id': ObjectId(id)},
            {'$set': {'report_status': new_status}}
        )
        
        if result.modified_count > 0:
            flash('Status updated successfully!', 'success')
        else:
            flash('No changes made', 'info')
            
    except Exception as e:
        flash(f'Error updating status: {str(e)}', 'danger')
    
    return redirect(url_for('qrs'))

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)