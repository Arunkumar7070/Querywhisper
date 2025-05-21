from flask import Flask, request, render_template, session, redirect, url_for
import urllib.parse
import os
import pymysql
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import requests  # For API calls

# Load environment variables from .env
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "default-secret-key")


HUGGINGFACE_API_TOKEN = os.getenv("HUGGINGFACE_API_TOKEN")
HUGGINGFACE_MODEL = os.getenv("HUGGINGFACE_MODEL", "mistralai/Mistral-7B-Instruct-v0.2")

def generate_sql_query(schema_dict, sentence):
    """Generate SQL query from natural language using Hugging Face Inference API"""
    prompt = f"""<s>[INST] You are an SQL assistant. Convert the following natural language question into a valid SQL query using this schema:
    Schema: {schema_dict} , Question:{sentence} Only output the SQL query, without any explanation or additional text. [/INST]</s>"""
    
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
            
            # If the response contains explanation text, try to extract just the SQL
            if "SELECT" in sql_query.upper() or "INSERT" in sql_query.upper() or "UPDATE" in sql_query.upper() or "DELETE" in sql_query.upper():
                lines = sql_query.split('\n')
                sql_lines = []
                for line in lines:
                    if line.strip() and not line.strip().startswith("--"):  # Keep non-empty lines that aren't comments
                        sql_lines.append(line)
                sql_query = '\n'.join(sql_lines)
            
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
            # Get all tables
            cursor.execute("SHOW TABLES")
            table_names = [row[f'Tables_in_{db_credentials["database"]}'] for row in cursor.fetchall()]
            
            schema_dict = {}
            for table in table_names:
                cursor.execute(f"SHOW COLUMNS FROM `{table}`")
                column_details = []
                for col in cursor.fetchall():
                    column_details.append({
                        "name": col['Field'],
                        "type": col['Type'],
                        "key": col['Key'] if 'Key' in col else None
                    })
                schema_dict[table] = column_details
        
        # Generate SQL query from natural language
        sql_query = generate_sql_query(schema_dict, sentence)
        
        # Execute the generated query
        with connection.cursor() as cursor:
            cursor.execute(sql_query)
            data = cursor.fetchall()
            
            # Get column names
            if data:
                columns = list(data[0].keys())
            else:
                columns = []
            
            # Convert dict rows to list format for template
            formatted_data = []
            for row in data:
                formatted_data.append([row[col] for col in columns])
        
        connection.close()
        
        return render_template(
            'index.html',
            status='success',
            message='Query executed successfully.',
            sql_query=sql_query,
            query_result=formatted_data,
            columns=columns,
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