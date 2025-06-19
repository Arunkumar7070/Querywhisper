from flask import Flask, request, render_template, session, redirect, url_for
from flask_bcrypt import Bcrypt
from pymongo import MongoClient
import os
from dotenv import load_dotenv
from datetime import datetime
from functools import wraps
import urllib.parse
import pymysql
from sqlalchemy import create_engine, text
import requests
import re
from bson.objectid import ObjectId

# Load environment variables from .env
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "default-secret-key")

# Initialize Bcrypt
bcrypt = Bcrypt(app)

# Set up MongoDB connection for storing user details
mongo_client = MongoClient(os.getenv("MONGODB_URI"))
db = mongo_client[os.getenv("MONGODB_DATABASE")]
users_collection = db["users"]

# Hugging Face API settings for SQL query generation
HUGGINGFACE_API_TOKEN = os.getenv("HUGGINGFACE_API_TOKEN")
HUGGINGFACE_MODEL = os.getenv("HUGGINGFACE_MODEL")

# Decorator to restrict access to logged-in users only
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Registration route (simplified without OTP)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['username']
        password = request.form['password']
        
        if users_collection.find_one({'email': email}):
            return render_template('register.html', error='Email already registered')
        
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        
        user = {
            'name': name,
            'email': email,
            'password': hashed_password,
            'created_at': datetime.utcnow()
        }
        users_collection.insert_one(user)
        
        return render_template('register.html', success='Registration successful! Please login.')
    
    return render_template('register.html')

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['username']
        password = request.form['password']
        
        user = users_collection.find_one({'email': email})
        if user and bcrypt.check_password_hash(user['password'], password):
            session['user_id'] = str(user['_id'])
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Invalid email or password')
    
    return render_template('login.html')

# Logout route
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('uri', None)
    session.pop('database', None)
    return redirect(url_for('index'))

# Index route with welcome message
@app.route('/')
def index():
    user_data = None
    if 'user_id' in session:
        user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
        if user:
            user_data = {
                'name': user.get('name', 'User'),
                'email': user['email']
            }
    return render_template('index.html', user_data=user_data)

# Database connection route (protected)
@app.route('/getinput', methods=['POST'])
@login_required
def getinput():
    server = request.form['server']
    database = request.form['database']
    username = request.form['username']
    password = request.form['password']
    
    try:
        password_encoded = urllib.parse.quote(password)
        uri = f"mysql+pymysql://{username}:{password_encoded}@{server}/{database}"
        engine = create_engine(uri)
        connection = engine.connect()
        connection.execute(text('SELECT 1'))
        connection.close()
        
        session['uri'] = uri
        session['database'] = database
        session['db_credentials'] = {
            'host': server,
            'user': username,
            'password': password,
            'database': database
        }
        
        user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
        user_data = {
            'name': user.get('name', 'User'),
            'email': user['email']
        }
        return render_template('index.html', 
                              status='success', 
                              message='Successfully connected to MySQL database.',
                              connected_db=database,
                              user_data=user_data)
    except Exception as e:
        user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
        user_data = {
            'name': user.get('name', 'User'),
            'email': user['email']
        } if user else None
        return render_template('index.html', 
                              status='error', 
                              message=f'Connection failed: {str(e)}',
                              user_data=user_data)

