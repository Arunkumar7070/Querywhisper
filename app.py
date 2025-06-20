from flask import Flask, request, render_template, session, redirect, url_for
from flask_bcrypt import Bcrypt
from pymongo import MongoClient
import os
from dotenv import load_dotenv
from datetime import datetime
from functools import wraps
import urllib.parse
import pymysql
import psycopg2
import pyodbc
import sqlite3
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

# Database configuration
DB_CONFIGS = {
    'mysql': {
        'name': 'MySQL',
        'icon': 'fas fa-database',
        'default_port': 3306,
        'fields': ['server', 'port', 'database', 'username', 'password']
    },
    'postgresql': {
        'name': 'PostgreSQL',
        'icon': 'fas fa-elephant',
        'default_port': 5432,
        'fields': ['server', 'port', 'database', 'username', 'password']
    },
    'sqlite': {
        'name': 'SQLite',
        'icon': 'fas fa-file-alt',
        'default_port': None,
        'fields': ['database_path']
    },
    'sqlserver': {
        'name': 'SQL Server',
        'icon': 'fas fa-server',
        'default_port': 1433,
        'fields': ['server', 'port', 'database', 'username', 'password']
    }
}

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
    session.pop('db_type', None)
    session.pop('db_credentials', None)
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
    return render_template('index.html', user_data=user_data, db_configs=DB_CONFIGS)

# Database connection route (protected)
@app.route('/getinput', methods=['POST'])
@login_required
def getinput():
    db_type = request.form['db_type']
    
    try:
        if db_type == 'mysql':
            connection_result = connect_mysql(request.form)
        elif db_type == 'postgresql':
            connection_result = connect_postgresql(request.form)
        elif db_type == 'sqlite':
            connection_result = connect_sqlite(request.form)
        elif db_type == 'sqlserver':
            connection_result = connect_sqlserver(request.form)
        else:
            raise ValueError(f"Unsupported database type: {db_type}")
        
        if connection_result['success']:
            session['db_type'] = db_type
            session['uri'] = connection_result['uri']
            session['database'] = connection_result['database']
            session['db_credentials'] = connection_result['credentials']
            
            user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
            user_data = {
                'name': user.get('name', 'User'),
                'email': user['email']
            }
            return render_template('index.html', 
                                  status='success', 
                                  message=f'Successfully connected to {DB_CONFIGS[db_type]["name"]} database.',
                                  connected_db=connection_result['database'],
                                  connected_db_type=DB_CONFIGS[db_type]['name'],
                                  user_data=user_data,
                                  db_configs=DB_CONFIGS)
        else:
            raise Exception(connection_result['error'])
            
    except Exception as e:
        user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
        user_data = {
            'name': user.get('name', 'User'),
            'email': user['email']
        } if user else None
        return render_template('index.html', 
                              status='error', 
                              message=f'Connection failed: {str(e)}',
                              user_data=user_data,
                              db_configs=DB_CONFIGS)

def connect_mysql(form_data):
    server = form_data['server']
    port = form_data.get('port', 3306)
    database = form_data['database']
    username = form_data['username']
    password = form_data['password']
    
    password_encoded = urllib.parse.quote(password)
    uri = f"mysql+pymysql://{username}:{password_encoded}@{server}:{port}/{database}"
    
    engine = create_engine(uri)
    connection = engine.connect()
    connection.execute(text('SELECT 1'))
    connection.close()
    
    return {
        'success': True,
        'uri': uri,
        'database': database,
        'credentials': {
            'host': server,
            'port': int(port),
            'user': username,
            'password': password,
            'database': database
        }
    }

def connect_postgresql(form_data):
    server = form_data['server']
    port = form_data.get('port', 5432)
    database = form_data['database']
    username = form_data['username']
    password = form_data['password']
    
    password_encoded = urllib.parse.quote(password)
    uri = f"postgresql://{username}:{password_encoded}@{server}:{port}/{database}"
    
    engine = create_engine(uri)
    connection = engine.connect()
    connection.execute(text('SELECT 1'))
    connection.close()
    
    return {
        'success': True,
        'uri': uri,
        'database': database,
        'credentials': {
            'host': server,
            'port': int(port),
            'user': username,
            'password': password,
            'database': database
        }
    }

