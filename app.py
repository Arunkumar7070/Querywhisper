from flask import Flask, request, render_template
from flask_sqlalchemy import SQLAlchemy
import urllib.parse

app = Flask(__name__)
db = SQLAlchemy()

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
            # Try a simple query to test connection
            db.session.execute('SELECT 1')
            return "✅ Successfully connected to the MySQL database!"
    except Exception as e:
        return f"❌ Connection failed: {str(e)}"






if __name__ == '__main__':
    app.run(debug=True)