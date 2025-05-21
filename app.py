from flask import Flask, request, render_template
from flask_sqlalchemy import SQLAlchemy
import urllib.parse
import openai
openai.api_key = 'your_api_key_here'

app = Flask(__name__)
db = SQLAlchemy()

def generate_sql_query(schema_dict, sentence):
    prompt = f"""You are an SQL assistant. Convert the following natural language question into a valid SQL query using this schema:
            Schema: {schema_dict} Question: "{sentence}" Only output the SQL query."""
    response = openai.ChatCompletion.create(
    model="gpt-3.5-turbo",  # Or use "mistral" for OpenRouter
    messages=[{"role": "user", "content": prompt}],temperature=0.5)
    return response['choices'][0]['message']['content'].strip()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/getinput', methods=['POST'])
def getinput():
    server = request.form['server']
    database = request.form['database']
    username = request.form['username']
    password = request.form['password']
    try:
        # Encode password for special characters
        password_encoded = urllib.parse.quote(password)
        # Form the SQLAlchemy connection URI
        uri = f"mysql+pymysql://{username}:{password_encoded}@{server}/{database}"
        app.config['SQLALCHEMY_DATABASE_URI'] = uri
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # Disable modification tracking to save resources
        db.init_app(app)# Initialize the database connection
        with app.app_context():
            db.session.execute('SELECT 1')  # Try simple query to test connection
            return render_template('index.html', status='success', message='Successfully connected to MySQL.')
    except Exception as e:
        return render_template('index.html', status='error', message=f'Connection failed: {str(e)}')

@app.route('/submit_sentence', methods=['POST'])
def submit_sentence():
    sentence = request.form['sentence']
    app.config['SQLALCHEMY_DATABASE_URI'] = uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    with app.app_context():
        result = db.session.execute("SHOW TABLES")#Get all table names
        table_names = [row[0] for row in result]
        """
        {
        "table1": ["col1", "col2", "col3"],
        "table2": ["colA", "colB"]
        }
        """
        schema_dict = {}
        for table in table_names:
            columns_result = db.session.execute(f"SHOW COLUMNS FROM `{table}`")
            column_names = [col[0] for col in columns_result]
            schema_dict[table] = column_names
    sql_query = generate_sql_query(schema_dict, sentence)






if __name__ == '__main__':
    app.run(debug=True)