def connect_sqlite(form_data):
    database_path = form_data['database_path']
    
    uri = f"sqlite:///{database_path}"
    
    engine = create_engine(uri)
    connection = engine.connect()
    connection.execute(text('SELECT 1'))
    connection.close()
    
    return {
        'success': True,
        'uri': uri,
        'database': database_path.split('/')[-1],
        'credentials': {
            'database_path': database_path
        }
    }

def connect_sqlserver(form_data):
    server = form_data['server']
    port = form_data.get('port', 1433)
    database = form_data['database']
    username = form_data['username']
    password = form_data['password']
    
    password_encoded = urllib.parse.quote(password)
    uri = f"mssql+pyodbc://{username}:{password_encoded}@{server}:{port}/{database}?driver=ODBC+Driver+17+for+SQL+Server"
    
    engine = create_engine(uri)
    connection = engine.connect()
    connection.execute(text('SELECT 1'))
    connection.close()
    
    return {
        'success': True,
        'uri': uri,
        'database': database,
        'credentials': {
            'host': server,
            'port': int(port),
            'user': username,
            'password': password,
            'database': database
        }
    }

def get_database_schema(db_type, credentials):
    """Get schema information based on database type"""
    if db_type == 'mysql':
        return get_mysql_schema(credentials)
    elif db_type == 'postgresql':
        return get_postgresql_schema(credentials)
    elif db_type == 'sqlite':
        return get_sqlite_schema(credentials)
    elif db_type == 'sqlserver':
        return get_sqlserver_schema(credentials)
    else:
        raise ValueError(f"Unsupported database type: {db_type}")

def get_mysql_schema(credentials):
    connection = pymysql.connect(
        host=credentials['host'],
        port=credentials['port'],
        user=credentials['user'],
        password=credentials['password'],
        database=credentials['database'],
        cursorclass=pymysql.cursors.DictCursor
    )
    
    schema_dict = {}
    with connection.cursor() as cursor:
        cursor.execute("SHOW TABLES")
        table_names = [row[f'Tables_in_{credentials["database"]}'] for row in cursor.fetchall()]
        
        for table in table_names:
            cursor.execute(f"SHOW COLUMNS FROM `{table}`")
            schema_dict[table] = [{
                "name": col['Field'],
                "type": col['Type'],
                "key": col.get('Key')
            } for col in cursor.fetchall()]
    
    connection.close()
    return schema_dict

def get_postgresql_schema(credentials):
    connection = psycopg2.connect(
        host=credentials['host'],
        port=credentials['port'],
        user=credentials['user'],
        password=credentials['password'],
        database=credentials['database']
    )
    
    schema_dict = {}
    cursor = connection.cursor()
    
    # Get table names
    cursor.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public'
    """)
    table_names = [row[0] for row in cursor.fetchall()]
    
    # Get column information for each table
    for table in table_names:
        cursor.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = %s AND table_schema = 'public'
            ORDER BY ordinal_position
        """, (table,))
        
        schema_dict[table] = [{
            "name": col[0],
            "type": col[1],
            "nullable": col[2] == 'YES',
            "default": col[3]
        } for col in cursor.fetchall()]
    
    connection.close()
    return schema_dict

def get_sqlite_schema(credentials):
    connection = sqlite3.connect(credentials['database_path'])
    cursor = connection.cursor()
    
    # Get table names
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    table_names = [row[0] for row in cursor.fetchall()]
    
    schema_dict = {}
    for table in table_names:
        cursor.execute(f"PRAGMA table_info({table})")
        schema_dict[table] = [{
            "name": col[1],
            "type": col[2],
            "nullable": not col[3],
            "default": col[4],
            "primary_key": col[5]
        } for col in cursor.fetchall()]
    
    connection.close()
    return schema_dict