# Query submission route (protected)
@app.route('/submit_sentence', methods=['POST'])
@login_required
def submit_sentence():
    sentence = request.form['sentence']
    uri = session.get('uri')
    db_credentials = session.get('db_credentials')

    if not uri or not db_credentials:
        user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
        user_data = {
            'name': user.get('name', 'User'),
            'email': user['email']
        } if user else None
        return render_template('index.html',
                              status='error',
                              message='No database connection found. Please connect to a database first.',
                              user_data=user_data)

    try:
        connection = pymysql.connect(
            host=db_credentials['host'],
            user=db_credentials['user'],
            password=db_credentials['password'],
            database=db_credentials['database'],
            cursorclass=pymysql.cursors.DictCursor
        )

        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            table_names = [row[f'Tables_in_{db_credentials["database"]}'] for row in cursor.fetchall()]
            schema_dict = {}
            for table in table_names:
                cursor.execute(f"SHOW COLUMNS FROM `{table}`")
                schema_dict[table] = [{
                    "name": col['Field'],
                    "type": col['Type'],
                    "key": col.get('Key')
                } for col in cursor.fetchall()]

        sql_query = generate_sql_query(schema_dict, sentence)

        if sql_query.startswith("Error:"):
            user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
            user_data = {
                'name': user.get('name', 'User'),
                'email': user['email']
            } if user else None
            return render_template('index.html',
                                   status='error',
                                   message=sql_query,
                                   connected_db=session.get('database'),
                                   sentence=sentence,
                                   user_data=user_data)

        queries = [q.strip() for q in sql_query.split(';') if q.strip()]
        all_results = []
        last_columns = []

        with connection.cursor() as cursor:
            for query in queries:
                cursor.execute(query)
                if cursor.description:
                    data = cursor.fetchall()
                    if data:
                        last_columns = list(data[0].keys())
                        all_results = [[row[col] for col in last_columns] for row in data]
                    else:
                        all_results = []
                else:
                    connection.commit()

        connection.close()

        user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
        user_data = {
            'name': user.get('name', 'User'),
            'email': user['email']
        } if user else None
        return render_template(
            'index.html',
            status='success',
            message='Query executed successfully.',
            sql_query=sql_query,
            query_result=all_results,
            columns=last_columns,
            connected_db=session.get('database'),
            sentence=sentence,
            user_data=user_data
        )

    except Exception as e:
        user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
        user_data = {
            'name': user.get('name', 'User'),
            'email': user['email']
        } if user else None
        return render_template(
            'index.html',
            status='error',
            message=f'Error executing SQL query: {str(e)}',
            sql_query=sql_query if 'sql_query' in locals() else None,
            connected_db=session.get('database'),
            sentence=sentence,
            user_data=user_data
        )

# Disconnect route (protected)
@app.route('/disconnect', methods=['POST'])
@login_required
def disconnect():
    session.pop('uri', None)
    session.pop('database', None)
    return redirect(url_for('index'))

# SQL query generation function
def generate_sql_query(schema_dict, sentence):
    prompt = f"""You are an SQL assistant. Convert the following natural language question into a **single valid SQL query** using this schema:
                Schema: {schema_dict} ,Question: {sentence} Only output one SQL query using the exact table and column names from the schema without modification or unnecessary escaping. Do not explain anything"""
    API_URL = f"https://api-inference.huggingface.co/models/{HUGGINGFACE_MODEL}"
    headers = {
        "Authorization": f"Bearer {HUGGINGFACE_API_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 250,
            "temperature": 0.3,
            "top_p": 0.95,
            "return_full_text": False
        }
    }
    
    try:
        response = requests.post(API_URL, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        if isinstance(result, list) and len(result) > 0:
            sql_query = result[0].get("generated_text", "").strip()
            sql_query = sql_query.replace("[/INST]", "").strip()

            match = re.search(r'\b(SELECT|INSERT|UPDATE|DELETE)\b.*?(?=;\s*$)', sql_query, re.DOTALL | re.IGNORECASE)
            if match:
                sql_query = match.group(0).strip()
            else:
                return "Error: Could not extract a valid SQL query from the model output."

            correct_column_names = [col['name'] for table in schema_dict.values() for col in table]
            for col in correct_column_names:
                if '_' in col:
                    escaped_col = col.replace('_', '\\_')
                    sql_query = sql_query.replace(escaped_col, col)

            return sql_query
        else:
            return "Error: Unexpected response format from the model."
    except Exception as e:
        return f"Error generating SQL query: {str(e)}"

if __name__ == '__main__':
    app.run(debug=True)