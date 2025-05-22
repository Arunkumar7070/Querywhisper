from flask import Flask, request, render_template, session, redirect, url_for
import urllib.parse
import os
import pymysql
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import requests
import re

# Load environment variables from .env
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "default-secret-key")

HUGGINGFACE_API_TOKEN = os.getenv("HUGGINGFACE_API_TOKEN")
HUGGINGFACE_MODEL = os.getenv("HUGGINGFACE_MODEL")

def generate_sql_query(schema_dict, sentence):
    """Generate SQL query from natural language using Hugging Face Inference API"""
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

            # Extract the SQL query using regex
            match = re.search(r'\b(SELECT|INSERT|UPDATE|DELETE)\b.*?(?=;\s*$)', sql_query, re.DOTALL | re.IGNORECASE)
            if match:
                sql_query = match.group(0).strip()
            else:
                return "Error: Could not extract a valid SQL query from the model output."

            # Replace incorrectly escaped column names
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

@app.route('/')
def index():
    """Render the main page"""
    return render_template('index.html')

@app.route('/getinput', methods=['POST'])
def getinput():
    """Handle database connection form submission"""
    server = request.form['server']
    database = request.form['database']
    username = request.form['username']
    password = request.form['password']
    
    try:
        # URL encode the password to handle special characters
        password_encoded = urllib.parse.quote(password)
        uri = f"mysql+pymysql://{username}:{password_encoded}@{server}/{database}"
        
        # Test connection directly with SQLAlchemy Engine
        engine = create_engine(uri)
        connection = engine.connect()
        connection.execute(text('SELECT 1'))
        connection.close()
            
        # Store URI in session for future requests
        session['uri'] = uri
        session['database'] = database  # Store database name for UI

        # Store database credentials separately for using direct connections
        session['db_credentials'] = {
            'host': server,
            'user': username,
            'password': password,
            'database': database
        }
        
        return render_template('index.html', 
                              status='success', 
                              message='Successfully connected to MySQL database.',
                              connected_db=database)
    except Exception as e:
        return render_template('index.html', 
                              status='error', 
                              message=f'Connection failed: {str(e)}')

@app.route('/submit_sentence', methods=['POST'])
def submit_sentence():
    """Handle natural language query submission"""
    sentence = request.form['sentence']
    uri = session.get('uri')
    db_credentials = session.get('db_credentials')

    if not uri or not db_credentials:
        return render_template('index.html',
                              status='error',
                              message='No database connection found. Please connect to a database first.')

    try:
        # Create direct connection to database
        connection = pymysql.connect(
            host=db_credentials['host'],
            user=db_credentials['user'],
            password=db_credentials['password'],
            database=db_credentials['database'],
            cursorclass=pymysql.cursors.DictCursor
        )

        # Get database schema information
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

        # Generate SQL query from natural language
        sql_query = generate_sql_query(schema_dict, sentence)

        if sql_query.startswith("Error:"):
            return render_template('index.html',
                                   status='error',
                                   message=sql_query,
                                   connected_db=session.get('database'),
                                   sentence=sentence)

        # Split and execute each SQL statement safely
        queries = [q.strip() for q in sql_query.split(';') if q.strip()]
        all_results = []
        last_columns = []

        with connection.cursor() as cursor:
            for query in queries:
                cursor.execute(query)
                if cursor.description:  # Only SELECT-type queries return results
                    data = cursor.fetchall()
                    if data:
                        last_columns = list(data[0].keys())
                        all_results = [[row[col] for col in last_columns] for row in data]
                    else:
                        all_results = []
                else:
                    connection.commit()  # For non-SELECT queries like INSERT/UPDATE

        connection.close()

        return render_template(
            'index.html',
            status='success',
            message='Query executed successfully.',
            sql_query=sql_query,
            query_result=all_results,
            columns=last_columns,
            connected_db=session.get('database'),
            sentence=sentence
        )

    except Exception as e:
        return render_template(
            'index.html',
            status='error',
            message=f'Error executing SQL query: {str(e)}',
            sql_query=sql_query if 'sql_query' in locals() else None,
            connected_db=session.get('database'),
            sentence=sentence
        )

@app.route('/disconnect', methods=['POST'])
def disconnect():
    """Disconnect from the database"""
    session.pop('uri', None)
    session.pop('database', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)