def get_sqlserver_schema(credentials):
    connection_string = f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={credentials['host']},{credentials['port']};DATABASE={credentials['database']};UID={credentials['user']};PWD={credentials['password']}"
    connection = pyodbc.connect(connection_string)
    cursor = connection.cursor()
    
    # Get table names
    cursor.execute("""
        SELECT TABLE_NAME 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_TYPE = 'BASE TABLE'
    """)
    table_names = [row[0] for row in cursor.fetchall()]
    
    schema_dict = {}
    for table in table_names:
        cursor.execute("""
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION
        """, table)
        
        schema_dict[table] = [{
            "name": col[0],
            "type": col[1],
            "nullable": col[2] == 'YES',
            "default": col[3]
        } for col in cursor.fetchall()]
    
    connection.close()
    return schema_dict

# Query submission route (protected)
@app.route('/submit_sentence', methods=['POST'])
@login_required
def submit_sentence():
    sentence = request.form['sentence']
    uri = session.get('uri')
    db_type = session.get('db_type')
    db_credentials = session.get('db_credentials')

    if not uri or not db_credentials or not db_type:
        user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
        user_data = {
            'name': user.get('name', 'User'),
            'email': user['email']
        } if user else None
        return render_template('index.html',
                              status='error',
                              message='No database connection found. Please connect to a database first.',
                              user_data=user_data,
                              db_configs=DB_CONFIGS)

    try:
        # Get database schema
        schema_dict = get_database_schema(db_type, db_credentials)
        
        # Generate SQL query
        sql_query = generate_sql_query(schema_dict, sentence, db_type)

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
                                   connected_db_type=DB_CONFIGS[db_type]['name'],
                                   sentence=sentence,
                                   user_data=user_data,
                                   db_configs=DB_CONFIGS)

        # Execute query using SQLAlchemy
        engine = create_engine(uri)
        connection = engine.connect()
        
        queries = [q.strip() for q in sql_query.split(';') if q.strip()]
        all_results = []
        last_columns = []

        for query in queries:
            result = connection.execute(text(query))
            if result.returns_rows:
                rows = result.fetchall()
                if rows:
                    last_columns = list(rows[0].keys())
                    all_results = [[row[col] for col in last_columns] for row in rows]
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
            connected_db_type=DB_CONFIGS[db_type]['name'],
            sentence=sentence,
            user_data=user_data,
            db_configs=DB_CONFIGS
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
            connected_db_type=DB_CONFIGS.get(db_type, {}).get('name', 'Unknown'),
            sentence=sentence,
            user_data=user_data,
            db_configs=DB_CONFIGS
        )

# Disconnect route (protected)
@app.route('/disconnect', methods=['POST'])
@login_required
def disconnect():
    session.pop('uri', None)
    session.pop('database', None)
    session.pop('db_type', None)
    session.pop('db_credentials', None)
    return redirect(url_for('index'))

# SQL query generation function
def generate_sql_query(schema_dict, sentence, db_type):
    # Adjust prompt based on database type
    db_specific_notes = {
        'mysql': "Use MySQL syntax. Remember to use backticks for table/column names if needed.",
        'postgresql': "Use PostgreSQL syntax. Use double quotes for identifiers if needed.",
        'sqlite': "Use SQLite syntax. Keep queries simple and compatible with SQLite.",
        'sqlserver': "Use SQL Server syntax. Use square brackets for identifiers if needed."
    }
    
    prompt = f"""You are an SQL assistant for {DB_CONFIGS[db_type]['name']}. Convert the following natural language question into a **single valid SQL query** using this schema:
                Schema: {schema_dict}
                Question: {sentence}
                
                {db_specific_notes.get(db_type, '')}
                
                Only output one SQL query using the exact table and column names from the schema without modification or unnecessary escaping. Do not explain anything."""
    
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

            # Clean up column names based on database type
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